from __future__ import annotations

"""Append missing English definitions without replacing saved Chinese or study progress."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.english.translation_generation import _context_from_connection
from app.english.translation_transport import translation_completion
from app.english.translator import _chat_completion, _english_ai_options, _extract_json_object, _translation_source
from app.platform.ai_transport import AIProviderError
from app.platform.db import begin_immediate, get_connection


SEPARATOR = "；英文："
SNAPSHOT_FIELDS = ("text", "sentence_translation", "word_translations_json")
CONTRACT = """You edit vocabulary cards for Chinese learners of English.
Each input sentence is independent. Explain only its requested words in their actual context.
The saved Chinese is read-only reference: do not translate the sentence or rewrite Chinese.
For each word, write an english_definition in 3-24 simple English words, in one line.
Use the correct part of speech and voice: an adjective needs an adjective explanation,
a verb needs a verb explanation, and a passive participle needs a passive explanation.
Explain the word itself, not its neighbours' quantity, negation, modifier or object.
For a fixed expression, explicitly identify the use within the expression when necessary.
Do not add unsupported conditions: bilingual need not mean equally fluent; corporate need
not mean a large company; sneak need not mean without permission; majority is not vast majority.
Feasibility means whether something is possible or practical, not necessarily easy.
No Chinese, example sentences, circular definitions, lists of unrelated senses or repeated labels.
Use the English source to disambiguate; adjacent sentences are reference, not extra targets.
For source_quote, copy the requested word itself exactly as it appears in the target English.
Do not include extra surrounding phrases or quote marks. If a stored word key includes sentence
punctuation, the quote may omit that punctuation, but the word key must remain unchanged.
Keep every id and word exactly as supplied. Never omit, add, rename or merge words.
Return JSON only, with this structure:
{"sentences":[{"id":123,"words":[{"word":"affected","source_quote":"can be affected",
"english_definition":"influenced or changed by something"}]}]}"""
REVIEW_CONTRACT = """Independently check these English vocabulary definitions against each target
English sentence and the saved Chinese reference. Check every word for meaning, part of speech,
voice, modifier scope, unnecessary restrictions, circular explanations and learner clarity.
Preserve correct definitions. Correct only identifiable problems, using 3-24 simple English words.
Do not rewrite Chinese. Do not add source words' neighbours' meanings or facts from other sentences.
Return JSON only: {"corrections":[{"id":123,"word":"word as supplied",
"english_definition":"the corrected explanation","reason":"specific reason"}]}.
If all definitions are suitable, return {"corrections":[]}.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _english(value: Any) -> str:
    return str(value or "").partition(SEPARATOR)[2].strip()


def _redact(value: str) -> str:
    secret = os.getenv("STUDY_ENGLISH_AI_API_KEY", "")
    return value.replace(secret, "[REDACTED]") if secret else value


def _write(path: Path, value: Any) -> None:
    path.write_text(_redact(json.dumps(value, ensure_ascii=False, indent=2)) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _append(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_redact(json.dumps(value, ensure_ascii=False)) + "\n")
    path.chmod(0o600)


def _load_rows(ids: set[int] | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT id, text, sentence_translation, word_translations_json "
            "FROM english_sentences WHERE COALESCE(deleted_at, '') = '' ORDER BY id"
        )]
        pending = []
        for row in rows:
            if ids is not None and int(row["id"]) not in ids:
                continue
            meanings = json.loads(row["word_translations_json"] or "{}")
            missing = {word: value for word, value in meanings.items() if not _english(value)}
            if not missing:
                continue
            if any(not str(value or "").strip() for value in missing.values()):
                raise ValueError(f"Sentence {row['id']} needs Chinese meanings before English-only backfill")
            before, after = _context_from_connection(conn, int(row["id"]))
            pending.append({**row, "words": missing, "context_before": before, "context_after": after})
    return pending


def _input(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"], "text": _translation_source(row["text"]),
        "saved_chinese_translation": row["sentence_translation"],
        "requested_words_with_saved_chinese": row["words"],
        "context_before": [_translation_source(text) for text in row["context_before"]],
        "context_after": [_translation_source(text) for text in row["context_after"]],
    }


