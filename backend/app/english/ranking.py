from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any


SMART_REVIEW_SETTINGS = {
    "algorithm_peak_mode": "corpus-average",
    "algorithm_sentence_peak": 6.0,
    "algorithm_peak_min": 3.0,
    "algorithm_peak_multiplier": 1.0,
    "algorithm_sentence_spread": 2.0,
    "algorithm_sentence_weight": 1.0,
    "algorithm_word_weight": 0.2,
    "algorithm_word_repeat_decay": 0.35,
    "algorithm_sentence_review_word_signal": 0.25,
    "algorithm_word_network_weight": 0.16,
    "algorithm_context_diversity_weight": 0.06,
    "algorithm_word_mastery_penalty": 0.08,
    "algorithm_word_node_peak_min": 1.5,
    "algorithm_word_node_spread": 1.5,
    "algorithm_unseen_boost": 0.08,
    "algorithm_same_word_penalty": 0.12,
    "algorithm_fatigue_recent": 6,
    "algorithm_fatigue_lookahead": 80,
}
_MARKDOWN_WORD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")
_WORD_TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")


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


def _normalize_dict(value: Any) -> dict:
    parsed = _json_loads(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _word_play_signal(count: int, repeat_decay: float) -> float:
    if count <= 0:
        return 0.0
    if repeat_decay <= 0:
        return 1.0
    return (1.0 - repeat_decay**count) / (1.0 - repeat_decay)


def _sentence_word_signal(row: dict, settings: dict) -> float:
    counts = _normalize_dict(row.get("word_play_counts_json"))
    repeat_decay = float(settings["algorithm_word_repeat_decay"])
    return sum(_word_play_signal(_safe_int(value), repeat_decay) for value in counts.values())


def _sentence_exposure(row: dict, settings: dict) -> tuple[float, float]:
    word_signal = _sentence_word_signal(row, settings)
    exposure = (
        _safe_int(row.get("review_count")) * float(settings["algorithm_sentence_weight"])
        + word_signal * float(settings["algorithm_word_weight"])
    )
    return exposure, word_signal


def _resolve_sentence_peak(rows: list[dict], settings: dict) -> tuple[float, dict]:
    fixed_peak = float(settings["algorithm_sentence_peak"])
    if settings.get("algorithm_peak_mode") != "corpus-average" or not rows:
        return fixed_peak, {"mode": "fixed", "corpus_count": len(rows), "corpus_average_exposure": None}

    exposures = [_sentence_exposure(row, settings)[0] for row in rows]
    average_exposure = sum(exposures) / max(len(exposures), 1)
    dynamic_peak = max(float(settings["algorithm_peak_min"]), average_exposure * float(settings["algorithm_peak_multiplier"]))
    return dynamic_peak, {
        "mode": "corpus-average",
        "corpus_count": len(rows),
        "corpus_average_exposure": round(average_exposure, 3),
    }


def _sigmoid(value: float) -> float:
    if value >= 35:
        return 1.0
    if value <= -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _normalize_focus_word(value: str) -> str:
    return re.sub(r"^\W+|\W+$", "", str(value or "").strip().lower())


def _word_key_candidates(normalized_word: str) -> list[str]:
    word = _normalize_focus_word(normalized_word)
    if not word:
        return []
    candidates = [word]
    if len(word) > 4 and word.endswith("ies"):
        candidates.append(f"{word[:-3]}y")
    if len(word) > 4 and word.endswith(("ches", "shes", "xes", "zes", "ses")):
        candidates.append(word[:-2])
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        candidates.append(word[:-1])
    if len(word) > 5 and word.endswith("ied"):
        candidates.append(f"{word[:-3]}y")
    if len(word) > 5 and word.endswith("ed"):
        stem = word[:-2]
        candidates.extend([stem, f"{stem}e"])
    if len(word) > 6 and word.endswith("ing"):
        stem = word[:-3]
        candidates.append(stem)
        if len(stem) > 2 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            candidates.append(stem[:-1])
        elif stem.endswith("mak"):
            candidates.append("make")
    result = []
    for candidate in candidates:
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def _build_word_canonical_map(rows: list[dict]) -> dict[str, str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for word in _raw_focus_words(row):
            normalized = _normalize_focus_word(word)
            if normalized:
                counts[normalized] += 1
    canonical: dict[str, str] = {}
    for word in counts:
        present = [candidate for candidate in _word_key_candidates(word) if counts.get(candidate, 0) > 0]
        if not present:
            canonical[word] = word
            continue
        canonical[word] = max(present, key=lambda candidate: (counts[candidate], -len(candidate), candidate == word))
    return canonical


def _canonical_word_key(word: str, canonical_map: dict[str, str] | None = None) -> str:
    normalized = _normalize_focus_word(word)
    if not normalized:
        return ""
    if canonical_map and normalized in canonical_map:
        return canonical_map[normalized]
    return normalized


def _raw_focus_words(row: dict) -> list[str]:
    words: list[str] = []
    translations = _normalize_dict(row.get("word_translations_json"))
    for word in translations.keys():
        cleaned = str(word or "").strip()
        if cleaned:
            words.append(cleaned)
    for match in _MARKDOWN_WORD_PATTERN.findall(str(row.get("text") or "")):
        cleaned = str(match or "").strip()
        if cleaned:
            words.append(cleaned)
    return words


def _context_label(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return text[:120]


def _sentence_focus_entries(row: dict, canonical_map: dict[str, str] | None = None) -> list[dict]:
    translations = _normalize_dict(row.get("word_translations_json"))
    counts = _normalize_dict(row.get("word_play_counts_json"))
    by_key: dict[str, dict] = {}
    for word, meaning in translations.items():
        surface = str(word or "").strip()
        key = _canonical_word_key(surface, canonical_map)
        if not key:
            continue
        by_key.setdefault(
            key,
            {"key": key, "surfaces": set(), "translation": str(meaning or ""), "play_count": 0},
        )
        by_key[key]["surfaces"].add(surface)
        if meaning and not by_key[key]["translation"]:
            by_key[key]["translation"] = str(meaning)

    for word in _MARKDOWN_WORD_PATTERN.findall(str(row.get("text") or "")):
        surface = str(word or "").strip()
        key = _canonical_word_key(surface, canonical_map)
        if not key:
            continue
        by_key.setdefault(key, {"key": key, "surfaces": set(), "translation": "", "play_count": 0})
        by_key[key]["surfaces"].add(surface)

    for word, count in counts.items():
        key = _canonical_word_key(str(word or ""), canonical_map)
        if key and key in by_key:
            by_key[key]["play_count"] += _safe_int(count)

    entries = []
    for entry in by_key.values():
        entries.append(
            {
                "key": entry["key"],
                "surfaces": sorted(surface for surface in entry["surfaces"] if surface),
                "translation": entry["translation"],
                "play_count": _safe_int(entry["play_count"]),
            }
        )
    return entries


def _extract_focus_words(row: dict, canonical_map: dict[str, str] | None = None) -> set[str]:
    return {entry["key"] for entry in _sentence_focus_entries(row, canonical_map)}


def _rank_percentiles(values: dict[int | str, float], *, include_zero: bool) -> dict[int | str, float]:
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], str(item[0])))
    denominator = max(len(ordered) - 1, 1) if include_zero else len(ordered)
    output: dict[int | str, float] = {}
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_index = (index + end) / 2
        percentile = average_index / denominator if include_zero else (average_index + 1) / denominator
        for tied_index in range(index, end + 1):
            output[ordered[tied_index][0]] = min(1.0, max(0.0, percentile))
        index = end + 1
    return output


