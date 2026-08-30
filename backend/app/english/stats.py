from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from ..platform.db import get_connection, rows_to_dicts
from .ranking import SMART_REVIEW_SETTINGS, _build_word_network


def _word_network_summary(rows: list[dict], *, limit: int = 8) -> dict:
    network = _build_word_network(rows, SMART_REVIEW_SETTINGS)
    nodes = []
    for node in network.get("nodes", {}).values():
        linked_count = int(node.get("linked_sentence_count") or 0)
        if linked_count < 2:
            continue
        surfaces = node.get("surfaces")
        if isinstance(surfaces, Counter):
            surface_items = [surface for surface, _ in surfaces.most_common(4)]
        else:
            surface_items = []
        nodes.append(
            {
                "key": node.get("key"),
                "surfaces": surface_items,
                "linked_sentences": linked_count,
                "contexts": int(node.get("context_count") or 0),
                "played_edges": int(node.get("played_edges") or 0),
                "total_play_count": int(node.get("total_play_count") or 0),
                "avg_exposure": round(float(node.get("avg_exposure") or 0.0), 3),
                "familiarity": round(float(node.get("familiarity") or 0.0), 3),
                "weakness": round(float(node.get("weakness") or 0.0), 3),
            }
        )
    nodes.sort(key=lambda item: (-float(item["weakness"]), -int(item["linked_sentences"]), str(item["key"])))
    return {
        "word_peak": round(float(network.get("word_peak") or 0.0), 3),
        "cross_sentence_words": len(nodes),
        "weak_words": nodes[:limit],
    }


