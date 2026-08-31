export function sentenceRecord(reviewCount = 0, roundCompleted = false) {
  return {
    id: 7,
    text: 'Repeated use builds familiarity.',
    review_count: reviewCount,
    word_play_total: 0,
    audio_available: true,
    audio_status: 'ready',
    audio_url: '/api/english/sentences/7/audio',
    review_round_item_id: 700,
    review_round_item_completed: roundCompleted,
    review_round_completed: roundCompleted
  }
}
export function roundSentence(id, completed = false) {
  return {
    ...sentenceRecord(0, completed),
    id,
    text: `Sentence ${id}.`,
    audio_url: `/api/english/sentences/${id}/audio`,
    review_round_item_id: 1000 + id,
    review_round_position: id
  }
}
