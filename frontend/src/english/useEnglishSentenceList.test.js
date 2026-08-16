import assert from 'node:assert/strict'
import test from 'node:test'

import { englishApi } from './api.js'
import { useEnglishAudio } from './useEnglishAudio.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { usePassageEditor } from './usePassageEditor.js'

function sentenceRecord(reviewCount = 0, roundCompleted = false) {
  return {
    id: 7,
    text: 'Repeated use builds familiarity.',
    review_count: reviewCount,
    word_play_total: 0,
    review_round_item_completed: roundCompleted,
    review_round_completed: roundCompleted
  }
}

test('manual review and natural audio completion are serialized additive events', async () => {
  const originals = {
    stats: englishApi.stats,
    heatmap: englishApi.heatmap,
    sentences: englishApi.sentences,
    reviewSentence: englishApi.reviewSentence
  }
  let releaseFirstReview
  const firstReviewGate = new Promise(resolve => {
    releaseFirstReview = resolve
  })
  const calls = []
  let inFlight = 0
  let maxInFlight = 0

  englishApi.stats = async () => ({ active: 1 })
  englishApi.heatmap = async () => ({ days: [] })
  englishApi.sentences = async () => ({
    items: [sentenceRecord()],
    total: 1,
    page: 1,
    review_round: { id: 3, completed: 0, total: 1, remaining: 1 }
  })
  englishApi.reviewSentence = async (sentenceId, payload) => {
    const callNumber = calls.length + 1
    calls.push({ sentenceId, payload })
    inFlight += 1
    maxInFlight = Math.max(maxInFlight, inFlight)
    if (callNumber === 1) await firstReviewGate
    inFlight -= 1
    return sentenceRecord(callNumber, callNumber === 1)
  }

  try {
    const list = useEnglishSentenceList({ isReview: () => true })
    await list.load()
    const sentence = list.sentences.value[0]
    const audio = useEnglishAudio(list.sentences, {
      markReviewed: list.markReviewed
    })

    const manualReview = list.markReviewed(sentence)
    const audioReview = audio.handleSentenceAudioEnded(sentence)

    await Promise.resolve()
    assert.equal(calls.length, 1)
    assert.equal(list.sentences.value[0].ui.reviewPending, 2)

    releaseFirstReview()
    await Promise.all([manualReview, audioReview])

    assert.deepEqual(calls.map(call => call.payload.event_type), [
      'sentence_review',
      'sentence_play'
    ])
    assert.deepEqual(calls.map(call => call.sentenceId), [7, 7])
    assert.equal(maxInFlight, 1)
    assert.equal(list.sentences.value[0].review_count, 2)
    assert.equal(list.sentences.value[0].review_round_item_completed, true)
    assert.equal(list.reviewRound.value.completed, 1)
    assert.equal(list.reviewRound.value.remaining, 0)
    assert.equal(list.sentences.value[0].ui.reviewPending, 0)
    assert.equal(list.sentences.value[0].ui.reviewing, false)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('an older AI translation cannot overwrite a draft edited while the request is running', async () => {
  const originalTranslateText = englishApi.translateText
  let releaseTranslation
  const translationResult = new Promise(resolve => {
    releaseTranslation = resolve
  })
  englishApi.translateText = async () => translationResult

  try {
    const list = useEnglishSentenceList()
    list.draft.value.text = 'The **current** sentence.'
    const request = list.translateDraft()
    await Promise.resolve()

    list.draft.value.sentenceTranslation = '用户刚刚输入的翻译'
    releaseTranslation({
      sentence_translation: '过期的 AI 翻译',
      sentence_segments: ['The current sentence.'],
      translation_segments: ['过期的 AI 翻译'],
      word_translations: { current: '当前的' },
      word_tips: {}
    })
    await request

    assert.equal(list.draft.value.sentenceTranslation, '用户刚刚输入的翻译')
    assert.equal(list.draft.value.translationsText, '')
  } finally {
    englishApi.translateText = originalTranslateText
  }
})

test('a sentence save response preserves edits made after the request started', async () => {
  const originals = {
    stats: englishApi.stats,
    heatmap: englishApi.heatmap,
    sentences: englishApi.sentences,
    updateSentence: englishApi.updateSentence
  }
  let releaseSave
  const saveGate = new Promise(resolve => {
    releaseSave = resolve
  })
  let submittedPayload
  const initial = {
    ...sentenceRecord(),
    text: 'A **focus** word remains.',
    sentence_translation: '旧译文',
    word_translations: { focus: '重点', stale: '过期' },
    word_tips: { focus: '提示', stale: '过期提示' },
    sentence_segments: [],
    translation_segments: []
  }
  englishApi.stats = async () => ({ active: 1 })
  englishApi.heatmap = async () => ({ days: [] })
  englishApi.sentences = async () => ({ items: [initial], total: 1, page: 1 })
  englishApi.updateSentence = async (_sentenceId, payload) => {
    submittedPayload = payload
    return saveGate
  }

  try {
    const list = useEnglishSentenceList()
    await list.load()
    const sentence = list.sentences.value[0]
    list.toggleEditor(sentence)
    const pendingSave = list.saveSentence(sentence)
    await Promise.resolve()

    assert.deepEqual(submittedPayload.word_translations, { focus: '重点' })
    assert.deepEqual(submittedPayload.word_tips, { focus: '提示' })
    sentence.ui.editDraft.sentenceTranslation = '请求发出后输入的新译文'
    releaseSave({
      ...initial,
      sentence_translation: '旧译文',
      word_translations: { focus: '重点' },
      word_tips: { focus: '提示' }
    })
    await pendingSave

    const refreshed = list.sentences.value[0]
    assert.equal(refreshed.ui.showEditor, true)
    assert.equal(refreshed.ui.editDraft.sentenceTranslation, '请求发出后输入的新译文')
    assert.equal(refreshed.sentence_translation, '旧译文')
    assert.match(refreshed.ui.message, /仍待保存/)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('a passage save response preserves edits made after the request started', async () => {
  const originalUpdatePassage = englishApi.updatePassage
  const originalWarn = console.warn
  let releaseSave
  const saveGate = new Promise(resolve => {
    releaseSave = resolve
  })
  englishApi.updatePassage = async () => saveGate
  console.warn = () => {}

  try {
    const editor = usePassageEditor()
    const passage = {
      id: 9,
      title: 'Race passage',
      source_label: '',
      source_url: '',
      year: null,
      exam_type: '',
      passage_type: 'custom',
      body_text: 'Request body',
      status: 'reading'
    }
    editor.passages.value = [passage]
    editor.activePassage.value = passage
    editor.passageForm.value = {
      id: 9,
      title: 'Race passage',
      sourceLabel: '',
      sourceUrl: '',
      year: '',
      examType: '',
      passageType: 'custom',
      bodyText: 'Request body',
      status: 'reading'
    }

    const pendingSave = editor.savePassage()
    await Promise.resolve()
    editor.passageForm.value = {
      ...editor.passageForm.value,
      bodyText: 'Newer local body'
    }
    releaseSave(passage)
    await pendingSave

    assert.equal(editor.passageForm.value.bodyText, 'Newer local body')
    assert.equal(editor.activePassage.value.body_text, 'Newer local body')
    assert.equal(editor.passageDirty.value, true)
    assert.match(editor.passageMessage.value, /仍待保存/)
  } finally {
    englishApi.updatePassage = originalUpdatePassage
    console.warn = originalWarn
  }
})

test('passage flush waits for the active autosave request', async () => {
  const originalUpdatePassage = englishApi.updatePassage
  const originalWarn = console.warn
  let releaseSave
  const saveGate = new Promise(resolve => {
    releaseSave = resolve
  })
  englishApi.updatePassage = async () => saveGate
  console.warn = () => {}

  try {
    const editor = usePassageEditor()
    editor.activePassage.value = { id: 9, status: 'reading' }
    editor.passageForm.value = {
      id: 9,
      title: 'Autosave passage',
      sourceLabel: '',
      sourceUrl: '',
      year: '',
      examType: '',
      passageType: 'custom',
      bodyText: 'Edited body',
      status: 'reading'
    }
    editor.passageDirty.value = true

    let settled = false
    const flush = editor.flushPassageAutosave().then(result => {
      settled = true
      return result
    })
    await Promise.resolve()
    assert.equal(settled, false)

    releaseSave({
      id: 9,
      title: 'Autosave passage',
      source_label: '',
      source_url: '',
      year: null,
      exam_type: '',
      passage_type: 'custom',
      body_text: 'Edited body',
      status: 'reading'
    })
    assert.equal(await flush, true)
    assert.equal(editor.passageDirty.value, false)
  } finally {
    englishApi.updatePassage = originalUpdatePassage
    console.warn = originalWarn
  }
})
