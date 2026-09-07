from __future__ import annotations

"""Run the V2 English translation pipeline as a resumable, read-only evaluation.

This script deliberately opens the study database in SQLite ``mode=ro`` and
contains no UPDATE/INSERT paths.  Generated candidates are written immediately
to a JSONL audit report instead of being applied to ``english_sentences``.
"""

import argparse
import hashlib
import json
import os
import random
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.translation_quality import (  # noqa: E402
    segmentation_advisory_issues,
    translation_result_issues,
)
from app.english.translator import (  # noqa: E402
    MAX_REFERENCE_CONTEXT_ITEMS,
    SEGMENTATION_CONTRACT,
    TRANSLATION_PRECISION_RULES,
    _translation_source,
    extract_words,
    translate_text,
)
from app.platform.db import DB_PATH, DATA_DIR  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prompt_fingerprint() -> str:
    prompt = f"{TRANSLATION_PRECISION_RULES}\n---SEGMENTATION---\n{SEGMENTATION_CONTRACT}"
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _pipeline_fingerprint() -> str:
    digest = hashlib.sha256()
    for filename in ("translator.py", "translation_quality.py", "translation_transport.py", "translation_glossary.py"):
        digest.update(filename.encode("utf-8"))
        digest.update((ROOT / "app" / "english" / filename).read_bytes())
    return digest.hexdigest()