def _focus_occurrences_by_sentence(
    rows: list[dict],
    canonical_map: dict[str, str],
) -> tuple[dict[int, Counter[str]], Counter[str]]:
    surface_to_key: dict[str, str] = {}
    phrase_patterns: dict[str, re.Pattern] = {}
    for row in rows:
        for entry in _sentence_focus_entries(row, canonical_map):
            key = str(entry["key"])
            for surface in [key, *entry.get("surfaces", [])]:
                normalized = _normalize_focus_word(surface)
                if not normalized:
                    continue
                surface_to_key[normalized] = key
                if " " in normalized:
                    phrase_patterns.setdefault(
                        key,
                        re.compile(rf"(?<![A-Za-z0-9']){re.escape(normalized)}(?![A-Za-z0-9'])", re.IGNORECASE),
                    )

    by_sentence: dict[int, Counter[str]] = {}
    totals: Counter[str] = Counter()
    for row in rows:
        sentence_id = int(row["id"])
        plain_text = str(row.get("text") or "").replace("**", "")
        counts: Counter[str] = Counter()
        for token in _WORD_TOKEN_PATTERN.findall(plain_text):
            normalized = _normalize_focus_word(token)
            key = surface_to_key.get(normalized)
            if not key:
                for candidate in _word_key_candidates(normalized):
                    key = surface_to_key.get(candidate)
                    if key:
                        break
            if key:
                counts[key] += 1
        for key, pattern in phrase_patterns.items():
            counts[key] += len(pattern.findall(plain_text))
        by_sentence[sentence_id] = counts
        totals.update(counts)
    return by_sentence, totals


