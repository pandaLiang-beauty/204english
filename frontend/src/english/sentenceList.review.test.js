import assert from 'node:assert/strict'
import test from 'node:test'

import { englishApi } from './api.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { roundSentence, sentenceRecord } from './testFixtures.js'

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
