// 英语 passage / 富文本编辑器共用的 markdown 纯函数工具。
// 不含组件状态，供 RichMarkedTextEditor.vue、usePassageEditor.js 复用。

export function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[char])
}

export function inlineMarkedHtml(text) {
  const source = String(text || '')
  let html = ''
  let last = 0
  const regex = /\*\*([^*]+)\*\*/g
  let match
  while ((match = regex.exec(source))) {
    html += escapeHtml(source.slice(last, match.index))
    html += `<strong class="rounded bg-primary/10 px-1 font-semibold text-primary">${escapeHtml(match[1])}</strong>`
    last = match.index + match[0].length
  }
  html += escapeHtml(source.slice(last))
  return html || '<br>'
}

export function markedTextToEditableHtml(text) {
  const source = String(text || '')
  return source ? inlineMarkedHtml(source).replace(/\n/g, '<br>') : ''
}

export function passageParagraphs(passage) {
  const text = String(passage?.body_text || '').trim()
  if (!text) return []
  return text
    .split(/\n{2,}/)
    .map(item => item.trim().replace(/\s+/g, ' '))
    .filter(Boolean)
}

export function passageTextToHtml(text) {
  const source = String(text || '').trim()
  if (!source) return '<p><br></p>'
  return source
    .split(/\n{2,}/)
    .map(paragraph => `<p>${inlineMarkedHtml(paragraph.trim())}</p>`)
    .join('')
}

export function domNodeToMarkdown(node, inBold = false) {
  if (!node) return ''
  if (node.nodeType === 3) return node.nodeValue || ''
  if (node.nodeType !== 1) return ''
  const tag = String(node.tagName || '').toLowerCase()
  if (tag === 'br') return '\n'
  const isBold = tag === 'strong' || tag === 'b'
  const childText = Array.from(node.childNodes || [])
    .map(child => domNodeToMarkdown(child, inBold || isBold))
    .join('')
  if (isBold && !inBold) {
    const cleaned = childText.replace(/\*\*/g, '')
    return cleaned.trim() ? `**${cleaned}**` : ''
  }
  if (['p', 'div', 'article', 'section'].includes(tag)) {
    return `${childText.trim()}\n\n`
  }
  if (tag === 'li') return `${childText.trim()}\n`
  return childText
}

export function editableElementToMarkdown(el) {
  if (!el) return ''
  return Array.from(el.childNodes || [])
    .map(node => domNodeToMarkdown(node))
    .join('')
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function splitMarkedPassageSentences(text) {
  const source = String(text || '').replace(/[ \t]+/g, ' ').trim()
  if (!source) return []
  const chunks = []
  source.split(/\n{2,}/).forEach(paragraph => {
    const normalized = paragraph.trim()
    if (!normalized) return
    const matches = normalized.match(/[^.!?。！？]+[.!?。！？]+(?:["')\]]+)?|[^.!?。！？]+$/g)
    if (matches?.length) chunks.push(...matches.map(item => item.trim()).filter(Boolean))
    else chunks.push(normalized)
  })
  return chunks
}

export function markedWordsFromText(text) {
  const result = []
  const seen = new Set()
  const regex = /\*\*([^*]+)\*\*/g
  let match
  while ((match = regex.exec(String(text || '')))) {
    const word = match[1].trim().replace(/\s+/g, ' ')
    const key = word.toLowerCase()
    if (!word || seen.has(key)) continue
    seen.add(key)
    result.push({ word, translation: '', tip: '' })
  }
  return result
}

export function manualPassageCandidates(passage) {
  const candidates = []
  const seen = new Set()
  splitMarkedPassageSentences(passage?.body_text || '').forEach(sentence => {
    const focusWords = markedWordsFromText(sentence)
    if (!focusWords.length) return
    const key = sentence.replace(/\*\*/g, '').trim().toLowerCase()
    if (!key || seen.has(key)) return
    seen.add(key)
    candidates.push({
      text: sentence,
      translation: '',
      reason: '手工标注',
      focus_words: focusWords
    })
  })
  return candidates
}

export function passageCandidates(passage) {
  return manualPassageCandidates(passage)
}

export function candidateCount(passage) {
  return passageCandidates(passage).length
}

export function markedWordCount(passage) {
  return markedWordsFromText(passage?.body_text || '').length
}
