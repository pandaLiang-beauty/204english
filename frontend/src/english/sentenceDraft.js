import { markedWordsFromText } from './passageMarkdown.js'

export function emptySentenceDraft() {
  return {
    text: '',
    sentenceTranslation: '',
    sentenceSegmentsText: '',
    translationSegmentsText: '',
    translationsText: '',
    tipsText: ''
  }
}

export function splitBulkSentences(text = '') {
  return String(text || '')
    .split(/(?:\r?\n){2,}/)
    .map(chunk => chunk.trim().replace(/\s+/g, ' '))
    .filter(Boolean)
}

export function sentenceToDraft(sentence) {
  return {
    text: sentence?.text || '',
    sentenceTranslation: sentence?.sentence_translation || '',
    sentenceSegmentsText: stringifySegments(sentence?.sentence_segments || []),
    translationSegmentsText: stringifySegments(sentence?.translation_segments || []),
    translationsText: stringifyMap(sentence?.word_translations || {}),
    tipsText: stringifyMap(sentence?.word_tips || {})
  }
}

export function sentenceDraftPayload(value) {
  const wordTranslations = mergeMarkedWordsIntoTranslations(
    value.text,
    parseMap(value.translationsText)
  )
  return {
    text: String(value.text || '').trim(),
    sentence_translation: String(value.sentenceTranslation || '').trim(),
    sentence_segments: parseSegments(value.sentenceSegmentsText),
    translation_segments: parseSegments(value.translationSegmentsText),
    word_translations: wordTranslations,
    word_tips: filterMapToMarkedWords(value.text, parseMap(value.tipsText))
  }
}

// 与后端的 sentence_translation_source_key 保持一致：加粗只是重点词标记，
// 方括号里的中文只是编辑注记，都不改变整句翻译的来源。
export function translationSourceKey(text) {
  return String(text || '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\[[^\]]*[\u4e00-\u9fff][^\]]*\]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

// 补空释义，也可为已有中文词义补充英文解释。
export function missingMarkedWords(value, { includeMissingEnglish = false } = {}) {
  const translations = parseMap(value?.translationsText)
  const byNormalized = new Map(
    Object.entries(translations)
      .map(([key, translation]) => [String(key || '').trim().toLowerCase(), String(translation || '').trim()])
      .filter(([key]) => key)
  )
  return markedWordsFromText(value?.text)
    .map(item => String(item.word || '').trim())
    .filter(word => {
      const meaning = byNormalized.get(word.toLowerCase())
      return word && (!meaning || (includeMissingEnglish && !englishDefinition(meaning)))
    })
}

export function applyTranslationToDraft(target, result) {
  if (!target || !result) return target
  const wordTranslations = result.word_translations || {}
  const wordTips = result.word_tips || {}
  const hasWordTranslations = Object.keys(wordTranslations).length > 0
  const hasWordTips = Object.keys(wordTips).length > 0
  const sentenceSegments = result.sentence_segments || []
  const translationSegments = result.translation_segments || []
  return {
    ...target,
    sentenceTranslation: result.sentence_translation || target.sentenceTranslation || '',
    sentenceSegmentsText: sentenceSegments.length ? stringifySegments(sentenceSegments) : target.sentenceSegmentsText,
    translationSegmentsText: translationSegments.length ? stringifySegments(translationSegments) : target.translationSegmentsText,
    translationsText: hasWordTranslations ? stringifyMap(wordTranslations) : target.translationsText,
    tipsText: hasWordTips ? stringifyMap(wordTips) : target.tipsText
  }
}

export function applyWordTranslationsToDraft(target, result) {
  if (!target || !result) return target
  const translations = mergeMaps(parseMap(target.translationsText), result.word_translations, (existing, generated) => {
    if (!existing) return generated
    if (englishDefinition(existing)) return existing
    const english = englishDefinition(generated)
    return english ? `${existing.split('；英文：')[0]}；英文：${english}` : existing
  })
  const tips = mergeMaps(parseMap(target.tipsText), result.word_tips, (existing, generated) => existing || generated)
  return {
    ...target,
    translationsText: stringifyMap(translations),
    tipsText: stringifyMap(tips)
  }
}

function englishDefinition(meaning) {
  const separator = '；英文：'
  const text = String(meaning || '')
  const index = text.indexOf(separator)
  return index < 0 ? '' : text.slice(index + separator.length).trim()
}

function stringifyMap(value) {
  return Object.entries(value || {}).map(([key, text]) => `${key}=${text || ''}`).join('\n')
}

function parseMap(text) {
  const output = {}
  String(text || '').split(/\r?\n/).forEach(line => {
    const trimmed = line.trim()
    if (!trimmed) return
    const index = trimmed.indexOf('=')
    if (index <= 0) return
    const key = trimmed.slice(0, index).trim()
    if (!key) return
    output[key] = trimmed.slice(index + 1).trim()
  })
  return output
}

function stringifySegments(value) {
  return (Array.isArray(value) ? value : [])
    .map(item => String(item || '').trim())
    .filter(Boolean)
    .join(' / ')
}

function parseSegments(text) {
  return String(text || '')
    .split(/\s*\/\s*/)
    .map(item => item.trim().replace(/\s+/g, ' '))
    .filter(Boolean)
}

function mergeMaps(existing, additions, mergeValue = (_existing, generated) => generated) {
  const output = { ...(existing || {}) }
  const existingKeys = new Map(
    Object.keys(output).map(key => [String(key || '').trim().toLowerCase(), key])
  )
  for (const [rawKey, rawValue] of Object.entries(additions || {})) {
    const key = String(rawKey || '').trim()
    if (!key) continue
    const existingKey = existingKeys.get(key.toLowerCase()) || key
    output[existingKey] = mergeValue(output[existingKey], String(rawValue || '').trim())
    existingKeys.set(key.toLowerCase(), existingKey)
  }
  return output
}

function mergeMarkedWordsIntoTranslations(text, translations) {
  const source = translations || {}
  const byNormalized = new Map(
    Object.entries(source)
      .map(([key, value]) => [key.trim().toLowerCase(), value])
      .filter(([key]) => key)
  )
  const output = {}
  for (const item of markedWordsFromText(text)) {
    const word = String(item.word || '').trim()
    const key = word.toLowerCase()
    if (!word) continue
    output[word] = byNormalized.get(key) || ''
  }
  return output
}

function filterMapToMarkedWords(text, mapping) {
  const allowed = new Set(markedWordsFromText(text).map(item => String(item.word || '').trim().toLowerCase()))
  return Object.fromEntries(
    Object.entries(mapping || {}).filter(([key]) => allowed.has(String(key || '').trim().toLowerCase()))
  )
}
