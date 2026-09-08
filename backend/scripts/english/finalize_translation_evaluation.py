from __future__ import annotations

"""Export only source-reviewed, complete translation candidates for application."""

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.english import evaluate_translation_pipeline as evaluation
from scripts.english import inspect_translation_evaluation as inspection
from scripts.english.repair_translation_evaluation import _digest, _require_complete
from scripts.english.reconcile_translation_focus import SNAPSHOT_FIELDS, _validate_rebase_provenance


def _accepted_candidates(reports: list[Path], decisions: Path) -> dict[int, dict[str, Any]]:
    if not reports or len({path.name for path in reports}) != len(reports):
        raise ValueError("Provide a baseline report followed by uniquely named repair reports")
    for path in [*reports, decisions]:
        _require_complete(path)
    baseline = inspection._candidates(reports[:1])
    candidates = inspection._candidates(reports)
    approvals = inspection._decisions(decisions)
    if not baseline or set(candidates) != set(baseline):
        raise ValueError("Final candidates must have exactly the baseline id coverage")
    for identifier, candidate in sorted(candidates.items()):
        if approvals.get((candidate["report"], identifier)) != "accepted":
            raise ValueError(f"Latest candidate is not source-reviewed and accepted: {candidate['report']}, id {identifier}")
        changed_fields = [field for field in SNAPSHOT_FIELDS if field not in candidate or candidate[field] != baseline[identifier].get(field)]
        if changed_fields:
            if not candidate.get("focus_rebase"):
                raise ValueError(f"Repair changed the original snapshot for id {identifier}: {changed_fields}")
            _validate_rebase_provenance(baseline[identifier], candidate)
        issues = inspection._quality_issues(candidate)
        if issues:
            raise ValueError(f"Final candidate fails local/evidence validation: id {identifier}: {issues}")
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, action="append", required=True, help="Baseline first, then repairs in chronological order.")
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {path.resolve() for path in [*args.report, args.decisions]}:
        parser.error("output must not overwrite an input report or review ledger")
    candidates = _accepted_candidates(args.report, args.decisions)
    ledger_hash = hashlib.sha256(args.decisions.read_bytes()).hexdigest()
    summary = {
        "event": "reviewed_export",
        "created_at": evaluation._utc_now(),
        "count": len(candidates),
        "selected_words": sum(len(candidate["words"]) for candidate in candidates.values()),
        "origins": dict(Counter(candidate["report"] for candidate in candidates.values())),
        "review_ledger_sha256": ledger_hash,
        "input_reports": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in args.report},
        "validation_pipeline_sha256": evaluation._pipeline_fingerprint(),
        "semantic_accuracy_inferred_from_technical_success": False,
        "database_written": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        args.output.chmod(0o600)
        handle.write(json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n")
        for identifier, candidate in sorted(candidates.items()):
            exported = copy.deepcopy(candidate)
            exported.pop("report")
            exported["source_review"] = {
                "status": "accepted",
                "report": candidate["report"],
                "candidate_sha256": _digest(candidate["v2"]),
                "ledger_sha256": ledger_hash,
            }
            handle.write(json.dumps(exported, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
    print(json.dumps({**summary, "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
