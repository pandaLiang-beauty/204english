from __future__ import annotations

"""Safely apply a completed read-only translation evaluation to the database."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.translation_quality import translation_result_issues  # noqa: E402
from app.english.translator import _translation_source  # noqa: E402
from app.platform.db import DB_PATH, begin_immediate, get_connection, rows_to_dicts  # noqa: E402


TRANSLATION_COLUMNS = (
    "sentence_translation",
    "sentence_segments_json",
    "translation_segments_json",
    "word_translations_json",
    "word_tips_json",
)


def _json_loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value or json.dumps(fallback))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid stored JSON: {str(value)[:160]}") from exc


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _latest_candidates(report_path: Path) -> dict[int, dict[str, Any]]:
    if not report_path.is_file():
        raise FileNotFoundError(f"Evaluation report does not exist: {report_path}")
    latest: dict[int, dict[str, Any]] = {}
    with report_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {report_path}:{line_number}") from exc
            if event.get("event") != "translation":
                continue
            try:
                latest[int(event["id"])] = event
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid translation event at {report_path}:{line_number}") from exc

    failures = sorted(identifier for identifier, event in latest.items() if event.get("status") != "success")
    if failures:
        raise ValueError(f"The report has unresolved failed ids: {failures[:20]}")
    if not latest:
        raise ValueError("The report has no successful translation candidates")
    return latest


def _current_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT id, text, sentence_translation, sentence_segments_json,
                   translation_segments_json, word_translations_json,
                   word_tips_json
            FROM english_sentences
            WHERE COALESCE(deleted_at, '') = ''
            ORDER BY id
            """
        ).fetchall()
    )


def _previous_value(event: dict[str, Any], db_column: str) -> Any:
    previous = event.get("previous")
    if not isinstance(previous, dict):
        raise ValueError(f"Report id {event.get('id')} has no previous-value snapshot")
    mapping = {
        "sentence_translation": "sentence_translation",
        "sentence_segments_json": "sentence_segments",
        "translation_segments_json": "translation_segments",
        "word_translations_json": "word_translations",
        "word_tips_json": "word_tips",
    }
    key = mapping[db_column]
    if key not in previous:
        raise ValueError(f"Report id {event.get('id')} is missing previous.{key}")
    return previous[key]


def _current_value(row: dict[str, Any], db_column: str) -> Any:
    if db_column == "sentence_translation":
        return str(row.get(db_column) or "")
    fallback = {} if db_column.startswith("word_") else []
    return _json_loads(row.get(db_column), fallback)


def _candidate_value(event: dict[str, Any], db_column: str) -> Any:
    candidate = event.get("v2")
    if not isinstance(candidate, dict):
        raise ValueError(f"Report id {event.get('id')} has no V2 candidate")
    mapping = {
        "sentence_translation": "sentence_translation",
        "sentence_segments_json": "sentence_segments",
        "translation_segments_json": "translation_segments",
        "word_translations_json": "word_translations",
        "word_tips_json": "word_tips",
    }
    key = mapping[db_column]
    if key not in candidate:
        raise ValueError(f"Report id {event.get('id')} is missing v2.{key}")
    return candidate[key]


def _validate(rows: list[dict[str, Any]], candidates: dict[int, dict[str, Any]]) -> None:
    row_ids = {int(row["id"]) for row in rows}
    candidate_ids = set(candidates)
    if row_ids != candidate_ids:
        missing = sorted(row_ids - candidate_ids)
        unexpected = sorted(candidate_ids - row_ids)
        raise ValueError(f"Report/database id mismatch; missing={missing[:20]}, unexpected={unexpected[:20]}")

    mismatches: list[dict[str, Any]] = []
    quality_failures: list[dict[str, Any]] = []
    for row in rows:
        identifier = int(row["id"])
        event = candidates[identifier]
        if str(event.get("text") or "") != str(row.get("text") or ""):
            mismatches.append({"id": identifier, "fields": ["text"]})
            continue
        changed_fields = [
            column
            for column in TRANSLATION_COLUMNS
            if _current_value(row, column) != _previous_value(event, column)
        ]
        if changed_fields:
            mismatches.append({"id": identifier, "fields": changed_fields})
            continue

        candidate = event["v2"]
        words = [str(item).strip() for item in event.get("words", []) if str(item).strip()]
        issues = translation_result_issues(
            {
                "sentence_translation": _candidate_value(event, "sentence_translation"),
                "sentence_segments": _candidate_value(event, "sentence_segments_json"),
                "translation_segments": _candidate_value(event, "translation_segments_json"),
                "word_translations": _candidate_value(event, "word_translations_json"),
                "word_tips": _candidate_value(event, "word_tips_json"),
            },
            words,
            source_text=_translation_source(str(row.get("text") or "")),
        )
        if issues:
            quality_failures.append({"id": identifier, "issues": issues[:8]})

    if mismatches:
        raise ValueError(f"Database changed after evaluation: {mismatches[:12]}")
    if quality_failures:
        raise ValueError(f"Candidate validation failures: {quality_failures[:12]}")


def _backup_database(backup_path: Path) -> None:
    if backup_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)


def _apply(rows: list[dict[str, Any]], candidates: dict[int, dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        begin_immediate(conn)
        locked_rows = _current_rows(conn)
        _validate(locked_rows, candidates)
        for row in locked_rows:
            event = candidates[int(row["id"])]
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
                    _candidate_value(event, "sentence_translation"),
                    _json_dumps(_candidate_value(event, "sentence_segments_json")),
                    _json_dumps(_candidate_value(event, "translation_segments_json")),
                    _json_dumps(_candidate_value(event, "word_translations_json")),
                    _json_dumps(_candidate_value(event, "word_tips_json")),
                    now,
                    int(row["id"]),
                ),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a validated V2 translation evaluation report.")
    parser.add_argument("--report", type=Path, required=True, help="Completed V2 JSONL evaluation report.")
    parser.add_argument("--apply", action="store_true", help="Actually update the database after validation.")
    parser.add_argument("--backup", type=Path, help="Required destination for a pre-apply SQLite backup.")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--backup is required with --apply")
    if not args.apply and args.backup:
        parser.error("--backup is only valid with --apply")

    candidates = _latest_candidates(args.report)
    read_uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(read_uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = _current_rows(connection)
    _validate(rows, candidates)
    print(json.dumps({"validated": len(rows), "database_written": False}, ensure_ascii=False), flush=True)
    if not args.apply:
        return

    _backup_database(args.backup)
    _apply(rows, candidates)
    print(
        json.dumps(
            {
                "updated": len(rows),
                "database_written": True,
                "backup_path": str(args.backup),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