def sentence_exposure_metrics(rows: list[dict]) -> dict[int, dict]:
    """Return the frozen-cycle exposure inputs agreed for review scheduling."""
    if not rows:
        return {}
    canonical_map = _build_word_canonical_map(rows)
    occurrences, occurrence_totals = _focus_occurrences_by_sentence(rows, canonical_map)
    word_plays: Counter[str] = Counter()
    for row in rows:
        for entry in _sentence_focus_entries(row, canonical_map):
            word_plays[str(entry["key"])] += _safe_int(entry.get("play_count"))

    word_weights = _rank_percentiles(dict(occurrence_totals), include_zero=False)
    exposures: dict[int, float] = {}
    details: dict[int, dict] = {}
    for row in rows:
        sentence_id = int(row["id"])
        sentence_plays = _safe_int(row.get("review_count"))
        word_exposure = sum(
            word_plays[word] * float(word_weights.get(word, 0.0)) * count
            for word, count in occurrences.get(sentence_id, {}).items()
        )
        exposure = float(sentence_plays) + word_exposure
        exposures[sentence_id] = exposure
        details[sentence_id] = {
            "exposure": exposure,
            "sentence_plays": sentence_plays,
            "word_exposure": word_exposure,
        }

    sentence_percentiles = _rank_percentiles(exposures, include_zero=True)
    for sentence_id, detail in details.items():
        percentile = float(sentence_percentiles.get(sentence_id, 0.5))
        wave = math.sin(2 * math.pi * percentile) ** 2
        repeat_count = 1 + int(math.floor(wave + 0.5))
        detail["percentile"] = percentile
        detail["repeat_count"] = min(2, max(1, repeat_count))
    return details


def build_review_schedule(ranked_items: list[tuple[dict, dict]]) -> list[dict]:
    """Expand the smart order into one or two passes across seven slots."""
    if not ranked_items:
        return []
    rows = [row for row, _ in ranked_items]
    exposure_by_id = sentence_exposure_metrics(rows)
    prioritized = sorted(
        enumerate(ranked_items),
        key=lambda item: (
            not (
                _safe_int(item[1][0].get("review_count")) == 0
                and not any(_safe_int(value) for value in _normalize_dict(item[1][0].get("word_play_counts_json")).values())
                and _safe_int(item[1][0].get("completion_count")) == 0
            ),
            item[0],
        ),
    )
    base_items = [item for _, item in prioritized]
    slots_by_id: dict[int, list[int]] = {}
    for row, _ in base_items:
        sentence_id = int(row["id"])
        repeat_total = int(exposure_by_id[sentence_id]["repeat_count"])
        slots_by_id[sentence_id] = (
            [0]
            if repeat_total == 1
            else [round(index * 6 / (repeat_total - 1)) for index in range(repeat_total)]
        )

    schedule: list[dict] = []
    for slot in range(7):
        for row, _ in base_items:
            sentence_id = int(row["id"])
            slots = slots_by_id[sentence_id]
            if slot not in slots:
                continue
            detail = exposure_by_id[sentence_id]
            schedule.append(
                {
                    "sentence_id": sentence_id,
                    "repeat_index": slots.index(slot) + 1,
                    "repeat_total": len(slots),
                    "exposure_score": float(detail["exposure"]),
                    "exposure_percentile": float(detail["percentile"]),
                }
            )
    return schedule


