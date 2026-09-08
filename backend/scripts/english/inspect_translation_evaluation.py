from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.translation_quality import translation_result_issues


def _events(path: Path) -> list[dict[str, Any]]:
    contents = path.read_text(encoding="utf-8")
    lines = contents.splitlines()
    if contents and not contents.endswith("\n"):
        lines = lines[:-1]
    return [json.loads(line) for line in lines if line.strip()]


def _candidates(paths: list[Path]) -> dict[int, dict[str, Any]]:
    candidates: dict[int, dict[str, Any]] = {}
    for path in paths:
        for event in _events(path):
            if event.get("event") == "translation":
                candidates[int(event["id"])] = {**event, "report": path.name}
    return candidates


def _decisions(path: Path | None) -> dict[tuple[str, int], str]:
    decisions: dict[tuple[str, int], str] = {}
    if path is not None and path.is_file():
        for event in _events(path):
            report = str(event["report"])
            for identifier in event.get("accepted_ids", []):
                decisions[(report, int(identifier))] = "accepted"
            for identifier in event.get("revision_requests", {}):
                decisions[(report, int(identifier))] = "needs_revision"
    return decisions


def _quality_issues(event: dict[str, Any]) -> list[str]:
    if event.get("status") != "success":
        return [str(event.get("error_type") or "generation_failed")]
    candidate = event["v2"]
    result = {
        **candidate,
        "items": candidate.get("word_items") or [],
        "word_evidence_required": bool(event.get("words")),
    }
    return translation_result_issues(result, event.get("words") or [], source_text=event["source_text"])


def _print_candidate(event: dict[str, Any]) -> None:
    candidate = event.get("v2") or event.get("candidate") or {}
    print(f'\n[{event["id"]}] {event["status"]} ({event["report"]})')
    print("EN:", event.get("source_text") or event.get("text") or "")
    print("ZH:", candidate.get("sentence_translation") or "")
    meanings = [
        f'{word}={str(meaning).removeprefix("本义：").replace("；句中：", " → ")}'
        for word, meaning in (candidate.get("word_translations") or {}).items()
    ]
    print("WORDS:", " | ".join(meanings))
    source_segments = candidate.get("sentence_segments") or []
    target_segments = candidate.get("translation_segments") or []
    for index in range(min(len(source_segments), len(target_segments)) - 1):
        source_left = " ".join(source_segments[index].split()[-5:])
        source_right = " ".join(source_segments[index + 1].split()[:5])
        target_left = target_segments[index][-14:]
        target_right = target_segments[index + 1][:14]
        print(f"CUT {index + 1}: {source_left} / {source_right} <> {target_left} / {target_right}")
    if event.get("status") != "success":
        print("ERROR:", event.get("diagnostic") or event.get("error") or "unknown")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect translation candidates without model scoring or database writes.")
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--decisions", type=Path, help="JSONL source-based review decisions; hide already reviewed candidates.")
    parser.add_argument("--ids", help="Optional comma-separated sentence ids.")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    candidates = _candidates(args.report)
    decisions = _decisions(args.decisions)
    if args.summary:
        issues = {identifier: _quality_issues(event) for identifier, event in candidates.items()}
        issues = {identifier: problems for identifier, problems in issues.items() if problems}
        summary = {
            "generated": len(candidates),
            "statuses": dict(Counter(event["status"] for event in candidates.values())),
            "selected_words": sum(len(event.get("words") or []) for event in candidates.values()),
            "source_review": dict(Counter(decisions.get((event["report"], identifier), "pending") for identifier, event in candidates.items())),
            "local_issues": issues,
            "semantic_accuracy_inferred_from_technical_success": False,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    selected_ids = {int(value) for value in args.ids.split(",") if value.strip()} if args.ids else None
    pending = [
        event for identifier, event in sorted(candidates.items())
        if (selected_ids is not None and identifier in selected_ids)
        or (selected_ids is None and (event["report"], identifier) not in decisions)
    ]
    for event in pending[:args.limit]:
        _print_candidate(event)
    print(f"\nDisplayed {min(args.limit, len(pending))} of {len(pending)} selected/unreviewed candidates.")


if __name__ == "__main__":
    main()
