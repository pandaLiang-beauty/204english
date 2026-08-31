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
    audio_available: true,
    audio_status: 'ready',
    audio_url: '/api/english/sentences/7/audio',
    review_round_item_id: 700,
    review_round_item_completed: roundCompleted,
    review_round_completed: roundCompleted
  }
}

function roundSentence(id, completed = false) {
  return {
    ...sentenceRecord(0, completed),
    id,
    text: `Sentence ${id}.`,
    audio_url: `/api/english/sentences/${id}/audio`,
    review_round_item_id: 1000 + id,
    review_round_position: id
  }
}

test('completed round items stay hidden after paging or reloading the review queue', async () => {
  const originals = {
    stats: englishApi.stats,
    heatmap: englishApi.heatmap,
    sentences: englishApi.sentences
  }
  const requests = []
  const statsRequests = []
  let heatmapRequests = 0

  englishApi.stats = async params => {
    statsRequests.push(params)
    return { active: 4 }
  }
  englishApi.heatmap = async () => {
    heatmapRequests += 1
    return { days: [] }
  }
  englishApi.sentences = async params => {
    requests.push(params)
    if (Number(params.page) === 2) {
      return {
        items: [roundSentence(3, true), roundSentence(4, false)],
        total: 4,
        page: 2,
        review_round: { id: 9, completed: 2, total: 4, remaining: 2 }
      }
    }
    return {
      items: [roundSentence(1, true), roundSentence(2, false)],
      total: 4,
      page: 1,
      review_round: { id: 9, completed: 1, total: 4, remaining: 3 }
    }
  }

  try {
    const list = useEnglishSentenceList({ isReview: () => true })
    await list.load()
    assert.deepEqual(list.sentences.value.map(item => item.id), [2])

    list.page.value = 2
    await list.load()
    assert.deepEqual(list.sentences.value.map(item => item.id), [4])
    assert.equal(requests[0].roundQueue, true)
    assert.equal(requests[0].resume, true)
    assert.equal(requests[1].roundQueue, true)
    assert.equal(requests[1].resume, false)
    assert.equal(heatmapRequests, 0)
    assert.equal(statsRequests.every(params => params.includeWordNetwork === false), true)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('an exhausted review page automatically resumes at the first unfinished page', async () => {
  const originals = {
    stats: englishApi.stats,
    sentences: englishApi.sentences
  }
  const requests = []
  let pageOneCompleted = false

  englishApi.stats = async () => ({ active: 4 })
  englishApi.sentences = async params => {
    requests.push(params)
    if (Number(params.page) === 2) {
      return {
        items: [roundSentence(3), roundSentence(4)],
        total: 4,
        page: 2,
        review_round: { id: 9, completed: 2, total: 4, remaining: 2, resume_page: 2 }
      }
    }
    return {
      items: [roundSentence(1, pageOneCompleted), roundSentence(2, pageOneCompleted)],
      total: 4,
      page: 1,
      review_round: {
        id: 9,
        completed: pageOneCompleted ? 2 : 0,
        total: 4,
        remaining: pageOneCompleted ? 2 : 4,
        resume_page: pageOneCompleted ? 2 : 1
      }
    }
  }

  try {
    const list = useEnglishSentenceList({ isReview: () => true })
    await list.load()
    assert.deepEqual(list.sentences.value.map(item => item.id), [1, 2])

    pageOneCompleted = true
    await list.load()

    assert.deepEqual(list.sentences.value.map(item => item.id), [3, 4])
    assert.equal(list.page.value, 2)
    assert.deepEqual(requests.slice(1).map(request => [request.page, request.resume]), [
      [1, false],
      [2, false]
    ])
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('the heatmap is loaded only on the statistics page', async () => {
  const originals = {
    stats: englishApi.stats,
    heatmap: englishApi.heatmap,
    sentences: englishApi.sentences
  }
  let statsRequests = 0
  let statsParams
  let heatmapRequests = 0
  let sentenceRequests = 0

  englishApi.stats = async params => {
    statsRequests += 1
    statsParams = params
    return { active: 4 }
  }
  englishApi.heatmap = async () => {
    heatmapRequests += 1
    return { days: [], window_days: 119 }
  }
  englishApi.sentences = async () => {
    sentenceRequests += 1
    return { items: [], total: 0, page: 1 }
  }

  try {
    const list = useEnglishSentenceList({ isStats: () => true })
    await list.load()

    assert.equal(statsRequests, 1)
    assert.equal(statsParams.includeWordNetwork, true)
    assert.equal(heatmapRequests, 1)
    assert.equal(sentenceRequests, 0)
    assert.equal(list.heatmap.value.window_days, 119)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('sentence creation failures remain visible to the user', async () => {
  const originalCreateSentence = englishApi.createSentence
  englishApi.createSentence = async () => {
    throw new Error('服务暂时不可用')
  }

  try {
    const list = useEnglishSentenceList()
    list.draft.value.text = 'A sentence that should remain in the editor.'
    await list.createSentence()

    assert.equal(list.error.value, '服务暂时不可用')
    assert.equal(list.draft.value.text, 'A sentence that should remain in the editor.')
    assert.equal(list.saving.value, false)
  } finally {
    englishApi.createSentence = originalCreateSentence
  }
})

test('manual completion and sentence-play exposure are serialized independently', async () => {
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
  let statsRequests = 0

  englishApi.stats = async () => {
    statsRequests += 1
    if (statsRequests > 1) throw new Error('统计暂时不可用')
    return { active: 1 }
  }
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
    return sentenceRecord(payload.event_type === 'sentence_play' ? 1 : 0, callNumber === 1)
  }

  try {
    const list = useEnglishSentenceList({ isReview: () => true })
    await list.load()
    const sentence = list.sentences.value[0]
    const manualReview = list.markReviewed(sentence)
    const audioReview = list.markReviewed(sentence, {
      eventType: 'sentence_play',
      completeRound: false,
      silentMessage: true
    })

    await Promise.resolve()
    assert.equal(calls.length, 1)
    assert.equal(list.sentences.value[0].ui.reviewPending, 2)

    releaseFirstReview()
    await Promise.all([manualReview, audioReview])

    assert.deepEqual(calls.map(call => call.payload.event_type), [
      'sentence_review',
      'sentence_play'
    ])
    assert.deepEqual(calls.map(call => call.payload.complete_round_item), [true, false])
    assert.deepEqual(calls.map(call => call.payload.round_item_id), [700, 700])
    assert.deepEqual(calls.map(call => call.sentenceId), [7, 7])
    assert.equal(maxInFlight, 1)
    assert.equal(list.sentences.value[0].review_count, 1)
    assert.equal(list.sentences.value[0].review_round_item_completed, true)
    assert.equal(list.reviewRound.value.completed, 1)
    assert.equal(list.reviewRound.value.remaining, 0)
    assert.equal(list.sentences.value[0].ui.reviewPending, 0)
    assert.equal(list.sentences.value[0].ui.reviewing, false)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('sentence exposure is recorded at playback start and audio sources do not overlap', async () => {
  const originalPlayWord = englishApi.playWord
  const OriginalAudio = globalThis.Audio
  const sentence = {
    ...sentenceRecord(),
    pronunciations: { focus: '/focus.mp3' },
    ui: {
      audioPlaying: false,
      cachedAudioUrl: '',
      pendingCachedAudioUrl: '',
      wordAudioCache: {},
      message: '',
      status: '',
      wordPlaying: ''
    }
  }
  const exposures = []
  let sentencePauses = 0
  const sentenceAudio = {
    currentTime: 0,
    paused: false,
    pause() {
      sentencePauses += 1
      this.paused = true
    }
  }
  class FakeWordAudio {
    addEventListener() {}
    pause() {}
    async play() {}
  }
  globalThis.Audio = FakeWordAudio
  englishApi.playWord = async () => sentence

  try {
    const controls = useEnglishAudio({ value: [sentence] }, {
      markReviewed: (_sentence, options) => {
        exposures.push(options)
        return Promise.resolve(sentence)
      }
    })
    controls.setSentenceAudioRef(sentence, sentenceAudio)

    controls.handleSentenceAudioPlay(sentence)
    assert.equal(exposures.length, 1)
    assert.equal(exposures[0].eventType, 'sentence_play')

    sentenceAudio.currentTime = 2
    controls.handleSentenceAudioPause(sentence)
    controls.handleSentenceAudioPlay(sentence)
    assert.equal(exposures.length, 1)

    controls.handleSentenceAudioEnded(sentence)
    sentenceAudio.currentTime = 0
    controls.handleSentenceAudioPlay(sentence)
    assert.equal(exposures.length, 2)

    await controls.playWord(sentence, 'focus')
    assert.equal(sentencePauses > 0, true)
  } finally {
    englishApi.playWord = originalPlayWord
    globalThis.Audio = OriginalAudio
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

test('editing sentence text reports that sentence audio will regenerate automatically', async () => {
  const originals = {
    stats: englishApi.stats,
    heatmap: englishApi.heatmap,
    sentences: englishApi.sentences,
    updateSentence: englishApi.updateSentence
  }
  const initial = {
    ...sentenceRecord(),
    text: 'Inline note [remove this] remains.',
    sentence_translation: '译文仍然有效',
    word_translations: {},
    word_tips: {},
    sentence_segments: [],
    translation_segments: []
  }
  let submittedPayload
  let audioRefreshes = 0
  englishApi.stats = async () => ({ active: 1 })
  englishApi.heatmap = async () => ({ days: [] })
  englishApi.sentences = async () => ({ items: [initial], total: 1, page: 1 })
  englishApi.updateSentence = async (_sentenceId, payload) => {
    submittedPayload = payload
    return {
      ...initial,
      text: payload.text,
      audio_available: false,
      audio_url: '',
      audio_status: 'pending',
      audio_needs_regeneration: true
    }
  }

  try {
    const list = useEnglishSentenceList({
      audioControls: () => ({
        scheduleAudioStatusRefresh: () => { audioRefreshes += 1 }
      })
    })
    await list.load()
    const sentence = list.sentences.value[0]
    list.toggleEditor(sentence)
    sentence.ui.editDraft.text = 'Inline note remains.'
    await list.saveSentence(sentence)

    const refreshed = list.sentences.value[0]
    assert.equal(submittedPayload.text, 'Inline note remains.')
    assert.equal(refreshed.ui.showEditor, false)
    assert.match(refreshed.ui.message, /音频已进入重新生成队列/)
    assert.equal(refreshed.audio_status, 'pending')
    assert.equal(audioRefreshes, 1)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('editing a review sentence keeps it available while audio regenerates', async () => {
  const originals = {
    stats: englishApi.stats,
    sentences: englishApi.sentences,
    updateSentence: englishApi.updateSentence
  }
  const initial = {
    ...roundSentence(7),
    text: 'Inline note [remove this] remains.',
    sentence_translation: '译文仍然有效',
    word_translations: {},
    word_tips: {},
    sentence_segments: [],
    translation_segments: []
  }
  let audioRefreshes = 0
  const disposedIds = []
  englishApi.stats = async () => ({ active: 1 })
  englishApi.sentences = async () => ({
    items: [initial],
    total: 1,
    page: 1,
    review_round: {
      id: 3,
      completed: 0,
      total: 1,
      remaining: 1,
      available: 1,
      available_remaining: 1,
      resume_page: 1
    }
  })
  englishApi.updateSentence = async (_sentenceId, payload) => ({
    ...initial,
    text: payload.text,
    audio_available: false,
    audio_url: '',
    audio_status: 'pending',
    audio_needs_regeneration: true
  })

  try {
    const list = useEnglishSentenceList({
      isReview: () => true,
      audioControls: () => ({
        disposeSentenceCaches: items => disposedIds.push(...items.map(item => item.id)),
        scheduleAudioStatusRefresh: () => { audioRefreshes += 1 }
      })
    })
    await list.load()
    const sentence = list.sentences.value[0]
    list.toggleEditor(sentence)
    sentence.ui.editDraft.text = 'Inline note remains.'
    await list.saveSentence(sentence)

    assert.equal(list.sentences.value.length, 1)
    assert.equal(list.sentences.value[0].audio_status, 'pending')
    assert.deepEqual(disposedIds, [])
    assert.equal(audioRefreshes, 0)
    assert.equal(list.total.value, 1)
    assert.equal(list.reviewRound.value.remaining, 1)
    assert.equal(list.reviewRound.value.available, 1)
    assert.equal(list.reviewRound.value.available_remaining, 1)
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

test('passage information edits are included in autosave protection', async () => {
  const originalUpdatePassage = englishApi.updatePassage
  let submittedPayload
  englishApi.updatePassage = async (_passageId, payload) => {
    submittedPayload = payload
    return {
      id: 9,
      title: payload.title,
      source_label: payload.source_label,
      source_url: payload.source_url,
      year: payload.year,
      exam_type: payload.exam_type,
      passage_type: payload.passage_type,
      body_text: payload.body_text,
      status: payload.status
    }
  }

  try {
    const editor = usePassageEditor()
    editor.activePassage.value = {
      id: 9,
      title: 'Original title',
      body_text: 'Original body',
      status: 'reading'
    }
    editor.passageForm.value = {
      id: 9,
      title: 'Updated title',
      sourceLabel: '考研真题',
      sourceUrl: '',
      year: '2026',
      examType: 'english1',
      passageType: 'reading_a',
      bodyText: 'Original body',
      status: 'reading'
    }

    editor.handlePassageFormInput()
    assert.equal(editor.passageDirty.value, true)
    assert.equal(await editor.flushPassageAutosave(), true)
    assert.equal(submittedPayload.title, 'Updated title')
    assert.equal(submittedPayload.year, 2026)
    assert.equal(editor.passageDirty.value, false)
  } finally {
    englishApi.updatePassage = originalUpdatePassage
  }
})

test('an unsaved new passage cannot be silently discarded by navigation', async () => {
  const editor = usePassageEditor()
  editor.passageForm.value.bodyText = 'A new passage draft.'
  editor.handlePassageFormInput({ bodyText: true })

  assert.equal(editor.passageDirty.value, true)
  assert.equal(await editor.flushPassageAutosave(), false)
  assert.equal(editor.passageDirty.value, true)
  assert.match(editor.passageError.value, /尚未保存/)
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

test('首屏的 stats 与句子列表并发请求，不再白等一个隧道往返', async () => {
  const originals = { stats: englishApi.stats, sentences: englishApi.sentences }
  let sentencesCalled = false
  let releaseStats
  // stats 故意卡住：如果这两个请求还是串行的，句子请求永远发不出去，这个测试会挂死。
  const statsGate = new Promise(resolve => {
    releaseStats = resolve
  })

  englishApi.stats = async () => {
    await statsGate
    return { active: 4 }
  }
  englishApi.sentences = async () => {
    sentencesCalled = true
    releaseStats()
    return { items: [roundSentence(1)], total: 1, page: 1 }
  }

  try {
    const list = useEnglishSentenceList({ isReview: () => true })
    await list.load()
    assert.equal(sentencesCalled, true)
    assert.deepEqual(list.sentences.value.map(item => item.id), [1])
    // 句子响应里的 total 必须盖住 fetchActivity 写进去的 stats.active，取值顺序不能被并发打乱。
    assert.equal(list.total.value, 1)
  } finally {
    Object.assign(englishApi, originals)
  }
})

test('音频预加载同时最多 3 个请求在飞，不会把链路打满', async () => {
  const originalWindow = globalThis.window
  const originalFetch = globalThis.fetch
  const originalCreateObjectURL = URL.createObjectURL
  const originalRevokeObjectURL = URL.revokeObjectURL

  let inFlight = 0
  let peak = 0
  let started = 0
  const pending = []

  globalThis.window = { setTimeout, clearTimeout }
  URL.createObjectURL = () => 'blob:stub'
  URL.revokeObjectURL = () => {}
  globalThis.fetch = () => {
    inFlight += 1
    started += 1
    peak = Math.max(peak, inFlight)
    return new Promise(resolve => {
      pending.push(() => {
        inFlight -= 1
        resolve({ ok: true, blob: async () => ({}) })
      })
    })
  }

  // 12 句 × (1 条整句音频 + 2 个生词读音) = 36 个请求；旧实现会几乎同时全部发出。
  const sentences = Array.from({ length: 12 }, (_, index) => ({
    ...roundSentence(index + 1),
    pronunciations: {
      alpha: `/api/english/pronunciations/${index}/alpha.mp3`,
      beta: `/api/english/pronunciations/${index}/beta.mp3`
    },
    ui: { cachedAudioUrl: '', pendingCachedAudioUrl: '', wordAudioCache: {}, audioPreloadPromise: null }
  }))

  try {
    const controls = useEnglishAudio({ value: sentences })
    controls.schedulePreloadWindow(0)
    await new Promise(resolve => setTimeout(resolve, 250))
    assert.equal(peak <= 3, true, `预加载峰值并发 ${peak}，应当不超过 3`)

    for (let guard = 0; pending.length && guard < 200; guard += 1) {
      pending.shift()()
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    assert.equal(peak <= 3, true, `放行过程中峰值并发 ${peak}，应当不超过 3`)
    assert.equal(started, 36)
  } finally {
    globalThis.window = originalWindow
    globalThis.fetch = originalFetch
    URL.createObjectURL = originalCreateObjectURL
    URL.revokeObjectURL = originalRevokeObjectURL
  }
})