def _build_word_network(rows: list[dict], settings: dict) -> dict:
    canonical_map = _build_word_canonical_map(rows)
    nodes: dict[str, dict] = {}
    sentence_entries: dict[int, list[dict]] = {}
    repeat_decay = float(settings["algorithm_word_repeat_decay"])
    sentence_word_signal = float(settings["algorithm_sentence_review_word_signal"])

    for row in rows:
        sentence_id = int(row["id"])
        sentence_reviews = _safe_int(row.get("review_count"))
        entries = _sentence_focus_entries(row, canonical_map)
        sentence_entries[sentence_id] = entries
        for entry in entries:
            edge_signal = _word_play_signal(entry["play_count"], repeat_decay) + sentence_reviews * sentence_word_signal
            node = nodes.setdefault(
                entry["key"],
                {
                    "key": entry["key"],
                    "surfaces": Counter(),
                    "sentence_ids": set(),
                    "contexts": Counter(),
                    "edge_signals": [],
                    "played_edges": 0,
                    "total_play_count": 0,
                },
            )
            for surface in entry["surfaces"]:
                node["surfaces"][surface] += 1
            node["sentence_ids"].add(sentence_id)
            context = _context_label(entry.get("translation")) or f"sentence:{sentence_id}"
            node["contexts"][context] += 1
            node["edge_signals"].append(edge_signal)
            if entry["play_count"] > 0:
                node["played_edges"] += 1
            node["total_play_count"] += entry["play_count"]

    averages = [
        sum(node["edge_signals"]) / max(len(node["edge_signals"]), 1)
        for node in nodes.values()
        if len(node["sentence_ids"]) >= 2
    ]
    word_peak = max(float(settings["algorithm_word_node_peak_min"]), sum(averages) / max(len(averages), 1))
    spread = float(settings["algorithm_word_node_spread"])
    for node in nodes.values():
        edge_count = max(len(node["edge_signals"]), 1)
        avg_exposure = sum(node["edge_signals"]) / edge_count
        familiarity = _sigmoid((avg_exposure - word_peak) / spread)
        node["linked_sentence_count"] = len(node["sentence_ids"])
        node["context_count"] = len(node["contexts"])
        node["avg_exposure"] = avg_exposure
        node["familiarity"] = familiarity
        node["weakness"] = 1.0 - familiarity

    return {
        "canonical_map": canonical_map,
        "nodes": nodes,
        "sentence_entries": sentence_entries,
        "word_peak": word_peak,
    }


def _word_network_adjustment(row: dict, settings: dict, word_network: dict | None) -> tuple[float, dict]:
    if not word_network:
        return 0.0, {
            "word_weakness_boost": 0.0,
            "context_diversity_boost": 0.0,
            "word_mastery_penalty": 0.0,
            "linked_words": [],
        }

    sentence_id = int(row["id"])
    entries = word_network.get("sentence_entries", {}).get(sentence_id, [])
    nodes = word_network.get("nodes", {})
    if not entries:
        return 0.0, {
            "word_weakness_boost": 0.0,
            "context_diversity_boost": 0.0,
            "word_mastery_penalty": 0.0,
            "linked_words": [],
        }

    repeat_decay = float(settings["algorithm_word_repeat_decay"])
    sentence_word_signal = float(settings["algorithm_sentence_review_word_signal"])
    sentence_reviews = _safe_int(row.get("review_count"))
    edge_peak = max(1.0, float(word_network.get("word_peak") or 1.0) * 0.75)
    edge_spread = float(settings["algorithm_word_node_spread"])
    weakness_values = []
    diversity_values = []
    mastery_values = []
    linked_words = []

    for entry in entries:
        node = nodes.get(entry["key"])
        if not node or int(node.get("linked_sentence_count") or 0) < 2:
            continue
        edge_exposure = _word_play_signal(_safe_int(entry.get("play_count")), repeat_decay) + sentence_reviews * sentence_word_signal
        edge_need = 1.0 - _sigmoid((edge_exposure - edge_peak) / edge_spread)
        node_weakness = float(node.get("weakness") or 0.0)
        node_familiarity = float(node.get("familiarity") or 0.0)
        linked_count = int(node.get("linked_sentence_count") or 0)
        played_edges = int(node.get("played_edges") or 0)
        target_contexts = min(3, linked_count)

        weakness_values.append(node_weakness * edge_need)
        if played_edges > 0 and played_edges < target_contexts and edge_exposure < edge_peak:
            diversity_values.append((target_contexts - played_edges) / target_contexts)
        if node_familiarity > 0.72 and edge_exposure >= edge_peak:
            mastery_values.append(node_familiarity)

        surfaces = node.get("surfaces")
        if isinstance(surfaces, Counter):
            surface = surfaces.most_common(1)[0][0] if surfaces else entry["key"]
        else:
            surface = entry["surfaces"][0] if entry.get("surfaces") else entry["key"]
        linked_words.append(
            {
                "key": entry["key"],
                "surface": surface,
                "linked_sentences": linked_count,
                "weakness": round(node_weakness, 3),
                "edge_need": round(edge_need, 3),
            }
        )

    if not weakness_values and not diversity_values and not mastery_values:
        return 0.0, {
            "word_weakness_boost": 0.0,
            "context_diversity_boost": 0.0,
            "word_mastery_penalty": 0.0,
            "linked_words": [],
        }

    weakness_values.sort(reverse=True)
    diversity_values.sort(reverse=True)
    mastery_values.sort(reverse=True)
    weakness_boost = min(float(settings["algorithm_word_network_weight"]), sum(weakness_values[:3]) / max(min(len(weakness_values), 3), 1) * float(settings["algorithm_word_network_weight"]))
    diversity_boost = min(float(settings["algorithm_context_diversity_weight"]), sum(diversity_values[:2]) / max(min(len(diversity_values), 2), 1) * float(settings["algorithm_context_diversity_weight"]))
    mastery_penalty = min(float(settings["algorithm_word_mastery_penalty"]), sum(mastery_values[:3]) / max(min(len(mastery_values), 3), 1) * float(settings["algorithm_word_mastery_penalty"]))
    delta = weakness_boost + diversity_boost - mastery_penalty
    linked_words.sort(key=lambda item: (-item["weakness"], -item["linked_sentences"], item["key"]))
    metrics = {
        "word_weakness_boost": round(weakness_boost, 6),
        "context_diversity_boost": round(diversity_boost, 6),
        "word_mastery_penalty": round(mastery_penalty, 6),
        "linked_words": linked_words[:5],
    }
    return delta, metrics


