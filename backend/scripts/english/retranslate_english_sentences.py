from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.english.translation_quality import (
    row_has_bad_translation,
    stored_translation_issues,
    validate_translation_result,
)
from app.english.translator import _translate_words_only, extract_words, segment_translation, translate_text
from app.platform.db import DATA_DIR, get_connection, rows_to_dicts

def _json_loads(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_loads_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select_ids(*, mode: str, limit: int | None, ids: list[int], segments_only: bool = False) -> list[int]:
    if ids:
        return ids[:limit] if limit else ids

    where = "WHERE COALESCE(deleted_at, '') = ''"
    params: list[Any] = []
    if segments_only:
        where += """
          AND COALESCE(sentence_translation, '') <> ''
          AND COALESCE(sentence_segments_json, '[]') IN ('', '[]')
          AND COALESCE(translation_segments_json, '[]') IN ('', '[]')
        """
    elif mode == "missing":
        where += " AND COALESCE(sentence_translation, '') = ''"

    sql = f"SELECT id FROM english_sentences {where} ORDER BY id"
    if limit and mode != "bad":
        sql += f" LIMIT {int(limit)}"
    with get_connection() as conn:
        selected = [int(row["id"]) for row in conn.execute(sql, params).fetchall()]
    if mode != "bad":
        return selected

    bad_ids: list[int] = []
    for start in range(0, len(selected), 100):
        for row in _load_rows(selected[start : start + 100]):
            if row_has_bad_translation(row, _words_for_row(row)):
                bad_ids.append(int(row["id"]))
                if limit and len(bad_ids) >= limit:
                    return bad_ids
    return bad_ids


def _load_rows(batch_ids: list[int]) -> list[dict[str, Any]]:
    if not batch_ids:
        return []
    placeholders = ",".join(["?"] * len(batch_ids))
    order_sql = " ".join(f"WHEN {sentence_id} THEN {index}" for index, sentence_id in enumerate(batch_ids))
    with get_connection() as conn:
        return rows_to_dicts(
            conn.execute(
                f"""
                SELECT id, text, sentence_translation, sentence_segments_json, translation_segments_json,
                       word_translations_json, word_tips_json
                FROM english_sentences
                WHERE id IN ({placeholders})
                ORDER BY CASE id {order_sql} END
                """,
                batch_ids,
            ).fetchall()
        )


def _words_for_row(row: dict[str, Any]) -> list[str]:
    existing = _json_loads(row.get("word_translations_json"))
    words = list(existing.keys()) or extract_words(str(row.get("text") or ""))
    seen = set()
    result: list[str] = []
    for word in words:
        clean = str(word or "").strip()
        lowered = clean.lower()
        if clean and lowered not in seen:
            seen.add(lowered)
            result.append(clean)
    return result


def _valid_translation(result: dict[str, Any], words: list[str], *, source_text: str = "") -> tuple[bool, str]:
    return validate_translation_result(result, words, source_text=source_text)


def _update_row(sentence_id: int, result: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE english_sentences
            SET sentence_translation = ?,
                sentence_segments_json = ?,
                translation_segments_json = ?,
                word_translations_json = ?,
                word_tips_json = ?,
                updated_at = ?
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (
                str(result.get("sentence_translation") or "").strip(),
                _json_dumps(result.get("sentence_segments") or []),
                _json_dumps(result.get("translation_segments") or []),
                _json_dumps(result.get("word_translations") or {}),
                _json_dumps(result.get("word_tips") or {}),
                _now(),
                sentence_id,
            ),
        )


def _update_segments(sentence_id: int, result: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE english_sentences
            SET sentence_segments_json = ?,
                translation_segments_json = ?,
                updated_at = ?
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (
                _json_dumps(result.get("sentence_segments") or []),
                _json_dumps(result.get("translation_segments") or []),
                _now(),
                sentence_id,
            ),
        )


def _update_words(sentence_id: int, result: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE english_sentences
            SET word_translations_json = ?,
                word_tips_json = ?,
                updated_at = ?
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (
                _json_dumps(result.get("word_translations") or {}),
                _json_dumps(result.get("word_tips") or {}),
                _now(),
                sentence_id,
            ),
        )


def _check_batch(batch_ids: list[int]) -> dict[str, Any]:
    rows = _load_rows(batch_ids)
    issues: list[dict[str, Any]] = []
    for row in rows:
        words = _words_for_row(row)
        row_issues = stored_translation_issues(row, words)
        if row_issues:
            issues.append({"id": row["id"], "issues": row_issues[:6]})
    samples = [
        {
            "id": row["id"],
            "sentence_translation": str(row.get("sentence_translation") or "")[:160],
            "sentence_segments_json": str(row.get("sentence_segments_json") or "")[:260],
            "translation_segments_json": str(row.get("translation_segments_json") or "")[:260],
            "word_translations_json": str(row.get("word_translations_json") or "")[:260],
            "word_tips_json": str(row.get("word_tips_json") or "")[:180],
        }
        for row in rows[:2]
    ]
    return {
        "checked": len(rows),
        "issue_count": len(issues),
        "issues": issues[:10],
        "samples": samples,
    }


def _write_report(report_path: Path, payload: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _translate_with_retries(
    row: dict[str, Any],
    *,
    retries: int,
    segments_only: bool = False,
    words_only: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    words = _words_for_row(row)
    last_error = ""
    for attempt in range(retries + 1):
        try:
            if words_only:
                word_payload = _translate_words_only(
                    str(row.get("text") or ""),
                    words,
                    feedback=last_error if attempt else "",
                )
                result = {
                    "sentence_translation": str(row.get("sentence_translation") or ""),
                    "sentence_segments": _json_loads_list(row.get("sentence_segments_json")),
                    "translation_segments": _json_loads_list(row.get("translation_segments_json")),
                    "word_translations": word_payload.get("word_translations") or {},
                    "word_tips": word_payload.get("word_tips") or {},
                    "items": word_payload.get("items") or [],
                }
                ok, reason = _valid_translation(result, words, source_text=str(row.get("text") or ""))
            elif segments_only:
                result = segment_translation(
                    str(row.get("text") or ""),
                    str(row.get("sentence_translation") or ""),
                    feedback=last_error if attempt else "",
                )
                ok, reason = _valid_translation(result, [], source_text=str(row.get("text") or ""))
            else:
                result = translate_text(
                    str(row.get("text") or ""),
                    words=words,
                    feedback=last_error if attempt else "",
                )
                ok, reason = _valid_translation(result, words, source_text=str(row.get("text") or ""))
            if ok:
                return result, ""
            last_error = reason
        except Exception as exc:  # noqa: BLE001 - batch job records and continues according to policy.
            last_error = f"{type(exc).__name__}:{exc}"
        if attempt < retries:
            time.sleep(1.0 + attempt)
    return None, last_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Retranslate English sentence metadata in batches.")
    parser.add_argument("--apply", action="store_true", help="Write translated results to the database.")
    parser.add_argument("--mode", choices=["all", "missing", "bad"], default="all")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="Comma-separated sentence ids.")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--segments-only", action="store_true", help="Only generate segment pairs from existing sentence translations.")
    parser.add_argument("--words-only", action="store_true", help="Only regenerate word translations/tips from existing translations and segments.")
    parser.add_argument("--stop-on-batch-issue", action="store_true", default=True)
    args = parser.parse_args()
    if args.segments_only and args.words_only:
        parser.error("--segments-only and --words-only cannot be used together")

    selected_ids = [int(item) for item in args.ids.split(",") if item.strip()] if args.ids else []
    target_ids = _select_ids(
        mode=args.mode,
        limit=args.limit or None,
        ids=selected_ids,
        segments_only=args.segments_only,
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = DATA_DIR / "english" / f"retranslate-report-{timestamp}.jsonl"
    print(
        "START",
        {
            "apply": args.apply,
            "mode": args.mode,
            "target_count": len(target_ids),
            "batch_size": args.batch_size,
            "segments_only": args.segments_only,
            "words_only": args.words_only,
            "report_path": str(report_path),
        },
        flush=True,
    )

    total_ok = 0
    total_failed = 0
    for batch_index, start in enumerate(range(0, len(target_ids), args.batch_size), start=1):
        batch_ids = target_ids[start : start + args.batch_size]
        rows = _load_rows(batch_ids)
        batch_ok: list[int] = []
        batch_failed: list[dict[str, Any]] = []
        print(f"BATCH {batch_index} BEGIN ids={batch_ids[0]}..{batch_ids[-1]} count={len(batch_ids)}", flush=True)
        for row in rows:
            result, error = _translate_with_retries(
                row,
                retries=max(0, args.retries),
                segments_only=args.segments_only,
                words_only=args.words_only,
            )
            if not result:
                batch_failed.append({"id": row["id"], "error": error})
                _write_report(report_path, {"event": "failed", "id": row["id"], "error": error})
                continue
            if args.apply:
                if args.words_only:
                    _update_words(int(row["id"]), result)
                elif args.segments_only:
                    _update_segments(int(row["id"]), result)
                else:
                    _update_row(int(row["id"]), result)
            batch_ok.append(int(row["id"]))
            _write_report(
                report_path,
                {
                    "event": "translated",
                    "id": row["id"],
                    "applied": args.apply,
                    "sentence_translation": result.get("sentence_translation"),
                    "sentence_segments": result.get("sentence_segments") or [],
                    "translation_segments": result.get("translation_segments") or [],
                    "word_count": len(result.get("word_translations") or {}),
                    "tip_count": len(result.get("word_tips") or {}),
                },
            )
            if args.sleep:
                time.sleep(args.sleep)

        check = _check_batch(batch_ok) if args.apply and batch_ok else {"checked": 0, "issue_count": 0, "issues": [], "samples": []}
        total_ok += len(batch_ok)
        total_failed += len(batch_failed)
        batch_summary = {
            "batch": batch_index,
            "ok": len(batch_ok),
            "failed": batch_failed,
            "check": check,
            "total_ok": total_ok,
            "total_failed": total_failed,
        }
        print("BATCH_SUMMARY", json.dumps(batch_summary, ensure_ascii=False), flush=True)
        _write_report(report_path, {"event": "batch_summary", **batch_summary})
        if batch_failed or (args.stop_on_batch_issue and check.get("issue_count")):
            print("STOP batch has failures or quality issues", flush=True)
            break

    print(
        "DONE",
        {"target_count": len(target_ids), "total_ok": total_ok, "total_failed": total_failed, "report_path": str(report_path)},
        flush=True,
    )


if __name__ == "__main__":
    main()
