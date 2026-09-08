from __future__ import annotations

"""Reconcile concurrent focus-word edits without changing approved sentence meanings."""

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english import translator
from scripts.english import evaluate_translation_pipeline as evaluation
from scripts.english import inspect_translation_evaluation as inspection
from scripts.english.repair_translation_evaluation import _digest, _require_complete, _result_payload


SNAPSHOT_FIELDS = ("text", "source_text", "words", "previous", "context_before", "context_after")


def _identity_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    return {field: candidate[field] for field in SNAPSHOT_FIELDS}


def _validate_focus_only_change(original: dict[str, Any], revised: dict[str, Any]) -> None:
    identifier = original["id"]
    if revised["id"] != identifier:
        raise ValueError("Focus reconciliation cannot change sentence identity")
    source = translator._translation_source(original["text"])
    if source != translator._translation_source(revised["text"]) or revised["source_text"] != source:
        raise ValueError(f"English source changed, not just focus metadata: id {identifier}")
    for field in ("context_before", "context_after"):
        if original.get(field) != revised.get(field):
            raise ValueError(f"Reference context changed for id {identifier}")
    old_values = original["previous"]
    new_values = revised["previous"]
    if old_values["sentence_translation"] != new_values["sentence_translation"]:
        raise ValueError(f"Concurrent sentence translation edit requires explicit review: id {identifier}")
    retained = set(original["words"]) & set(revised["words"])
    for field in ("word_translations", "word_tips"):
        if any(old_values[field].get(word, "") != new_values[field].get(word, "") for word in retained):
            raise ValueError(f"Concurrent {field} edit requires explicit review: id {identifier}")
    expected_words = evaluation._words_for_row({
        "text": revised["text"],
        "word_translations_json": json.dumps(new_values["word_translations"], ensure_ascii=False),
    })
    if revised["words"] != expected_words:
        raise ValueError(f"Reconciled selection differs from the observed database: id {identifier}")


def _validate_rebase_provenance(original: dict[str, Any], revised: dict[str, Any]) -> None:
    _validate_focus_only_change(original, revised)
    rebase = revised.get("focus_rebase") or {}
    if rebase.get("baseline_snapshot_sha256") != _digest(_identity_snapshot(original)):
        raise ValueError(f"Focus rebase does not reference the original snapshot: id {original['id']}")
    if rebase.get("current_snapshot_sha256") != _digest(_identity_snapshot(revised)):
        raise ValueError(f"Focus rebase snapshot was altered: id {original['id']}")


def _focus_jobs(
    baseline: dict[int, dict[str, Any]], candidates: dict[int, dict[str, Any]],
    rows: list[dict[str, Any]], approvals: dict[tuple[str, int], str],
) -> dict[int, dict[str, Any]]:
    if set(baseline) != set(candidates) or set(candidates) != {row["id"] for row in rows}:
        raise ValueError("Active sentence ids changed; this is not a focus-only reconciliation")
    jobs: dict[int, dict[str, Any]] = {}
    for row in rows:
        identifier = row["id"]
        candidate = candidates[identifier]
        observed = {
            **copy.deepcopy(candidate), "text": row["text"],
            "source_text": translator._translation_source(row["text"]),
            "words": evaluation._words_for_row(row), "previous": evaluation._previous_snapshot(row),
            "context_before": row["context_before"], "context_after": row["context_after"],
        }
        if _identity_snapshot(observed) == _identity_snapshot(candidate):
            continue
        if approvals.get((candidate["report"], identifier)) != "accepted" or inspection._quality_issues(candidate):
            raise ValueError(f"Reconcile only after the inherited candidate is accepted: id {identifier}")
        _validate_focus_only_change(candidate, observed)
        _validate_focus_only_change(baseline[identifier], observed)
        jobs[identifier] = {"baseline": baseline[identifier], "inherited": candidate, "observed": observed}
    return jobs


