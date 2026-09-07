from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..platform.ai_transport import AIProviderError
from ..platform.db import begin_immediate, get_connection
from .translation_quality import validate_translation_result, word_translation_issues
from .translator import (
    MAX_REFERENCE_CONTEXT_ITEMS,
    extract_words,
    translate_text,
    translate_words,
    translation_configured,
)


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed if parsed is not None else fallback


def _json_dumps(value: Any, fallback: Any) -> str:
    if value is None:
        value = fallback
    return json.dumps(value, ensure_ascii=False)


def _context_from_connection(conn, sentence_id: int) -> tuple[list[str], list[str]]:
    before_rows = conn.execute(
        """
        SELECT text
        FROM english_sentences
        WHERE id < ? AND COALESCE(deleted_at, '') = ''
        ORDER BY id DESC
        LIMIT ?
        """,
        (sentence_id, MAX_REFERENCE_CONTEXT_ITEMS),
    ).fetchall()
    after_rows = conn.execute(
        """
        SELECT text
        FROM english_sentences
        WHERE id > ? AND COALESCE(deleted_at, '') = ''
        ORDER BY id
        LIMIT ?
        """,
        (sentence_id, MAX_REFERENCE_CONTEXT_ITEMS),
    ).fetchall()
    before = [str(row["text"] or "") for row in reversed(before_rows)]
    after = [str(row["text"] or "") for row in after_rows]
    return before, after


