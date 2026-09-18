// Keep these rules in sync with backend/app/english/sentence_boundaries.py.
// Shared fixtures exercise both implementations, including candidate indexes.
const titles = new Set('mr mrs ms dr prof sr st mt gen gov sen rep capt lt col rev hon'.split(' '))
const abbreviations = new Set('jr vs etc e.g i.e a.m p.m ph.d no fig vol pp inc ltd co dept approx est jan feb mar apr jun jul aug sep sept oct nov dec'.split(' '))
const sentenceStarts = new Set('The This That These Those It He She They We I You However But Yet Meanwhile Next Then A An In On At After Before When While Why How What Where Who Which There Here As For To By Our Their Its His Her All Some Many Most Not No Both Each Such'.split(' '))
const terminal = /[.!?。！？]/
const closer = /["'’”）)\]}»]/

function internalPeriod(text, index) {
  const before = text.slice(0, index).replace(/\*\*/g, '')
  const after = text.slice(index + 1).replace(/\*\*/g, '')
  if (/^[0-9]/.test(after)) return true
  // Interior initialism periods and domains have no whitespace after the dot.
  if (/[A-Za-z0-9]$/.test(before) && /^[A-Za-z0-9]/.test(after)) return true
  const token = before.match(/[A-Za-z][A-Za-z.]*$/)?.[0] || ''
  const next = after.replace(/^[\s"'’”）)\]}»]+/, '').match(/^[A-Za-z0-9]+/)?.[0] || ''
  if (!next) return false
  if (titles.has(token.toLowerCase())) return true
  const abbreviated = abbreviations.has(token.toLowerCase()) || /^(?:[A-Za-z]\.)+[A-Za-z]$/.test(token)
  const initial = /^[A-Z]$/.test(token) && /^[A-Z]/.test(next)
  return (abbreviated || initial) && !sentenceStarts.has(next)
}

export function splitEnglishSentences(value) {
  const source = String(value || '').replace(/\r\n?/g, '\n').trim()
  const chunks = []
  for (const paragraph of source.split(/\n\s*\n/)) {
    const text = paragraph.replace(/\s+/g, ' ').trim()
    let start = 0
    let bold = false
    for (let index = 0; index < text.length; index += 1) {
      if (text.slice(index, index + 2) === '**') {
        bold = !bold
        index += 1
        continue
      }
      if (!terminal.test(text[index])) continue
      if (text[index] === '.' && internalPeriod(text, index)) continue
      let end = index + 1
      while (end < text.length && terminal.test(text[end])) end += 1
      let closesQuote = false
      let closesBold = false
      while (end < text.length) {
        if (closer.test(text[end])) {
          closesQuote = true
          end += 1
        } else if (bold && !closesBold && text.slice(end, end + 2) === '**') {
          closesBold = true
          end += 2
        } else break
      }
      if (bold && !closesBold) continue
      const continuation = text.slice(end).trimStart().replace(/^\*\*/, '')
      const ellipsis = text.slice(index, end).startsWith('..')
      if ((closesQuote || ellipsis) && /^[a-z]/.test(continuation)) {
        if (closesBold) bold = false
        index = end - 1
        continue
      }
      const sentence = text.slice(start, end).trim()
      if (sentence) chunks.push(sentence)
      if (closesBold) bold = false
      start = end
      index = end - 1
    }
    const remainder = text.slice(start).trim()
    if (remainder) chunks.push(remainder)
  }
  return chunks
}