def _reconcile_one(job: dict[str, Any]) -> dict[str, Any]:
    inherited = job["inherited"]
    event = copy.deepcopy(job["observed"])
    event.pop("report", None)
    selected_words = event["words"]
    added = [word for word in selected_words if word not in inherited["words"]]
    removed = [word for word in inherited["words"] if word not in selected_words]
    result = copy.deepcopy(inherited["v2"])
    result["items"] = result.pop("word_items", [])
    result["word_evidence_required"] = bool(selected_words)
    feedback = "只为用户新选的重点词制作词卡；逐字引用已审阅的中文定稿，不改变整句含义或分块，不把邻词的否定、数量、比较或宾语吸收到本词释义中。"
    additions = translator.translate_words(
        event["text"], words=added, sentence_translation=result["sentence_translation"],
        feedback=feedback, context_before=event["context_before"], context_after=event["context_after"],
    ) if added else {"items": [], "word_translations": {}, "word_tips": {}}
    if set(additions.get("word_translations") or {}) != set(added):
        raise ValueError("New-word generation changed the requested focus selection")
    by_word = {item["word"]: item for item in [*result["items"], *(additions.get("items") or [])]}
    result["items"] = [by_word[word] for word in selected_words if word in by_word]
    for field in ("word_translations", "word_tips"):
        combined = {**result.get(field, {}), **additions.get(field, {})}
        result[field] = {word: combined[word] for word in selected_words if word in combined}
    event["v2"] = _result_payload(result, selected_words, event["source_text"])
    event["status"] = "success"
    event["completed_at"] = evaluation._utc_now()
    event["focus_rebase"] = {
        "baseline_snapshot_sha256": _digest(_identity_snapshot(job["baseline"])),
        "current_snapshot_sha256": _digest(_identity_snapshot(event)),
        "source_report": inherited["report"],
        "source_candidate_sha256": _digest(inherited["v2"]),
        "added_words": added, "removed_words": removed,
        "executed_stages": ["focus_selection", *(["new_word_cards"] if added else [])],
        "pipeline_sha256": evaluation._pipeline_fingerprint(),
        "feedback": feedback if added else "",
    }
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if len({path.name for path in args.report}) != len(args.report):
        parser.error("input report basenames must be unique")
    for path in [*args.report, args.decisions]:
        _require_complete(path)
    baseline = inspection._candidates(args.report[:1])
    candidates = inspection._candidates(args.report)
    jobs = _focus_jobs(baseline, candidates, evaluation._load_rows(None), inspection._decisions(args.decisions))
    summary = {
        "changed_ids": list(jobs),
        "added_words": {identifier: [word for word in job["observed"]["words"] if word not in job["inherited"]["words"]] for identifier, job in jobs.items()},
        "database_written": False,
    }
    if args.plan_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if not args.output:
        parser.error("--output is required unless --plan-only is used")
    if args.output.resolve() in {path.resolve() for path in [*args.report, args.decisions]}:
        parser.error("output must not overwrite an input")
    contract = {
        "jobs_sha256": _digest(jobs), "pipeline_sha256": evaluation._pipeline_fingerprint(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "provider_base_url": os.getenv("STUDY_ENGLISH_AI_BASE_URL", ""),
        "model": os.getenv("STUDY_ENGLISH_AI_MODEL", ""),
        "temperature": os.getenv("STUDY_ENGLISH_AI_TEMPERATURE", ""),
        "disable_thinking": os.getenv("STUDY_ENGLISH_AI_DISABLE_THINKING", ""),
        "reasoning_effort": os.getenv("STUDY_ENGLISH_AI_REASONING_EFFORT", ""),
    }
    if args.resume:
        _require_complete(args.output)
        events = inspection._events(args.output)
        starts = [event for event in events if event.get("event") == "focus_rebase_start"]
        if not starts or any(event.get("contract") != contract for event in starts):
            parser.error("focus snapshots or inherited candidates changed; use a new report and review")
        completed = {int(event["id"]) for event in events if event.get("event") == "translation" and event.get("status") == "success"}
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8"):
            pass
        args.output.chmod(0o600)
        completed = set()
    evaluation._append_report(args.output, {"event": "focus_rebase_start", "contract": contract, "started_at": evaluation._utc_now(), **summary})
    for identifier, job in jobs.items():
        if identifier in completed:
            continue
        event = _reconcile_one(job)
        evaluation._append_report(args.output, event)
        print(json.dumps({"id": identifier, "status": "success", "added_words": event["focus_rebase"]["added_words"]}, ensure_ascii=False), flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