def translation_context_for_sentence(
    sentence_id: int,
    *,
    expected_text: str | None = None,
) -> tuple[list[str], list[str]]:
    """Load a bounded neighbouring window only for an unchanged stored source."""
    with get_connection() as conn:
        current = conn.execute(
            """
            SELECT text
            FROM english_sentences
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (sentence_id,),
        ).fetchone()
        if not current:
            return [], []
        if expected_text is not None and str(current["text"] or "") != str(expected_text):
            return [], []
        return _context_from_connection(conn, sentence_id)


def _load_sentence(sentence_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, text, word_translations_json, word_tips_json, sentence_translation
            FROM english_sentences
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (sentence_id,),
        ).fetchone()
        if not row:
            return None
        context_before, context_after = _context_from_connection(conn, sentence_id)
    result = dict(row)
    result["context_before"] = context_before
    result["context_after"] = context_after
    return result


def _selected_words(row: dict) -> list[str] | None:
    translations = _json_loads(row.get("word_translations_json"), {})
    if isinstance(translations, dict) and translations:
        return [str(word) for word in translations.keys() if str(word).strip()]
    focused = extract_words(str(row.get("text") or ""))
    return focused or []


def _needs_translation(row: dict) -> bool:
    if not str(row.get("sentence_translation") or "").strip():
        return True
    translations = _json_loads(row.get("word_translations_json"), {})
    return isinstance(translations, dict) and any(not str(value or "").strip() for value in translations.values())


def _missing_words(row: dict) -> list[str]:
    translations = _json_loads(row.get("word_translations_json"), {})
    if not isinstance(translations, dict):
        return []
    return [str(word) for word, value in translations.items() if str(word).strip() and not str(value or "").strip()]


def _merge_missing(
    existing: Any,
    generated: Any,
    allowed_words: list[str],
    *,
    include_empty: bool = False,
) -> dict[str, str]:
    base = _json_loads(existing, {})
    if not isinstance(base, dict):
        base = {}
    additions = generated if isinstance(generated, dict) else {}
    base_by_lower = {str(key).strip().casefold(): str(value or "").strip() for key, value in base.items()}
    additions_by_lower = {
        str(key).strip().casefold(): str(value or "").strip()
        for key, value in additions.items()
        if str(key).strip()
    }
    merged: dict[str, str] = {}
    for raw_word in allowed_words:
        word = str(raw_word or "").strip()
        if not word:
            continue
        key = word.casefold()
        text = base_by_lower.get(key) or additions_by_lower.get(key) or ""
        if include_empty or text:
            merged[word] = text
    return merged


def _apply_translation_if_still_missing(sentence_id: int, result: dict, *, expected_text: str) -> bool:
    with get_connection() as conn:
        begin_immediate(conn)
        current = conn.execute(
            """
            SELECT text, word_translations_json, word_tips_json, sentence_translation
            FROM english_sentences
            WHERE id = ? AND COALESCE(deleted_at, '') = ''
            """,
            (sentence_id,),
        ).fetchone()
        if not current:
            return False
        current_data = dict(current)
        if str(current_data.get("text") or "") != expected_text:
            return False
        allowed_words = _selected_words(current_data)
        word_translations = _merge_missing(
            current_data.get("word_translations_json"),
            result.get("word_translations"),
            allowed_words,
            include_empty=True,
        )
        word_tips = _merge_missing(
            current_data.get("word_tips_json"),
            result.get("word_tips"),
            allowed_words,
        )
        cur = conn.execute(
            """
            UPDATE english_sentences
            SET sentence_translation = CASE WHEN COALESCE(sentence_translation, '') = '' THEN ? ELSE sentence_translation END,
                sentence_segments_json = CASE WHEN COALESCE(sentence_translation, '') = '' THEN ? ELSE sentence_segments_json END,
                translation_segments_json = CASE WHEN COALESCE(sentence_translation, '') = '' THEN ? ELSE translation_segments_json END,
                word_translations_json = ?,
                word_tips_json = ?,
                updated_at = ?
            WHERE id = ?
              AND COALESCE(deleted_at, '') = ''
              AND text = ?
            """,
            (
                str(result.get("sentence_translation") or "").strip(),
                _json_dumps(result.get("sentence_segments") or [], []),
                _json_dumps(result.get("translation_segments") or [], []),
                _json_dumps(word_translations, {}),
                _json_dumps(word_tips, {}),
                _now(),
                sentence_id,
                expected_text,
            ),
        )
        return bool(getattr(cur, "rowcount", 0) or conn.total_changes)


def translate_sentence_if_missing_best_effort(sentence_id: int, expected_text: str | None = None) -> None:
    if not translation_configured():
        return
    row = _load_sentence(sentence_id)
    if not row:
        return
    if expected_text is not None and str(row.get("text") or "") != expected_text:
        return
    if not _needs_translation(row):
        return
    try:
        text = str(row.get("text") or "")
        words = _selected_words(row)
        missing_words = _missing_words(row)
        context_before = row.get("context_before") or []
        context_after = row.get("context_after") or []
        if not str(row.get("sentence_translation") or "").strip():
            result = translate_text(
                text,
                words=words,
                context_before=context_before,
                context_after=context_after,
            )
            ok, reason = validate_translation_result(result, words or [], source_text=text)
            if ok:
                _apply_translation_if_still_missing(sentence_id, result, expected_text=text)
                return
            logger.warning("english auto translation rejected invalid result for sentence %s: %s", sentence_id, reason)
        elif missing_words:
            result = translate_words(
                text,
                words=missing_words,
                sentence_translation=str(row.get("sentence_translation") or ""),
                context_before=context_before,
                context_after=context_after,
            )
            issues = word_translation_issues(result, missing_words)
            if not issues:
                _apply_translation_if_still_missing(sentence_id, result, expected_text=text)
                return
            logger.warning("english auto word translation rejected invalid result for sentence %s: %s", sentence_id, issues[0])
    except AIProviderError as exc:
        logger.warning("english auto translation failed for sentence %s: %s", sentence_id, exc.diagnostic)
    except Exception:
        logger.exception("english auto translation crashed for sentence %s", sentence_id)


def translate_sentences_if_missing_best_effort(
    sentence_ids: list[int],
    expected_texts: dict[int, str] | None = None,
) -> None:
    seen: set[int] = set()
    for value in sentence_ids:
        try:
            sentence_id = int(value)
        except (TypeError, ValueError):
            continue
        if sentence_id <= 0 or sentence_id in seen:
            continue
        seen.add(sentence_id)
        expected_text = expected_texts.get(sentence_id) if expected_texts else None
        translate_sentence_if_missing_best_effort(sentence_id, expected_text=expected_text)


def resume_pending_translation_generation_best_effort() -> None:
    """Retry sentences whose translations were interrupted before completion.

    Translation work remains deliberately lightweight and non-persistent: the
    sentence fields themselves are the source of truth.  On startup, scan the
    active sentence rows and retry only those that still need a translation.
    """
    if not translation_configured():
        return
    try:
        with get_connection() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, text, word_translations_json, sentence_translation
                    FROM english_sentences
                    WHERE COALESCE(deleted_at, '') = ''
                    ORDER BY id
                    """
                ).fetchall()
            ]
        pending = [row for row in rows if _needs_translation(row)]
        if not pending:
            return
        sentence_ids = [int(row["id"]) for row in pending]
        expected_texts = {int(row["id"]): str(row.get("text") or "") for row in pending}
        logger.info("resuming English translation for %s pending sentences", len(sentence_ids))
        translate_sentences_if_missing_best_effort(sentence_ids, expected_texts)
    except Exception:  # noqa: BLE001 - startup recovery must not stop the API.
        logger.exception("English translation startup recovery failed")
