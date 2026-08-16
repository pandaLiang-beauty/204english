from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.platform.db import get_connection, initialize_database  # noqa: E402
from app.english import repository  # noqa: E402
from app.english.schema import initialize_schema  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value, fallback):
    try:
        parsed = json.loads(str(value or ""))
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _merge_counts(translations: dict, rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        source = repository._normalize_dict(row.get("word_play_counts_json"))
        for raw_key, value in source.items():
            normalized = repository._normalize_focus_word(raw_key)
            target = repository._find_map_key_by_normalized(translations, normalized)
            if not target:
                target = repository._related_focus_key(translations, str(raw_key))
            if target:
                counts[target] = counts.get(target, 0) + repository._safe_int(value)
    return counts


def _replace_passage_references(conn, *, canonical_id: int, duplicate_ids: set[int]) -> None:
    rows = conn.execute("SELECT id, selected_sentence_ids_json FROM english_passages").fetchall()
    for row in rows:
        values = _json(row["selected_sentence_ids_json"], [])
        updated = []
        changed = False
        for value in values:
            try:
                sentence_id = int(value)
            except (TypeError, ValueError):
                continue
            if sentence_id in duplicate_ids:
                sentence_id = canonical_id
                changed = True
            if sentence_id not in updated:
                updated.append(sentence_id)
        if changed:
            conn.execute(
                "UPDATE english_passages SET selected_sentence_ids_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(updated, ensure_ascii=False), _now(), int(row["id"])),
            )


def _merge_round_items(conn, *, canonical_id: int, duplicate_id: int) -> None:
    items = conn.execute(
        "SELECT * FROM english_review_round_items WHERE sentence_id = ?",
        (duplicate_id,),
    ).fetchall()
    for item in items:
        existing = conn.execute(
            "SELECT * FROM english_review_round_items WHERE round_id = ? AND sentence_id = ?",
            (int(item["round_id"]), canonical_id),
        ).fetchone()
        if existing:
            completed_at = max(str(existing["completed_at"] or ""), str(item["completed_at"] or ""))
            conn.execute(
                "UPDATE english_review_round_items SET completed_at = ?, updated_at = ? WHERE id = ?",
                (completed_at, _now(), int(existing["id"])),
            )
            conn.execute("DELETE FROM english_review_round_items WHERE id = ?", (int(item["id"]),))
        else:
            conn.execute(
                "UPDATE english_review_round_items SET sentence_id = ?, updated_at = ? WHERE id = ?",
                (canonical_id, _now(), int(item["id"])),
            )


def _merge_duplicate_group(conn, rows: list[dict]) -> int:
    rows.sort(key=lambda row: int(row["id"]))
    canonical = rows[0]
    duplicates = rows[1:]
    translations = {}
    tips = {}
    for row in rows:
        translations = repository._merge_focus_maps(
            translations,
            repository._normalize_dict(row.get("word_translations_json")),
        )
        tips = repository._merge_focus_maps(tips, repository._normalize_dict(row.get("word_tips_json")))
    counts = _merge_counts(translations, rows)
    merged_marks = []
    for row in rows:
        merged_marks.extend({"word": word} for word in repository._marked_word_surfaces(row["text"]))
    text, translations, tips, counts = repository._coherent_focus_state(
        repository._mark_focus_words(canonical["text"], merged_marks),
        translations,
        tips,
        counts,
    )
    best_translation = next((str(row.get("sentence_translation") or "") for row in rows if str(row.get("sentence_translation") or "").strip()), "")
    audio_row = next((row for row in rows if str(row.get("audio_path") or "").strip()), canonical)
    now = _now()
    conn.execute(
        """
        UPDATE english_sentences
        SET text = ?, word_translations_json = ?, word_tips_json = ?,
            word_play_counts_json = ?, word_play_total = ?, review_count = ?,
            sentence_translation = ?, audio_path = ?, audio_provider = ?, audio_voice = ?,
            audio_hash = ?, audio_status = ?, audio_error = ?, audio_generated_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            text,
            json.dumps(translations, ensure_ascii=False),
            json.dumps(tips, ensure_ascii=False),
            json.dumps(counts, ensure_ascii=False),
            repository._calculate_word_total(counts),
            sum(int(row.get("review_count") or 0) for row in rows),
            best_translation,
            audio_row.get("audio_path") or "",
            audio_row.get("audio_provider") or "",
            audio_row.get("audio_voice") or "",
            audio_row.get("audio_hash") or "",
            audio_row.get("audio_status") or "missing",
            audio_row.get("audio_error") or "",
            audio_row.get("audio_generated_at") or "",
            now,
            int(canonical["id"]),
        ),
    )

    canonical_id = int(canonical["id"])
    duplicate_ids = {int(row["id"]) for row in duplicates}
    _replace_passage_references(conn, canonical_id=canonical_id, duplicate_ids=duplicate_ids)
    for duplicate_id in duplicate_ids:
        conn.execute(
            "UPDATE english_review_events SET sentence_id = ? WHERE sentence_id = ?",
            (canonical_id, duplicate_id),
        )
        _merge_round_items(conn, canonical_id=canonical_id, duplicate_id=duplicate_id)
        conn.execute(
            "UPDATE english_sentences SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, duplicate_id),
        )
    return len(duplicate_ids)


def audit() -> tuple[list[list[dict]], int]:
    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = '' ORDER BY id"
        ).fetchall()]
    groups: dict[str, list[dict]] = defaultdict(list)
    focus_changes = 0
    for row in rows:
        groups[repository.sentence_identity_key(row["text"])].append(row)
        coherent = repository._coherent_focus_state(
            row["text"],
            repository._normalize_dict(row.get("word_translations_json")),
            repository._normalize_dict(row.get("word_tips_json")),
            repository._normalize_dict(row.get("word_play_counts_json")),
        )
        current = (
            row["text"],
            repository._normalize_dict(row.get("word_translations_json")),
            repository._normalize_dict(row.get("word_tips_json")),
            repository._normalize_dict(row.get("word_play_counts_json")),
        )
        if coherent != current:
            focus_changes += 1
    return [group for key, group in groups.items() if key and len(group) > 1], focus_changes


def apply_repairs() -> dict:
    duplicate_groups, _ = audit()
    merged = 0
    focus_updated = 0
    with get_connection() as conn:
        for group in duplicate_groups:
            merged += _merge_duplicate_group(conn, group)
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = '' ORDER BY id"
        ).fetchall()]
        for row in rows:
            text, translations, tips, counts = repository._coherent_focus_state(
                row["text"],
                repository._normalize_dict(row.get("word_translations_json")),
                repository._normalize_dict(row.get("word_tips_json")),
                repository._normalize_dict(row.get("word_play_counts_json")),
            )
            current = (
                row["text"],
                repository._normalize_dict(row.get("word_translations_json")),
                repository._normalize_dict(row.get("word_tips_json")),
                repository._normalize_dict(row.get("word_play_counts_json")),
            )
            if (text, translations, tips, counts) == current:
                continue
            conn.execute(
                """
                UPDATE english_sentences
                SET text = ?, word_translations_json = ?, word_tips_json = ?,
                    word_play_counts_json = ?, word_play_total = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    text,
                    json.dumps(translations, ensure_ascii=False),
                    json.dumps(tips, ensure_ascii=False),
                    json.dumps(counts, ensure_ascii=False),
                    repository._calculate_word_total(counts),
                    _now(),
                    int(row["id"]),
                ),
            )
            focus_updated += 1
    return {"duplicates_merged": merged, "focus_rows_updated": focus_updated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and repair English sentence identity/focus-word data.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    initialize_database()
    initialize_schema()
    duplicate_groups, focus_changes = audit()
    report = {
        "duplicate_groups": [[int(row["id"]) for row in group] for group in duplicate_groups],
        "focus_rows_needing_update": focus_changes,
    }
    if args.apply:
        report.update(apply_repairs())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