def _validate_definition(word: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Non-string English definition: {word}")
    definition = value.strip()
    count = len(re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", definition))
    if not 3 <= count <= 24 or re.search(r"[\u4e00-\u9fff\r\n]", definition):
        raise ValueError(f"Invalid English definition for {word}: got {count} words; use 3-24 English words on one line")
    if definition.strip(".!?").casefold() == word.casefold():
        raise ValueError(f"Circular English definition: {word}")
    return definition


def _validate_batch(rows: list[dict[str, Any]], payload: dict[str, Any]) -> dict[int, list[dict[str, str]]]:
    entries = payload.get("sentences")
    expected = {int(row["id"]): row for row in rows}
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise ValueError("Generated sentence count differs from input")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or type(entry.get("id")) is not int:
            raise ValueError("Invalid generated sentence identity")
        identifier = entry["id"]
        if identifier not in expected or identifier in result:
            raise ValueError("Unknown or duplicate generated sentence")
        row = expected[identifier]
        cards = entry.get("words")
        if not isinstance(cards, list) or len(cards) != len(row["words"]):
            raise ValueError(f"Generated focus count differs: {identifier}")
        seen = set()
        source = _translation_source(row["text"])
        validated = []
        for card in cards:
            word = card.get("word") if isinstance(card, dict) else None
            if word not in row["words"] or word in seen:
                raise ValueError(f"Unknown or duplicate focus word: {identifier}")
            seen.add(word)
            quote = card.get("source_quote")
            if not isinstance(quote, str) or not quote or quote not in source:
                raise ValueError(f"Invalid source quote: {identifier}:{word}")
            lexical_word = word.strip(" \t\r\n.,!?;:\"'“”‘’()[]")
            if not lexical_word or not re.search(r"(?<![A-Za-z])" + re.escape(lexical_word) + r"(?![A-Za-z])", quote, re.I):
                raise ValueError(f"Source quote lacks focus word: {identifier}:{word}")
            validated.append({"word": word, "source_quote": quote,
                              "english_definition": _validate_definition(word, card.get("english_definition"))})
        result[identifier] = validated
    return result


def _completion(system: str, content: Any) -> dict[str, Any]:
    raw = translation_completion(
        [{"role": "system", "content": system},
         {"role": "user", "content": json.dumps(content, ensure_ascii=False)}],
        options=_english_ai_options(), completion=_chat_completion,
    )
    return _extract_json_object(raw, diagnostic_label="English definition backfill")


def _generate_batch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.monotonic()
    feedback = ""
    for attempt in range(3):
        try:
            raw = _completion(CONTRACT, {"sentences": [_input(row) for row in rows], "validation_feedback": feedback})
            cards = _validate_batch(rows, raw)
            review = _completion(REVIEW_CONTRACT, {
                "sentences": [{**_input(row), "candidate_definitions": cards[row["id"]]} for row in rows],
                "validation_feedback": feedback,
            })
            corrections = review.get("corrections")
            if not isinstance(corrections, list):
                raise ValueError("Missing structured definition review")
            seen = set()
            for correction in corrections:
                if not isinstance(correction, dict):
                    raise ValueError("Invalid review correction")
                key = (correction.get("id"), correction.get("word"))
                if key in seen or type(key[0]) is not int or key[0] not in cards:
                    raise ValueError("Unknown or duplicate review correction")
                matches = [card for card in cards[key[0]] if card["word"] == key[1]]
                if len(matches) != 1:
                    raise ValueError("Review changed the selected word")
                matches[0]["english_definition"] = _validate_definition(key[1], correction.get("english_definition"))
                seen.add(key)
            return {"cards": cards, "review_corrections": corrections, "attempts": attempt + 1,
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
        except ValueError as exc:
            feedback = str(exc)
            if attempt == 2:
                raise
        except AIProviderError as exc:
            if "English definition backfill parse failed:" not in exc.diagnostic or attempt == 2:
                raise
            feedback = "Return a valid JSON object with all requested ids and word keys, without prose or Markdown."
    raise AssertionError("No definition batch result")


def _apply_row(row: dict[str, Any], cards: list[dict[str, str]]) -> bool:
    """Compare the saved source/meanings before appending; never overwrite concurrent edits."""
    meanings = json.loads(row["word_translations_json"] or "{}")
    if {card["word"] for card in cards} != set(row["words"]) or len(cards) != len(row["words"]):
        raise ValueError("Refusing a mismatched set of English definitions")
    for card in cards:
        word = card["word"]
        definition = _validate_definition(word, card["english_definition"])
        old = str(meanings[word])
        if _english(old):
            raise ValueError("Refusing to replace an existing English definition")
        meanings[word] = old.partition(SEPARATOR)[0] + SEPARATOR + definition
    with get_connection() as conn:
        begin_immediate(conn)
        current = conn.execute(
            "SELECT text, sentence_translation, word_translations_json "
            "FROM english_sentences WHERE id = ? AND COALESCE(deleted_at, '') = ''", (row["id"],)
        ).fetchone()
        if not current or any(current[field] != row[field] for field in SNAPSHOT_FIELDS):
            return False
        conn.execute(
            "UPDATE english_sentences SET word_translations_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(meanings, ensure_ascii=False), _now(), row["id"]),
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ids", type=int, nargs="*")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--generate", action="store_true", help="Generate and review candidates without database writes")
    parser.add_argument("--apply", action="store_true", help="Generate, review and append missing English definitions")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 12 or not 1 <= args.workers <= 3:
        parser.error("batch-size must be 1-12 and workers must be 1-3")
    selected = set(args.ids) if args.ids is not None else None
    rows = _load_rows(selected)
    plan = {"sentences": len(rows), "words": sum(len(row["words"]) for row in rows),
            "apply": args.apply, "selected_ids": [row["id"] for row in rows]}
    if not args.generate and not args.apply:
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot = args.output_dir / "backfill-source.json"
    if not snapshot.exists():
        _write(snapshot, rows)
    options = _english_ai_options()
    manifest = {**plan, "started_at": _now(), "model": options["model"],
                "provider_base_url": options["base_url"], "workers": args.workers,
                "batch_size": args.batch_size, "requests_per_minute": os.getenv("STUDY_ENGLISH_AI_REQUESTS_PER_MINUTE", ""),
                "prompt_sha256": hashlib.sha256((CONTRACT + REVIEW_CONTRACT).encode()).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "source_sha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    _append(args.output_dir / "runs.jsonl", manifest)
    print(json.dumps({"event": "start", **{key: value for key, value in manifest.items() if key != "selected_ids"}}), flush=True)
    batches = [rows[index:index + args.batch_size] for index in range(0, len(rows), args.batch_size)]
    completed = applied = word_count = 0
    failures = []
    conflicts = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_generate_batch, batch): batch for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            try:
                generated = future.result()
                # Persist the exact candidates and model review before any database write.
                _append(args.output_dir / "candidates.jsonl", {
                    "completed_at": _now(), "rows": batch, **generated,
                })
                for row in batch:
                    completed += 1
                    if args.apply:
                        if _apply_row(row, generated["cards"][row["id"]]):
                            applied += 1
                            word_count += len(row["words"])
                        else:
                            conflicts.append(row["id"])
                print(json.dumps({"event": "progress", "completed_sentences": completed,
                                  "applied_sentences": applied, "appended_words": word_count,
                                  "last_ids": [row["id"] for row in batch],
                                  "review_corrections": len(generated["review_corrections"])}), flush=True)
            except Exception as exc:
                failed_ids = [row["id"] for row in batch]
                failures.extend(failed_ids)
                error = {"event": "batch_failed", "ids": failed_ids, "error_type": type(exc).__name__,
                         "error": _redact(str(exc)), "at": _now()}
                _append(args.output_dir / "errors.jsonl", error)
                print(json.dumps(error, ensure_ascii=False), flush=True)
    remaining = _load_rows(selected) if args.apply else rows
    summary = {"completed_at": _now(), "generated_sentences": completed, "applied_sentences": applied,
               "appended_words": word_count, "failed_ids": failures, "concurrent_edit_ids": conflicts,
               "remaining_sentences": len(remaining), "remaining_words": sum(len(row["words"]) for row in remaining),
               "model": options["model"], "database_written": args.apply and applied > 0}
    _write(args.output_dir / "summary.json", summary)
    print(json.dumps({"event": "complete", **summary}), flush=True)
    return 1 if failures or conflicts or (args.apply and remaining) else 0


if __name__ == "__main__":
    raise SystemExit(main())