def sentence_word_network_metrics(rows: list[dict], settings: dict | None = None) -> dict[int, dict]:
    selected_settings = settings or SMART_REVIEW_SETTINGS
    word_network = _build_word_network(rows, selected_settings)
    return {
        int(row["id"]): _word_network_adjustment(row, selected_settings, word_network)[1]
        for row in rows
    }


def _score_sentence_for_review(
    row: dict,
    settings: dict,
    sentence_peak: float,
    peak_context: dict,
    word_network: dict | None = None,
) -> tuple[float, dict]:
    sentence_reviews = _safe_int(row.get("review_count"))
    exposure, word_signal = _sentence_exposure(row, settings)
    familiarity = _sigmoid((exposure - sentence_peak) / float(settings["algorithm_sentence_spread"]))
    review_need = 1.0 - familiarity
    if sentence_reviews == 0:
        review_need += float(settings["algorithm_unseen_boost"])
    network_delta, network_metrics = _word_network_adjustment(row, settings, word_network)
    score = review_need + network_delta
    metrics = {
        "score": round(score, 6),
        "base_score": round(review_need, 6),
        "familiarity": round(familiarity, 6),
        "review_need": round(review_need, 6),
        "exposure": round(exposure, 3),
        "word_signal": round(word_signal, 3),
        "peak": round(sentence_peak, 3),
        "peak_mode": peak_context.get("mode"),
        "corpus_count": peak_context.get("corpus_count"),
        "corpus_average_exposure": peak_context.get("corpus_average_exposure"),
        "word_network": network_metrics,
    }
    return score, metrics


def _rank_sentences_by_peak_familiarity(rows: list[dict], settings: dict | None = None) -> list[tuple[dict, dict]]:
    settings = settings or SMART_REVIEW_SETTINGS
    sentence_peak, peak_context = _resolve_sentence_peak(rows, settings)
    word_network = _build_word_network(rows, settings)
    scored = []
    for row in rows:
        score, metrics = _score_sentence_for_review(row, settings, sentence_peak, peak_context, word_network)
        scored.append(
            {
                "row": row,
                "score": score,
                "metrics": metrics,
                "words": _extract_focus_words(row, word_network.get("canonical_map")),
            }
        )
    scored.sort(key=lambda item: (-item["score"], int(item["row"]["id"])))

    recent_limit = int(settings["algorithm_fatigue_recent"])
    penalty = float(settings["algorithm_same_word_penalty"])
    lookahead = int(settings["algorithm_fatigue_lookahead"])
    if recent_limit <= 0 or penalty <= 0:
        return [(item["row"], item["metrics"]) for item in scored]

    ranked = []
    recent_word_sets: list[set[str]] = []
    pending = scored
    while pending:
        recent_counts = Counter(word for words in recent_word_sets[-recent_limit:] for word in words)
        best_index = 0
        best_adjusted = None
        search_limit = min(len(pending), lookahead)
        for index, item in enumerate(pending[:search_limit]):
            overlap = sum(recent_counts[word] for word in item["words"])
            adjusted = item["score"] - penalty * overlap
            if best_adjusted is None or adjusted > best_adjusted:
                best_adjusted = adjusted
                best_index = index
        selected = pending.pop(best_index)
        selected["metrics"]["fatigue_adjusted_score"] = round(float(best_adjusted or selected["score"]), 6)
        ranked.append((selected["row"], selected["metrics"]))
        recent_word_sets.append(selected["words"])
    return ranked
