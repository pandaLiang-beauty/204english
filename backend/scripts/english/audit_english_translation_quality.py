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

from app.english.translation_quality import stored_translation_issues, translation_result_issues  # noqa: E402
from app.english.translator import extract_words  # noqa: E402
from app.platform.db import get_connection, rows_to_dicts  # noqa: E402


def _result(
    *,
    sentence_translation: str,
    sentence_segments: list[str],
    translation_segments: list[str],
    word_translations: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "sentence_translation": sentence_translation,
        "sentence_segments": sentence_segments,
        "translation_segments": translation_segments,
        "word_translations": word_translations or {},
        "word_tips": {},
    }


REGRESSION_CASES: list[dict[str, Any]] = [
    {
        "name": "flags_thought_as_background_before_was",
        "source": (
            "The thought of holding a fixed grin as the camera performed its magical duties "
            "was too much to contemplate."
        ),
        "result": _result(
            sentence_translation="一想到要在相机发挥神奇作用时保持固定的咧嘴笑，就让人难以忍受。",
            sentence_segments=[
                "The thought of holding a fixed grin as the camera performed its magical duties",
                "was too much to contemplate.",
            ],
            translation_segments=[
                "一想到要在相机发挥神奇作用时保持固定的咧嘴笑",
                "就让人难以忍受。",
            ],
        ),
        "expect": ["undersegmented_subject_background"],
    },
    {
        "name": "allows_thought_as_background_when_split",
        "source": (
            "The thought of holding a fixed grin as the camera performed its magical duties "
            "was too much to contemplate."
        ),
        "result": _result(
            sentence_translation="一想到要保持固定的咧嘴笑，在相机发挥神奇作用时，就让人难以忍受。",
            sentence_segments=[
                "The thought of holding a fixed grin",
                "as the camera performed its magical duties",
                "was too much to contemplate.",
            ],
            translation_segments=[
                "一想到要保持固定的咧嘴笑",
                "在相机发挥神奇作用时",
                "就让人难以忍受。",
            ],
        ),
        "expect_absent": ["undersegmented_subject_background"],
    },
    {
        "name": "flags_prospect_when_background_before_seemed",
        "source": (
            "The prospect of rebuilding the old local system when public support was already fading "
            "seemed unrealistic."
        ),
        "result": _result(
            sentence_translation="在公众支持已经减弱时，重建旧地方体系的前景似乎并不现实。",
            sentence_segments=[
                "The prospect of rebuilding the old local system when public support was already fading",
                "seemed unrealistic.",
            ],
            translation_segments=[
                "在公众支持已经减弱时，重建旧地方体系的前景",
                "似乎并不现实。",
            ],
        ),
        "expect": ["undersegmented_subject_background"],
    },
    {
        "name": "allows_prospect_when_background_when_split",
        "source": (
            "The prospect of rebuilding the old local system when public support was already fading "
            "seemed unrealistic."
        ),
        "result": _result(
            sentence_translation="重建旧地方体系的前景，在公众支持已经减弱时，似乎并不现实。",
            sentence_segments=[
                "The prospect of rebuilding the old local system",
                "when public support was already fading",
                "seemed unrealistic.",
            ],
            translation_segments=[
                "重建旧地方体系的前景",
                "在公众支持已经减弱时",
                "似乎并不现实。",
            ],
        ),
        "expect_absent": ["undersegmented_subject_background"],
    },
    {
        "name": "flags_problem_while_background_before_is",
        "source": (
            "The problem of measuring social progress while economic life keeps changing "
            "is more difficult than it first appears."
        ),
        "result": _result(
            sentence_translation="在经济生活不断变化时衡量社会进步的问题，比最初看起来更难。",
            sentence_segments=[
                "The problem of measuring social progress while economic life keeps changing",
                "is more difficult than it first appears.",
            ],
            translation_segments=[
                "在经济生活不断变化时衡量社会进步的问题",
                "比最初看起来更难。",
            ],
        ),
        "expect": ["undersegmented_subject_background"],
    },
    {
        "name": "does_not_force_short_background_split",
        "source": "The idea as a whole is useful.",
        "result": _result(
            sentence_translation="这个想法整体上是有用的。",
            sentence_segments=["The idea as a whole", "is useful."],
            translation_segments=["这个想法整体上", "是有用的。"],
        ),
        "expect_absent": ["undersegmented_subject_background"],
    },
]


def _has_issue(issues: list[str], expected: str) -> bool:
    return any(issue == expected or issue.startswith(f"{expected}:") for issue in issues)


def run_regressions() -> int:
    failures: list[dict[str, Any]] = []
    for case in REGRESSION_CASES:
        issues = translation_result_issues(case["result"], [], source_text=case["source"])
        for expected in case.get("expect", []):
            if not _has_issue(issues, expected):
                failures.append({"case": case["name"], "missing": expected, "issues": issues})
        for absent in case.get("expect_absent", []):
            if _has_issue(issues, absent):
                failures.append({"case": case["name"], "unexpected": absent, "issues": issues})
    if failures:
        print(json.dumps({"ok": False, "failures": failures}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "checked": len(REGRESSION_CASES)}, ensure_ascii=False))
    return 0


def _load_long_sentence_rows(limit: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        column_rows = conn.execute("PRAGMA table_info(english_sentences)").fetchall()
        columns = {str(row["name"]) for row in column_rows}
        required = {
            "text",
            "sentence_translation",
            "sentence_segments_json",
            "translation_segments_json",
            "word_translations_json",
            "word_tips_json",
        }
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError(f"english_sentences schema is missing columns: {', '.join(missing)}")
        return rows_to_dicts(
            conn.execute(
                """
                SELECT id, text, sentence_translation, sentence_segments_json, translation_segments_json,
                       word_translations_json, word_tips_json
                FROM english_sentences
                WHERE COALESCE(deleted_at, '') = ''
                  AND COALESCE(sentence_translation, '') <> ''
                  AND COALESCE(sentence_segments_json, '[]') NOT IN ('', '[]')
                  AND LENGTH(text) >= 120
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )


def scan_db(limit: int) -> int:
    try:
        rows = _load_long_sentence_rows(limit)
    except RuntimeError as exc:
        print(json.dumps({"checked": 0, "skipped": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    issue_counts: Counter[str] = Counter()
    issue_rows: list[dict[str, Any]] = []
    for row in rows:
        words = extract_words(str(row.get("text") or ""))
        issues = stored_translation_issues(row, words)
        for issue in issues:
            issue_counts[issue.split(":", 1)[0]] += 1
        if issues:
            issue_rows.append(
                {
                    "id": row["id"],
                    "issues": issues[:8],
                    "text": str(row.get("text") or "")[:220],
                }
            )
    print(
        json.dumps(
            {
                "checked": len(rows),
                "issue_rows": len(issue_rows),
                "issue_counts": dict(issue_counts.most_common()),
                "samples": issue_rows[:10],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if issue_rows else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit English translation quality rules without calling AI.")
    parser.add_argument("--scan-db", action="store_true", help="Scan stored long English sentence translations.")
    parser.add_argument("--limit", type=int, default=30, help="Maximum stored rows to scan with --scan-db.")
    args = parser.parse_args()

    regression_status = run_regressions()
    if args.scan_db:
        db_status = scan_db(max(1, args.limit))
        raise SystemExit(regression_status or db_status)
    raise SystemExit(regression_status)


if __name__ == "__main__":
    main()
