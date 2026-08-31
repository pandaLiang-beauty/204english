from __future__ import annotations

"""Run the V2 English translation pipeline as a resumable, read-only evaluation.

This script deliberately opens the study database in SQLite ``mode=ro`` and
contains no UPDATE/INSERT paths.  Generated candidates are written immediately
to a JSONL audit report instead of being applied to ``english_sentences``.
"""

import argparse
import json
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

from app.english.translation_quality import translation_result_issues  # noqa: E402
from app.english.translator import _translation_source, extract_words, translate_text  # noqa: E402
from app.platform.db import DB_PATH, DATA_DIR  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        params: tuple[int, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        return [dict(row) for row in conn.execute(query, params).fetchall()]


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


def _error_summary(exc: Exception) -> dict[str, str]:
    return {
        "error_type": type(exc).__name__,
        "error": str(exc).strip() or repr(exc),
    }


def _translate_one(row: dict[str, Any], retries: int) -> dict[str, Any]:
    """Call V2 sequentially per sentence; outer executor is the only concurrency."""
    started = time.monotonic()
    words = _words_for_row(row)
    text = str(row.get("text") or "")
    source_text = _translation_source(text)
    last_error: dict[str, str] | None = None

    for attempt in range(1, retries + 2):
        try:
            result = translate_text(text, words=words, feedback=(last_error or {}).get("error", ""))
            issues = translation_result_issues(result, words, source_text=source_text)
            if issues:
                raise RuntimeError("local_quality_issues: " + "; ".join(issues[:12]))
            return {
                "event": "translation",
                "status": "success",
                "id": int(row["id"]),
                "completed_at": _utc_now(),
                "attempts": attempt,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "text": text,
                "source_text": source_text,
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
                    "local_quality_issues": issues,
                },
            }
        except Exception as exc:  # noqa: BLE001 - an evaluation must retain each provider failure.
            last_error = _error_summary(exc)
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
        "words": words,
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
        "database_write_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only, resumable full evaluation of the V2 English translation pipeline."
    )
    parser.add_argument("--workers", type=int, default=4, help="Concurrent sentences; each sentence calls V2 sequentially.")
    parser.add_argument("--retries", type=int, default=1, help="Whole-pipeline retries per failed sentence.")
    parser.add_argument("--limit", type=int, default=0, help="Optional smoke-test limit; zero evaluates every active sentence.")
    parser.add_argument("--output", type=Path, help="JSONL report path; defaults to a timestamped file under data/audits.")
    parser.add_argument("--resume", type=Path, help="Append to this JSONL report and skip its successful sentence ids.")
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.retries < 0:
        parser.error("--retries cannot be negative")
    if args.limit < 0:
        parser.error("--limit cannot be negative")

    if args.resume and args.output and args.resume.resolve() != args.output.resolve():
        parser.error("When --resume is used, --output must be omitted or name that same report")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = args.resume or args.output or (DATA_DIR / "audits" / f"v2-translation-evaluation-{timestamp}.jsonl")
    completed = _completed_ids(report_path) if args.resume else set()
    rows = _load_rows(args.limit or None)
    pending_rows = [row for row in rows if int(row["id"]) not in completed]

    start_event = {
        "event": "start",
        "started_at": _utc_now(),
        "pipeline": "split_translation_v2",
        "database_write_performed": False,
        "target_count": len(rows),
        "skipped_completed": len(rows) - len(pending_rows),
        "pending_count": len(pending_rows),
        "workers": args.workers,
        "retries": args.retries,
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
