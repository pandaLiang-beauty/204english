import { markedWordCount } from './passageMarkdown.js'

export function emptyPassageForm() {
  return {
    id: null,
    title: '',
    sourceLabel: '',
    sourceUrl: '',
    year: '',
    examType: '',
    passageType: 'custom',
    bodyText: '',
    status: 'new'
  }
}

export function passageToForm(passage) {
  return {
    id: passage?.id || null,
    title: passage?.title || '',
    sourceLabel: passage?.source_label || '',
    sourceUrl: passage?.source_url || '',
    year: passage?.year ? String(passage.year) : '',
    examType: passage?.exam_type || '',
    passageType: passage?.passage_type || 'custom',
    bodyText: passage?.body_text || '',
    status: passage?.status || 'new'
  }
}

export function payloadFromPassageForm(value) {
  const year = String(value.year || '').trim()
  return {
    title: String(value.title || '').trim(),
    source_label: String(value.sourceLabel || '').trim(),
    source_url: String(value.sourceUrl || '').trim(),
    year: year ? Number(year) : null,
    exam_type: String(value.examType || '').trim(),
    passage_type: String(value.passageType || '').trim() || 'custom',
    body_text: String(value.bodyText || '').trim(),
    status: value.status || 'new'
  }
}

export function passageTitle(passage) {
  return passage?.title || passage?.source_label || `阅读文章 #${passage?.id || '-'}`
}

export function passageStatusLabel(status) {
  if (status === 'done') return '已完成'
  if (status === 'reading') return '阅读中'
  return '未开始'
}

export function examTypeLabel(value) {
  if (value === 'english1') return '英语一'
  if (value === 'english2') return '英语二'
  return value || ''
}

export function passageTypeLabel(value) {
  return {
    reading_a: '阅读理解',
    cloze: '完形填空',
    reading_b: '新题型',
    translation: '翻译材料',
    custom: '自建文章'
  }[value] || '自建文章'
}

export function passageActionLabel(passage) {
  if (passage?.status === 'done') return '查看标注'
  return markedWordCount(passage) ? '继续标注' : '开始标注'
}
