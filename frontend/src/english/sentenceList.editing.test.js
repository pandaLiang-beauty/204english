import assert from 'node:assert/strict'
import test from 'node:test'

import { englishApi } from './api.js'
import { useEnglishAudio } from './useEnglishAudio.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { roundSentence, sentenceRecord } from './testFixtures.js'

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

test('adding a focus marker requests meanings only for newly unfilled words', async () => {
  const originals = {
    stats: englishApi.stats,
    sentences: englishApi.sentences,
    translateText: englishApi.translateText,
    translateWords: englishApi.translateWords
  }
  const initial = {
    ...sentenceRecord(),
    text: 'A **known** and new word.',
    sentence_translation: '一个已知词和一个新词。',
    sentence_segments: ['A known and new word.'],
    translation_segments: ['一个已知词和一个新词。'],
    word_translations: { known: '本义：知道；句中：已知的' },
    word_tips: { known: 'know 的过去分词' }
  }
  const wordRequests = []
  let fullTranslationCalls = 0
  englishApi.stats = async () => ({ active: 1 })
  englishApi.sentences = async () => ({ items: [initial], total: 1, page: 1 })
  englishApi.translateText = async () => {
    fullTranslationCalls += 1
    throw new Error('the full translation path must not run')
  }
  englishApi.translateWords = async payload => {
    wordRequests.push(payload)
    return {
      items: [],
      word_translations: { new: '本义：新的；句中：新出现的' },
      word_tips: { new: '常与名词连用' }
    }
  }

  try {
    const list = useEnglishSentenceList()
    await list.load()
    const sentence = list.sentences.value[0]
    list.toggleEditor(sentence)
    sentence.ui.editDraft.text = 'A **known** and **new** word.'

    await list.translateSentenceDraft(sentence)

    assert.deepEqual(wordRequests, [{ text: 'A **known** and **new** word.', words: ['new'] }])
    assert.equal(fullTranslationCalls, 0)
    assert.equal(sentence.ui.editDraft.sentenceTranslation, initial.sentence_translation)
    assert.equal(sentence.ui.editDraft.sentenceSegmentsText, 'A known and new word.')
    assert.equal(sentence.ui.editDraft.translationSegmentsText, '一个已知词和一个新词。')
    assert.match(sentence.ui.editDraft.translationsText, /^known=本义：知道；句中：已知的$/m)
    assert.match(sentence.ui.editDraft.translationsText, /^new=本义：新的；句中：新出现的$/m)
    assert.match(sentence.ui.editDraft.tipsText, /^known=know 的过去分词$/m)
    assert.match(sentence.ui.editDraft.tipsText, /^new=常与名词连用$/m)
    assert.match(sentence.ui.message, /已补充 1 个新增重点词释义/)
  } finally {
    Object.assign(englishApi, originals)
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
