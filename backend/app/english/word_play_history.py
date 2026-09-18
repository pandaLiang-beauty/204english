from __future__ import annotations

from collections import Counter, defaultdict

from ..platform.db import begin_immediate
from .ranking import _normalize_dict, _normalize_focus_word, _safe_int


def lifetime_word_total(row: dict) -> int:
    """Lifetime plays never shrink when the current focus-word map is pruned."""
    counts = _normalize_dict(row.get("word_play_counts_json"))
    return max(_safe_int(row.get("word_play_total")), sum(_safe_int(value) for value in counts.values()))


def reconcile_word_play_totals(conn) -> list[dict]:
    """Raise old totals to the history we can prove, including retained legacy plays.

    A per-word count may include plays from before the event log existed. Taking
    only max(total, event count) loses that baseline when *another* word was
    removed. For each word take max(retained count, logged plays), then keep any
    larger imported aggregate. No events, dates, focus counts or rounds change.
    Repeating this repair is safe; missing legacy history is never guessed.
    """
    if not conn.in_transaction:
        begin_immediate(conn)
    events = defaultdict(Counter)
    for event in conn.execute(
        """
        SELECT sentence_id, word, COUNT(*) AS count FROM english_review_events
        WHERE event_type = 'word_play' AND sentence_id IS NOT NULL
        GROUP BY sentence_id, word
        """
    ):
        events[int(event["sentence_id"])][_normalize_focus_word(event["word"])] += int(event["count"])
    changes = []
    for record in conn.execute("SELECT id, word_play_total, word_play_counts_json FROM english_sentences").fetchall():
        row = dict(record)
        retained = Counter()
        for word, value in _normalize_dict(row.get("word_play_counts_json")).items():
            retained[_normalize_focus_word(word)] += _safe_int(value)
        tracked = events[int(row["id"])]
        recovered = sum(max(retained[word], tracked[word]) for word in retained.keys() | tracked.keys())
        before = _safe_int(row["word_play_total"])
        after = max(before, recovered)
        if after <= before:
            continue
        conn.execute("UPDATE english_sentences SET word_play_total = ? WHERE id = ?", (after, row["id"]))
        changes.append({"sentence_id": int(row["id"]), "before": before, "after": after})
    return changes
