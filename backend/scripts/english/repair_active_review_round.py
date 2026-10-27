from __future__ import annotations

"""Refreeze one active English review round using the agreed priority rules."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.english.ranking import rank_sentences_for_review  # noqa: E402
from app.english.review_rounds import round_play_context  # noqa: E402
from app.english.schema import initialize_schema  # noqa: E402
from app.platform.db import begin_immediate, get_connection, rows_to_dicts  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_round(conn, *, user_id: int, round_id: int | None) -> dict:
    if round_id is None:
        row = conn.execute(
            """
            SELECT *
            FROM english_review_rounds
            WHERE user_id = ? AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM english_review_rounds WHERE user_id = ? AND id = ?",
            (user_id, int(round_id)),
        ).fetchone()
    if not row:
        raise RuntimeError("active English review round not found")
    if str(row["status"]) != "active":
        raise RuntimeError(f"round {int(row['id'])} is not active")
    return dict(row)


def _resolve_previous_round_id(conn, *, user_id: int, current: dict, requested: int | None) -> int | None:
    if requested is not None:
        return int(requested)
    if current.get("previous_round_id") is not None:
        return int(current["previous_round_id"])
    row = conn.execute(
        """
        SELECT id
        FROM english_review_rounds
        WHERE user_id = ? AND id < ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, int(current["id"])),
    ).fetchone()
    return int(row["id"]) if row else None


def build_repair_plan(
    conn,
    *,
    user_id: int,
    round_id: int | None = None,
    previous_round_id: int | None = None,
) -> dict:
    current = _resolve_round(conn, user_id=user_id, round_id=round_id)
    round_value = int(current["id"])
    previous_value = _resolve_previous_round_id(
        conn,
        user_id=user_id,
        current=current,
        requested=previous_round_id,
    )
    context = round_play_context(conn, user_id=user_id, round_id=previous_value)
    items = rows_to_dicts(
        conn.execute(
            """
            SELECT ri.id AS item_id, ri.sentence_id, ri.position, ri.completed_at,
                   s.*
            FROM english_review_round_items ri
            JOIN english_sentences s ON s.id = ri.sentence_id
            WHERE ri.round_id = ? AND COALESCE(s.deleted_at, '') = ''
            ORDER BY ri.position, ri.id
            """,
            (round_value,),
        ).fetchall()
    )
    completed = [item for item in items if str(item["completed_at"] or "")]
    incomplete = [item for item in items if not str(item["completed_at"] or "")]
    completed.sort(key=lambda item: (int(item["position"]), int(item["item_id"])))

    ranked_all = rank_sentences_for_review(
        items,
        previous_completed_sentence_ids=context["completed_sentence_ids"],
        previous_sentence_plays=context["sentence_plays"],
        previous_word_plays=context["word_plays"],
    )
    metrics_by_item = {
        int(row["item_id"]): metrics
        for row, metrics in ranked_all
    }
    ranked_incomplete = rank_sentences_for_review(
        incomplete,
        previous_completed_sentence_ids=context["completed_sentence_ids"],
        previous_sentence_plays=context["sentence_plays"],
        previous_word_plays=context["word_plays"],
    )
    ordered_incomplete = [row for row, _ in ranked_incomplete]
    ordered = completed + ordered_incomplete
    if len(ordered) != len(items) or len({int(item["item_id"]) for item in ordered}) != len(items):
        raise RuntimeError("repair plan did not preserve every visible round item")
    for position, item in enumerate(ordered, start=1):
        item["new_position"] = position
        item["new_exposure_score"] = float(metrics_by_item[int(item["item_id"])]["previous_exposure"])
    return {
        "round": current,
        "round_id": round_value,
        "previous_round_id": previous_value,
        "items": ordered,
        "completed_count": len(completed),
        "incomplete_count": len(incomplete),
        "first_incomplete_position": len(completed) + 1 if incomplete else None,
    }


def apply_repair_plan(conn, plan: dict) -> None:
    round_id = int(plan["round_id"])
    round_row = plan["round"]
    previous_round_id = plan["previous_round_id"]
    items = plan["items"]
    if not items:
        return
    item_ids = [int(item["item_id"]) for item in items]
    completed_before = {
        int(item["item_id"]): str(item["completed_at"] or "")
        for item in items
    }
    offset = max((int(item["position"]) for item in items), default=0) + 10_000
    conn.execute(
        "UPDATE english_review_round_items SET position = position + ? WHERE round_id = ?",
        (offset, round_id),
    )
    timestamp = _now()
    for item in items:
        conn.execute(
            """
            UPDATE english_review_round_items
            SET position = ?, exposure_score = ?, updated_at = ?
            WHERE id = ? AND round_id = ?
            """,
            (
                int(item["new_position"]),
                float(item["new_exposure_score"]),
                timestamp,
                int(item["item_id"]),
                round_id,
            ),
        )
    conn.execute(
        """
        UPDATE english_review_rounds
        SET previous_round_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (previous_round_id, timestamp, round_id),
    )
    verify = rows_to_dicts(
        conn.execute(
            """
            SELECT id, sentence_id, position, completed_at
            FROM english_review_round_items
            WHERE round_id = ?
            ORDER BY position
            """,
            (round_id,),
        ).fetchall()
    )
    if len(verify) != len(items):
        raise RuntimeError("round item count changed during repair")
    if [int(row["position"]) for row in verify] != list(range(1, len(items) + 1)):
        raise RuntimeError("round positions are not contiguous after repair")
    if {int(row["id"]): str(row["completed_at"] or "") for row in verify} != completed_before:
        raise RuntimeError("completion state changed during repair")
    if int(round_row["id"]) != round_id:
        raise RuntimeError("round identity changed during repair")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--round-id", type=int)
    parser.add_argument("--previous-round-id", type=int)
    parser.add_argument("--apply", action="store_true", help="write the repair transaction")
    args = parser.parse_args()

    initialize_schema()
    with get_connection() as conn:
        begin_immediate(conn)
        plan = build_repair_plan(
            conn,
            user_id=int(args.user_id),
            round_id=args.round_id,
            previous_round_id=args.previous_round_id,
        )
        print(
            f"round={plan['round_id']} previous_round={plan['previous_round_id']} "
            f"total={len(plan['items'])} completed={plan['completed_count']} "
            f"incomplete={plan['incomplete_count']} first_incomplete={plan['first_incomplete_position']}"
        )
        if args.apply:
            apply_repair_plan(conn, plan)
            print("repair applied")
        else:
            print("dry run only; pass --apply to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
