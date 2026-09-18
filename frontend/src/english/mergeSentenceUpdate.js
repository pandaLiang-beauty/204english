const lifetimeCounters = ['review_count', 'completion_count', 'word_play_total']

export function mergeSentenceUpdate(current, updated, scope) {
  const older = Date.parse(updated.updated_at) < Date.parse(current.updated_at)
  const merged = scope || older ? { ...current } : { ...current, ...updated }
  for (const field of lifetimeCounters) {
    if (updated[field] !== undefined) merged[field] = Math.max(Number(current[field] || 0), Number(updated[field] || 0))
  }
  if (scope === 'word-play' && current.text === updated.text) {
    // An old pronunciation response must not restore removed focus words.
    merged.word_play_counts = { ...current.word_play_counts }
    for (const word of Object.keys(current.word_translations || {})) {
      if (updated.word_play_counts?.[word] !== undefined) {
        merged.word_play_counts[word] = Math.max(Number(merged.word_play_counts[word] || 0), Number(updated.word_play_counts[word] || 0))
      }
    }
    merged.focus_word_play_total = Object.values(merged.word_play_counts).reduce((sum, count) => sum + Number(count || 0), 0)
  }
  if (!scope || scope === 'review') {
    for (const field of ['review_round_item_completed', 'review_round_completed']) {
      if (current[field] !== undefined || updated[field] !== undefined) merged[field] = Boolean(current[field] || updated[field])
    }
  }
  return merged
}
