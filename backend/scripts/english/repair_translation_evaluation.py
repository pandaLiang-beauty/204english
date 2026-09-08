from __future__ import annotations

"""Repair reviewed evaluation candidates without writing to the study database."""

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english import translator
from app.english.translation_quality import segmentation_advisory_issues, translation_result_issues
from scripts.english import evaluate_translation_pipeline as evaluation
from scripts.english import inspect_translation_evaluation as inspection


STAGES = {"sentence", "words", "segments", "words_and_segments"}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_complete(path: Path) -> None:
    contents = path.read_bytes()
    if contents and not contents.endswith(b"\n"):
        raise ValueError(f"Report has an incomplete final line: {path}")


def _review_requests(path: Path) -> dict[tuple[str, int], str]:
    requests: dict[tuple[str, int], str] = {}
    _require_complete(path)
    for event in inspection._events(path):
        report = str(event["report"])
        for identifier in event.get("accepted_ids", []):
            requests.pop((report, int(identifier)), None)
        for identifier, feedback in event.get("revision_requests", {}).items():
            if not isinstance(feedback, str) or not feedback.strip():
                raise ValueError(f"Empty review feedback: {report}, {identifier}")
            requests[(report, int(identifier))] = feedback.strip()
    return requests


def _load_routes(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Repair routes must be an object keyed by sentence id")
    routes: dict[int, dict[str, Any]] = {}
    for identifier, route in values.items():
        sentence_id = int(identifier)
        if sentence_id <= 0 or sentence_id in routes or not isinstance(route, dict):
            raise ValueError(f"Invalid or duplicate repair route: {identifier}")
        if set(route) - {"stage", "words"} or route.get("stage") not in STAGES:
            raise ValueError(f"Invalid repair stage or fields: {identifier}")
        routes[sentence_id] = route
    return routes


def _review_history(candidate: dict[str, Any]) -> list[str]:
    values = candidate.get("review_history") or []
    if not isinstance(values, list):
        raise ValueError("Review history must be a list of source-based feedback strings")
    history: list[str] = []
    for value in [*values, candidate.get("review_feedback") or ""]:
        if not isinstance(value, str):
            raise ValueError("Review history entries must be strings")
        value = value.strip()
        if value and value not in history:
            history.append(value)
    return history


def _repair_feedback(candidate: dict[str, Any], feedback: str) -> str:
    history = _review_history(candidate)
    if not history:
        return feedback
    previous_translation = str((candidate.get("v2") or {}).get("sentence_translation") or "")
    return "\n\n".join(part for part in (
        "历史审阅约束（用于防止已纠正的问题回退；历史中的阶段安排不限制本轮任务，解释冲突以本轮要求为准）：\n"
        + "\n".join(f"{index}. {item}" for index, item in enumerate(history, start=1)),
        f"上轮中文候选（可能仍有下述问题，须对照英文核实；只改需要修复的内容）：\n{previous_translation}" if previous_translation else "",
        f"本轮修订要求（优先执行）：\n{feedback}",
    ) if part)


def _build_plan(
    reports: list[Path], decisions: Path, routes: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    if len({path.name for path in reports}) != len(reports):
        raise ValueError("Input report basenames must be unique for review provenance")
    candidates: dict[int, dict[str, Any]] = {}
    for path in reports:
        _require_complete(path)
        for identifier, candidate in inspection._candidates([path]).items():
            history = _review_history(candidates.get(identifier, {}))
            for previous_feedback in _review_history(candidate):
                if previous_feedback not in history:
                    history.append(previous_feedback)
            candidates[identifier] = {**candidate, "review_history": history} if history else candidate
    requests = _review_requests(decisions)
    plan: dict[int, dict[str, Any]] = {}
    for identifier, candidate in sorted(candidates.items()):
        feedback = requests.get((candidate["report"], identifier))
        if feedback is None:
            continue
        if not isinstance(candidate.get("previous"), dict):
            raise ValueError(f"Missing original database snapshot for id {identifier}")
        route = routes.get(identifier, {"stage": "sentence"})
        stage = route["stage"]
        words = route.get("words", [])
        if stage in {"words", "words_and_segments"}:
            if not isinstance(words, list) or not words or any(not isinstance(word, str) for word in words):
                raise ValueError(f"Explicit repair word list required for id {identifier}")
            if len(words) != len(set(words)) or not set(words).issubset(candidate.get("words") or []):
                raise ValueError(f"Repair words differ from the selected words for id {identifier}")
        elif words:
            raise ValueError(f"Unexpected word subset for stage {stage}, id {identifier}")
        if stage != "sentence" and candidate.get("status") != "success":
            raise ValueError(f"Partial repair requires a complete candidate for id {identifier}")
        plan[identifier] = {"candidate": candidate, "stage": stage, "words": words, "feedback": feedback}
    unexpected = sorted(set(routes) - set(plan))
    if unexpected:
        raise ValueError(f"Routes refer to candidates without an outstanding review request: {unexpected}")
    return plan


def _result_payload(result: dict[str, Any], words: list[str], source: str) -> dict[str, Any]:
    issues = translation_result_issues(result, words, source_text=source)
    if issues:
        raise translator.TranslationQualityError(
            "修订结果未通过本地校验。", "; ".join(issues), result,
        )
    return {
        "sentence_translation": result["sentence_translation"],
        "sentence_segments": result.get("sentence_segments") or [],
        "translation_segments": result.get("translation_segments") or [],
        "word_translations": result.get("word_translations") or {},
        "word_tips": result.get("word_tips") or {},
        "word_items": result.get("items") or [],
        "quality_audit": result.get("quality_audit") or {},
        "local_quality_issues": [],
        "segmentation_advisory_issues": segmentation_advisory_issues(result, source_text=source),
    }


def _repair_once(job: dict[str, Any], feedback: str) -> tuple[dict[str, Any], list[str]]:
    candidate = job["candidate"]
    source = candidate["source_text"]
    words = candidate.get("words") or []
    context = {
        "context_before": candidate.get("context_before") or [],
        "context_after": candidate.get("context_after") or [],
    }
    if job["stage"] == "sentence":
        result = translator.translate_text(candidate["text"], words=words, feedback=feedback, **context)
        result["word_evidence_required"] = bool(words)
        return _result_payload(result, words, source), ["sentence_draft", "sentence_review", "word_cards", "segments"]

    result = copy.deepcopy(candidate["v2"])
    result["items"] = result.pop("word_items", [])
    result["word_evidence_required"] = bool(words)
    stages: list[str] = []
    if job["stage"] in {"words", "words_and_segments"}:
        repair_words = job["words"]
        repaired = translator.translate_words(
            candidate["text"], words=repair_words,
            sentence_translation=result["sentence_translation"], feedback=feedback, **context,
        )
        if set(repaired.get("word_translations") or {}) != set(repair_words):
            raise ValueError("Word repair changed the requested word selection")
        by_word = {item["word"]: item for item in result["items"] if item["word"] not in repair_words}
        by_word.update({item["word"]: item for item in repaired.get("items") or []})
        result["items"] = [by_word[word] for word in words if word in by_word]
        for field in ("word_translations", "word_tips"):
            result[field] = {word: value for word, value in result.get(field, {}).items() if word not in repair_words}
            result[field].update(repaired.get(field) or {})
        stages.append("word_cards")
    if job["stage"] in {"segments", "words_and_segments"}:
        segmented = translator.segment_translation(source, result["sentence_translation"], feedback=feedback)
        for field in ("sentence_segments", "translation_segments"):
            result[field] = segmented.get(field) or []
        stages.append("segments")
        issues = translation_result_issues(result, words, source_text=source)
        if issues and not any(translator._is_sentence_or_word_issue(issue) for issue in issues):
            result = translator._single_segment_fallback(source, result)
            stages.append("safe_single_block_fallback")
    return _result_payload(result, words, source), stages


def _repair_one(job: dict[str, Any], retries: int) -> dict[str, Any]:
    started = time.monotonic()
    source = job["candidate"]
    event = copy.deepcopy(source)
    for field in ("report", "candidate", "error", "error_type", "diagnostic"):
        event.pop(field, None)
    event["review_feedback"] = job["feedback"]
    event["review_history"] = _review_history(source)
    if job["feedback"] not in event["review_history"]:
        event["review_history"].append(job["feedback"])
    event["repair"] = {
        "source_report": source["report"],
        "source_candidate_sha256": _digest(source.get("v2") or source.get("candidate")),
        "requested_stage": job["stage"],
        "requested_words": job["words"],
        "pipeline_sha256": evaluation._pipeline_fingerprint(),
        "inherited_full_pipeline_candidate": job["stage"] != "sentence",
    }
    last_error: dict[str, str] = {}
    last_candidate: dict[str, Any] | None = None
    for attempt in range(1, retries + 2):
        feedback = "\n\n".join(value for value in (
            job["feedback"], last_error.get("diagnostic") or last_error.get("error", ""),
        ) if value)
        try:
            payload, stages = _repair_once(job, _repair_feedback(source, feedback))
            event["v2"] = payload
            event["status"] = "success"
            event["repair"]["executed_stages"] = stages
            break
        except Exception as exc:
            last_error = evaluation._error_summary(exc)
            last_candidate = getattr(exc, "candidate", None)
            if attempt <= retries:
                time.sleep(float(attempt))
    else:
        event["status"] = "failed"
        event.pop("v2", None)
        event["candidate"] = last_candidate
        event.update(last_error)
    event["attempts"] = attempt
    event["completed_at"] = evaluation._utc_now()
    event["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return event


def _validate_resume(path: Path, contract: dict[str, Any]) -> set[int]:
    _require_complete(path)
    events = inspection._events(path)
    starts = [event for event in events if event.get("event") == "repair_start"]
    if not starts or any(event.get("contract") != contract for event in starts):
        raise ValueError("Repair resume contract changed: inputs, feedback, stages, model or pipeline differ")
    latest = {int(event["id"]): event for event in events if event.get("event") == "translation"}
    return {identifier for identifier, event in latest.items() if event.get("status") == "success"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--routes-json", type=Path, help="Explicit partial-stage routes; other rejected ids rerun the full pipeline.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()
    if args.workers < 1 or args.retries < 0:
        parser.error("workers must be positive and retries nonnegative")
    plan = _build_plan(args.report, args.decisions, _load_routes(args.routes_json))
    summary = {"selected": len(plan), "stages": dict(Counter(job["stage"] for job in plan.values()))}
    if args.plan_only:
        print(json.dumps({**summary, "ids": list(plan)}, ensure_ascii=False, indent=2))
        return
    if not args.output:
        parser.error("--output is required unless --plan-only is used")
    inputs = [*args.report, args.decisions, *([args.routes_json] if args.routes_json else [])]
    if args.output.resolve() in {path.resolve() for path in inputs}:
        parser.error("output must not overwrite an input or review ledger")
    if not translator.translation_configured():
        parser.error("dedicated English translation provider configuration is required")
    contract = {
        "plan_sha256": _digest(plan),
        "pipeline_sha256": evaluation._pipeline_fingerprint(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "provider_base_url": os.getenv("STUDY_ENGLISH_AI_BASE_URL", ""),
        "model": os.getenv("STUDY_ENGLISH_AI_MODEL", ""),
        "temperature": os.getenv("STUDY_ENGLISH_AI_TEMPERATURE", ""),
        "disable_thinking": os.getenv("STUDY_ENGLISH_AI_DISABLE_THINKING", ""),
        "reasoning_effort": os.getenv("STUDY_ENGLISH_AI_REASONING_EFFORT", ""),
        "timeout_seconds": os.getenv("STUDY_ENGLISH_AI_TIMEOUT_SECONDS", ""),
        "requests_per_minute": os.getenv("STUDY_ENGLISH_AI_REQUESTS_PER_MINUTE", ""),
        "workers": args.workers,
        "retries": args.retries,
    }
    if args.resume:
        completed = _validate_resume(args.output, contract)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8"):
            pass
        args.output.chmod(0o600)
        completed = set()
    evaluation._append_report(args.output, {
        "event": "repair_start", "started_at": evaluation._utc_now(), "contract": contract, **summary,
    })
    pending = {identifier: job for identifier, job in plan.items() if identifier not in completed}
    print(json.dumps({**summary, "pending": len(pending), "output": str(args.output)}, ensure_ascii=False), flush=True)
    counts: Counter[str] = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(_repair_one, job, args.retries): identifier for identifier, job in pending.items()}
        for future in as_completed(futures):
            event = future.result()
            evaluation._append_report(args.output, event)
            counts[event["status"]] += 1
            print("PROGRESS " + json.dumps({
                "completed": sum(counts.values()), "pending": len(pending), "id": event["id"],
                "status": event["status"], "stage": event["repair"]["requested_stage"],
            }, ensure_ascii=False), flush=True)
    evaluation._append_report(args.output, {"event": "repair_summary", "completed_at": evaluation._utc_now(), "statuses": dict(counts)})
    print(json.dumps({"statuses": dict(counts), "database_written": False}, ensure_ascii=False), flush=True)
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
