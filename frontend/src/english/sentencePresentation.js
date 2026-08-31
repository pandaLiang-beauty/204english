/**
 * Sentence-only presentation helpers.
 *
 * These functions deliberately have no Vue or network dependency so list,
 * review and audio features render the same sentence identity and metadata.
 */
export function sentenceInstanceKey(sentence) {
  if (typeof sentence === 'number' || typeof sentence === 'string') {
    return `sentence-${Number(sentence || 0)}`
  }
  const roundItemId = Number(sentence?.review_round_item_id || 0)
  return roundItemId > 0 ? `round-${roundItemId}` : `sentence-${Number(sentence?.id || 0)}`
}

export function sentenceTokens(text) {
  const source = String(text || '')
  const tokens = []
  const regex = /\*\*([^*]+)\*\*/g
  let last = 0
  let match
  while ((match = regex.exec(source))) {
    if (match.index > last) tokens.push({ text: source.slice(last, match.index), focus: false })
    tokens.push({ text: match[1], focus: true })
    last = match.index + match[0].length
  }
  if (last < source.length) tokens.push({ text: source.slice(last), focus: false })
  return tokens.length ? tokens : [{ text: source, focus: false }]
}

export function plainSentenceText(text) {
  return String(text || '').replace(/\*\*/g, '')
}

export function hasTranslationContent(sentence) {
  return Boolean(
    String(sentence?.sentence_translation || '').trim()
    || (sentence?.sentence_segments || []).length
    || (sentence?.translation_segments || []).length
  )
}

export function segmentPairs(sentence) {
  const sources = Array.isArray(sentence?.sentence_segments) ? sentence.sentence_segments : []
  const targets = Array.isArray(sentence?.translation_segments) ? sentence.translation_segments : []
  const count = Math.max(sources.length, targets.length)
  if (!count) return []
  return Array.from({ length: count }, (_, index) => ({
    source: sources[index] || '',
    target: targets[index] || ''
  })).filter(pair => pair.source || pair.target)
}

export function sentenceSegmentSources(sentence) {
  return segmentPairs(sentence).map(pair => pair.source).filter(Boolean)
}

export function sentenceSegmentTargets(sentence) {
  return segmentPairs(sentence).map(pair => pair.target).filter(Boolean)
}

export function focusWordCount(sentence) {
  return Object.keys(sentence?.word_translations || {}).length
}

export function wordEntries(sentence) {
  const translations = sentence?.word_translations || {}
  const tips = sentence?.word_tips || {}
  const counts = sentence?.word_play_counts || {}
  const audio = sentence?.pronunciations || {}
  return Object.entries(translations).map(([word, meaning]) => ({
    word,
    meaning,
    tip: tips[word] || '',
    count: counts[word] || 0,
    audio: audio[word] || ''
  }))
}

export function networkWords(sentence) {
  return sentence?.word_network?.linked_words || sentence?.algorithm?.word_network?.linked_words || []
}

export function wordEntryTitle(entry) {
  return [entry?.word, entry?.meaning, entry?.tip].filter(Boolean).join(' · ')
}

export function networkWordTitle(word) {
  const surface = word?.surface || word?.key || '关联词'
  const linked = Number(word?.linked_sentences || 0)
  const weakness = Math.round(Number(word?.weakness || 0) * 100)
  return `${surface} · 关联 ${linked} 个句子 · 薄弱度 ${weakness}%`
}
