export function mergeReviewRoundState(current, snapshot) {
  if (!current || !snapshot || Number(current.id) !== Number(snapshot.id)) return snapshot || null
  // The round is fixed. An older snapshot cannot undo completions already
  // acknowledged by another card or a retry while this request was in flight.
  const total = Number(snapshot.total ?? current.total ?? 0)
  const completed = Math.min(total, Math.max(Number(current.completed || 0), Number(snapshot.completed || 0)))
  return {
    ...current, ...snapshot, total, completed,
    remaining: Math.max(total - completed, 0),
    available_remaining: Math.max(total - completed, 0),
    is_completed: total > 0 && completed >= total,
    next_round_at: snapshot.next_round_at || current.next_round_at
  }
}