def stats(*, user_id: int, include_word_network: bool = True) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    with get_connection() as conn:
        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(CASE WHEN COALESCE(deleted_at, '') = '' THEN 1 END) AS active,
                COUNT(
                    CASE
                        WHEN COALESCE(deleted_at, '') = ''
                         AND COALESCE(audio_path, '') <> ''
                         AND COALESCE(audio_hash, '') <> ''
                         AND COALESCE(audio_status, '') = 'ready'
                        THEN 1
                    END
                ) AS with_audio,
                COALESCE(SUM(review_count), 0) AS sentence_reviews,
                COALESCE(SUM(completion_count), 0) AS sentence_completions,
                COALESCE(SUM(word_play_total), 0) AS word_reviews
            FROM english_sentences
            """
        ).fetchone()
        today_rows = conn.execute(
            """
            SELECT event_type, COUNT(*) AS count
            FROM english_review_events
            WHERE user_id = ? AND substr(created_at, 1, 10) = ?
            GROUP BY event_type
            """,
            (user_id, today),
        ).fetchall()
        today_reviewed_row = conn.execute(
            """
            SELECT COUNT(DISTINCT sentence_id) AS count
            FROM english_review_events
            WHERE user_id = ? AND substr(created_at, 1, 10) = ?
              AND event_type = 'sentence_review'
            """,
            (user_id, today),
        ).fetchone()
        all_event_rows = conn.execute(
            """
            SELECT event_type, COUNT(*) AS count
            FROM english_review_events
            WHERE user_id = ?
            GROUP BY event_type
            """,
            (user_id,),
        ).fetchall()
        active_rows = (
            rows_to_dicts(
                conn.execute("SELECT * FROM english_sentences WHERE COALESCE(deleted_at, '') = ''").fetchall()
            )
            if include_word_network
            else []
        )
    today_counts = {str(row["event_type"]): int(row["count"]) for row in today_rows}
    all_event_counts = {str(row["event_type"]): int(row["count"]) for row in all_event_rows}
    sentence_reviews = int(summary["sentence_reviews"] or 0)
    sentence_completions = int(summary["sentence_completions"] or 0)
    word_reviews = int(summary["word_reviews"] or 0)
    tracked_sentence_reviews = all_event_counts.get("sentence_play", 0)
    tracked_sentence_completions = all_event_counts.get("sentence_review", 0)
    tracked_word_reviews = all_event_counts.get("word_play", 0)
    legacy_sentence_reviews = max(0, sentence_reviews - tracked_sentence_reviews)
    legacy_word_reviews = max(0, word_reviews - tracked_word_reviews)
    result = {
        "total": int(summary["total"] or 0),
        "active": int(summary["active"] or 0),
        "with_audio": int(summary["with_audio"] or 0),
        "sentence_reviews": sentence_reviews,
        "sentence_completions": sentence_completions,
        "word_reviews": word_reviews,
        "tracked": {
            "sentence_reviews": tracked_sentence_reviews,
            "sentence_completions": tracked_sentence_completions,
            "word_reviews": tracked_word_reviews,
            "total_reviews": tracked_sentence_reviews + tracked_word_reviews,
        },
        "legacy": {
            "sentence_reviews": legacy_sentence_reviews,
            "sentence_completions": max(0, sentence_completions - tracked_sentence_completions),
            "word_reviews": legacy_word_reviews,
            "total_reviews": legacy_sentence_reviews + legacy_word_reviews,
        },
        "today": {
            "reviewed_sentences": int(today_reviewed_row["count"] or 0),
            "sentence_reviews": today_counts.get("sentence_play", 0),
            "sentence_completions": today_counts.get("sentence_review", 0),
            "word_reviews": today_counts.get("word_play", 0),
            "focus_toggles": today_counts.get("focus_word_toggle", 0),
        },
    }
    if include_word_network:
        result["word_network"] = _word_network_summary(active_rows)
    return result


def review_heatmap(*, user_id: int, days: int = 119) -> dict:
    window = max(7, min(int(days or 119), 370))
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=window - 1)
    date_range = [start + timedelta(days=index) for index in range(window)]
    by_date = {
        day.isoformat(): {
            "date": day.isoformat(),
            "weekday": day.weekday(),
            "sentence_reviews": 0,
            "word_reviews": 0,
            "focus_toggles": 0,
            "total": 0,
        }
        for day in date_range
    }
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, event_type, COUNT(*) AS count
            FROM english_review_events
            WHERE user_id = ? AND substr(created_at, 1, 10) >= ?
            GROUP BY substr(created_at, 1, 10), event_type
            ORDER BY day
            """,
            (user_id, start.isoformat()),
        ).fetchall()
        all_event_rows = conn.execute(
            """
            SELECT event_type, COUNT(*) AS count
            FROM english_review_events
            WHERE user_id = ?
            GROUP BY event_type
            """,
            (user_id,),
        ).fetchall()
        lifetime_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(review_count), 0) AS sentence_reviews,
                COALESCE(SUM(word_play_total), 0) AS word_reviews
            FROM english_sentences
            """
        ).fetchone()

    for row in rows:
        day = str(row["day"] or "")
        item = by_date.get(day)
        if not item:
            continue
        event_type = str(row["event_type"] or "")
        count = int(row["count"] or 0)
        if event_type == "sentence_play":
            item["sentence_reviews"] += count
            item["total"] += count
        elif event_type == "word_play":
            item["word_reviews"] += count
            item["total"] += count
        elif event_type == "focus_word_toggle":
            item["focus_toggles"] += count

    items = list(by_date.values())
    max_count = max((int(item["total"]) for item in items), default=0)
    active_days = sum(1 for item in items if int(item["total"]) > 0)
    total_reviews = sum(int(item["total"]) for item in items)
    all_event_counts = {str(row["event_type"]): int(row["count"]) for row in all_event_rows}
    tracked_sentence_reviews = all_event_counts.get("sentence_play", 0)
    tracked_word_reviews = all_event_counts.get("word_play", 0)
    lifetime_sentence_reviews = int(lifetime_row["sentence_reviews"] if lifetime_row else 0)
    lifetime_word_reviews = int(lifetime_row["word_reviews"] if lifetime_row else 0)
    legacy_sentence_reviews = max(0, lifetime_sentence_reviews - tracked_sentence_reviews)
    legacy_word_reviews = max(0, lifetime_word_reviews - tracked_word_reviews)
    longest_streak = 0
    current_run = 0
    for item in items:
        if int(item["total"]) > 0:
            current_run += 1
            longest_streak = max(longest_streak, current_run)
        else:
            current_run = 0
    current_streak = 0
    for item in reversed(items):
        if int(item["total"]) <= 0:
            break
        current_streak += 1
    return {
        "days": items,
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "window_days": window,
        "max_count": max_count,
        "active_days": active_days,
        "total_reviews": total_reviews,
        "tracked_sentence_reviews": tracked_sentence_reviews,
        "tracked_word_reviews": tracked_word_reviews,
        "tracked_total_reviews": tracked_sentence_reviews + tracked_word_reviews,
        "legacy_sentence_reviews": legacy_sentence_reviews,
        "legacy_word_reviews": legacy_word_reviews,
        "legacy_total_reviews": legacy_sentence_reviews + legacy_word_reviews,
        "lifetime_sentence_reviews": lifetime_sentence_reviews,
        "lifetime_word_reviews": lifetime_word_reviews,
        "lifetime_total_reviews": lifetime_sentence_reviews + lifetime_word_reviews,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
    }