def _json_loads_dict(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _words_for_row(row: dict[str, Any]) -> list[str]:
    """Keep the existing focus-word selection when it exists."""
    candidates = list(_json_loads_dict(row.get("word_translations_json")).keys())
    if not candidates:
        candidates = extract_words(str(row.get("text") or ""))

    words: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        word = str(candidate or "").strip().strip(".,;:!?，。；：！？、()[]{}\"“”‘’")
        lowered = word.casefold()
        if word and lowered not in seen:
            words.append(word)
            seen.add(lowered)
    return words


def _load_rows(limit: int | None) -> list[dict[str, Any]]:
    """Read current rows without creating a WAL file or modifying the database."""
    db_uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        query = """
            SELECT id, text, sentence_translation, sentence_segments_json,
                   translation_segments_json, word_translations_json,
                   word_tips_json
            FROM english_sentences
            WHERE COALESCE(deleted_at, '') = ''
            ORDER BY id
        """
        rows = [dict(row) for row in conn.execute(query).fetchall()]
    for index, row in enumerate(rows):
        row["context_before"] = [
            _translation_source(str(item.get("text") or ""))
            for item in rows[max(0, index - MAX_REFERENCE_CONTEXT_ITEMS) : index]
        ]
        row["context_after"] = [
            _translation_source(str(item.get("text") or ""))
            for item in rows[index + 1 : index + 1 + MAX_REFERENCE_CONTEXT_ITEMS]
        ]
    return rows[:limit] if limit is not None else rows


def _append_report(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


def _completed_ids(path: Path) -> set[int]:
    if not path.exists():
        raise FileNotFoundError(f"Resume report does not exist: {path}")
    completed: set[int] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}") from exc
            if event.get("event") == "translation" and event.get("status") == "success":
                try:
                    completed.add(int(event["id"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Missing valid sentence id in {path} at line {line_number}") from exc
    return completed


def _validate_resume_compatibility(path: Path) -> None:
    """Refuse to combine successful rows produced by different contracts."""
    expected = {
        "pipeline": "split_translation_v2",
        "provider_base_url": os.getenv("STUDY_ENGLISH_AI_BASE_URL", ""),
        "model": os.getenv("STUDY_ENGLISH_AI_MODEL", ""),
        "prompt_sha256": _prompt_fingerprint(),
        "pipeline_sha256": _pipeline_fingerprint(),
        "context_window_each_side": MAX_REFERENCE_CONTEXT_ITEMS,
    }
    starts: list[tuple[int, dict[str, Any]]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}") from exc
            if event.get("event") == "start":
                starts.append((line_number, event))
    if not starts:
        raise ValueError(f"Resume report has no start metadata: {path}")
    for line_number, event in starts:
        missing = [key for key in expected if key not in event]
        if missing:
            raise ValueError(
                f"Resume report start event at line {line_number} lacks: {','.join(missing)}"
            )
        mismatches = [
            key for key, value in expected.items()
            if event.get(key) != value
        ]
        if mismatches:
            raise ValueError(
                "Resume report was produced with a different evaluation contract "
                f"at line {line_number}: {','.join(mismatches)}"
            )


def _error_summary(exc: Exception) -> dict[str, str]:
    summary = {
        "error_type": type(exc).__name__,
        "error": str(exc).strip() or repr(exc),
    }
    diagnostic = str(getattr(exc, "diagnostic", "") or "").strip()
    if diagnostic and diagnostic != summary["error"]:
        summary["diagnostic"] = diagnostic[:2000]
    return summary


def _translate_one(row: dict[str, Any], retries: int) -> dict[str, Any]:
    """Call V2 sequentially per sentence; outer executor is the only concurrency."""
    started = time.monotonic()
    words = _words_for_row(row)
    text = str(row.get("text") or "")
    source_text = _translation_source(text)
    context_before = list(row.get("context_before") or [])
    context_after = list(row.get("context_after") or [])
    last_error: dict[str, str] | None = None
    last_candidate: dict[str, Any] | None = None

    for attempt in range(1, retries + 2):
        try:
            result = translate_text(
                text,
                words=words,
                feedback=(last_error or {}).get("diagnostic") or (last_error or {}).get("error", ""),
                context_before=context_before,
                context_after=context_after,
            )
            issues = translation_result_issues(result, words, source_text=source_text)
            if issues:
                raise RuntimeError("local_quality_issues: " + "; ".join(issues[:12]))
            advisory = segmentation_advisory_issues(result, source_text=source_text)
            return {
                "event": "translation",
                "status": "success",
                "id": int(row["id"]),
                "completed_at": _utc_now(),
                "attempts": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "text": text,
                "source_text": source_text,
                "context_before": context_before,
                "context_after": context_after,
                "words": words,
                "previous": {
                    "sentence_translation": str(row.get("sentence_translation") or ""),
                    "sentence_segments": _json_loads_list(row.get("sentence_segments_json")),
                    "translation_segments": _json_loads_list(row.get("translation_segments_json")),
                    "word_translations": _json_loads_dict(row.get("word_translations_json")),
                    "word_tips": _json_loads_dict(row.get("word_tips_json")),
                },
                "v2": {
                    "sentence_translation": str(result.get("sentence_translation") or ""),
                    "sentence_segments": result.get("sentence_segments") or [],
                    "translation_segments": result.get("translation_segments") or [],
                    "word_translations": result.get("word_translations") or {},
                    "word_tips": result.get("word_tips") or {},
                    "word_items": result.get("items") or [],
                    "quality_audit": result.get("quality_audit") or {},
                    "local_quality_issues": issues,
                    "segmentation_advisory_issues": advisory,
                },
            }
        except Exception as exc:  # noqa: BLE001 - an evaluation must retain each provider failure.
            last_error = _error_summary(exc)
            last_candidate = getattr(exc, "candidate", None)
            if attempt <= retries:
                time.sleep(float(attempt))

    return {
        "event": "translation",
        "status": "failed",
        "id": int(row["id"]),
        "completed_at": _utc_now(),
        "attempts": retries + 1,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "text": text,
        "source_text": source_text,
        "context_before": context_before,
        "context_after": context_after,
        "words": words,
        "candidate": last_candidate,
        **(last_error or {"error_type": "UnknownError", "error": "translation failed"}),
    }


def _json_loads_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _summary(events: list[dict[str, Any]], target_count: int, skipped: int) -> dict[str, Any]:
    successes = [event for event in events if event.get("status") == "success"]
    failures = [event for event in events if event.get("status") == "failed"]
    elapsed = [float(event["elapsed_seconds"]) for event in successes]
    error_types = Counter(str(event.get("error_type") or "UnknownError") for event in failures)
    quality_issues = Counter(
        issue.split(":", 1)[0]
        for event in successes
        for issue in event.get("v2", {}).get("local_quality_issues", [])
    )
    advisory_issues = Counter(
        issue.split(":", 1)[0]
        for event in successes
        for issue in event.get("v2", {}).get("segmentation_advisory_issues", [])
    )
    return {
        "event": "summary",
        "completed_at": _utc_now(),
        "target_count": target_count,
        "skipped_completed": skipped,
        "attempted_this_run": len(events),
        "success": len(successes),
        "failed": len(failures),
        "elapsed_seconds": {
            "mean": round(sum(elapsed) / len(elapsed), 3) if elapsed else 0.0,
            "median": round(median(elapsed), 3) if elapsed else 0.0,
            "p95": round(_percentile(elapsed, 0.95), 3),
            "max": round(max(elapsed), 3) if elapsed else 0.0,
        },
        "failure_types": dict(error_types.most_common()),
        "local_quality_issue_types": dict(quality_issues.most_common()),
        "segmentation_advisory_issue_types": dict(advisory_issues.most_common()),
        "database_write_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only, resumable full evaluation of the V2 English translation pipeline."
    )
    parser.add_argument("--workers", type=int, default=4, help="Concurrent sentences; each sentence calls V2 sequentially.")
    parser.add_argument("--retries", type=int, default=1, help="Whole-pipeline retries per failed sentence.")
    parser.add_argument("--limit", type=int, default=0, help="Optional smoke-test limit; zero evaluates every active sentence.")
    parser.add_argument("--sample-size", type=int, default=0, help="Uniform random sample of active sentences; does not write the database.")
    parser.add_argument("--seed", type=int, default=0, help="Reproducible random sample seed.")
    parser.add_argument(
        "--ids",
        help="Optional comma-separated sentence ids for a focused regression run; cannot be combined with --limit.",
    )
    parser.add_argument("--output", type=Path, help="JSONL report path; defaults to a timestamped file under data/audits.")
    parser.add_argument("--resume", type=Path, help="Append to this JSONL report and skip its successful sentence ids.")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.retries < 0:
        parser.error("--retries cannot be negative")
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.sample_size < 0:
        parser.error("--sample-size cannot be negative")
    if args.sample_size and (args.ids or args.limit):
        parser.error("--sample-size cannot be combined with --ids or --limit")
    if args.ids and args.limit:
        parser.error("--ids cannot be combined with --limit")

    selected_ids: set[int] | None = None
    if args.ids:
        try:
            selected_ids = {int(value.strip()) for value in args.ids.split(",") if value.strip()}
        except ValueError:
            parser.error("--ids must contain only comma-separated integers")
        if not selected_ids:
            parser.error("--ids must contain at least one sentence id")

    if args.resume and args.output and args.resume.resolve() != args.output.resolve():
        parser.error("When --resume is used, --output must be omitted or name that same report")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = args.resume or args.output or (DATA_DIR / "audits" / f"v2-translation-evaluation-{timestamp}.jsonl")
    if args.resume:
        try:
            _validate_resume_compatibility(report_path)
        except (FileNotFoundError, ValueError) as exc:
            parser.error(str(exc))
    completed = _completed_ids(report_path) if args.resume else set()
    rows = _load_rows(args.limit or None)
    population_count = len(rows)
    if args.sample_size:
        if args.sample_size > len(rows):
            parser.error("--sample-size exceeds the active sentence count")
        rows = sorted(random.Random(args.seed).sample(rows, args.sample_size), key=lambda row: int(row["id"]))
    if selected_ids is not None:
        rows = [row for row in rows if int(row["id"]) in selected_ids]
        missing_ids = selected_ids - {int(row["id"]) for row in rows}
        if missing_ids:
            parser.error(f"unknown or inactive sentence ids: {','.join(str(value) for value in sorted(missing_ids))}")
    pending_rows = [row for row in rows if int(row["id"]) not in completed]

    start_event = {
        "event": "start",
        "started_at": _utc_now(),
        "pipeline": "split_translation_v2",
        "provider_base_url": os.getenv("STUDY_ENGLISH_AI_BASE_URL", ""),
        "model": os.getenv("STUDY_ENGLISH_AI_MODEL", ""),
        "prompt_sha256": _prompt_fingerprint(),
        "pipeline_sha256": _pipeline_fingerprint(),
        "database_write_performed": False,
        "target_count": len(rows),
        "skipped_completed": len(rows) - len(pending_rows),
        "pending_count": len(pending_rows),
        "workers": args.workers,
        "retries": args.retries,
        "context_window_each_side": MAX_REFERENCE_CONTEXT_ITEMS,
        "requests_per_minute": os.getenv("STUDY_ENGLISH_AI_REQUESTS_PER_MINUTE", ""),
        "provider_retries": os.getenv("STUDY_ENGLISH_AI_MAX_RETRIES", ""),
        "sample_seed": args.seed if args.sample_size else None,
        "population_count": population_count,
        "selected_ids": [int(row["id"]) for row in rows],
    }
    _append_report(report_path, start_event)
    print("START", json.dumps({**start_event, "report_path": str(report_path)}, ensure_ascii=False), flush=True)

    events: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="v2-translation") as executor:
        futures = {
            executor.submit(_translate_one, row, args.retries): row["id"]
            for row in pending_rows
        }
        for index, future in enumerate(as_completed(futures), start=1):
            sentence_id = futures[future]
            try:
                event = future.result()
            except Exception as exc:  # Defensive: worker should return failures, never raise.
                event = {
                    "event": "translation",
                    "status": "failed",
                    "id": int(sentence_id),
                    "completed_at": _utc_now(),
                    "attempts": 0,
                    "elapsed_seconds": 0.0,
                    **_error_summary(exc),
                }
            events.append(event)
            _append_report(report_path, event)
            print(
                "PROGRESS",
                json.dumps(
                    {
                        "completed_this_run": index,
                        "pending": len(pending_rows),
                        "id": event["id"],
                        "status": event["status"],
                        "elapsed_seconds": event["elapsed_seconds"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    summary = _summary(events, len(rows), len(rows) - len(pending_rows))
    _append_report(report_path, summary)
    print("DONE", json.dumps({**summary, "report_path": str(report_path)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
