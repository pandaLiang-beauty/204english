import assert from 'node:assert/strict'
import test from 'node:test'
import { englishApi } from './api.js'
import { useEnglishAudio } from './useEnglishAudio.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { deferred, sentenceRecord } from './testFixtures.js'

function mockRound(t, items = [sentenceRecord()]) {
  t.mock.method(englishApi, 'stats', async () => ({ active: items.length }))
  t.mock.method(englishApi, 'sentences', async () => ({
    items, page: 1, total: items.length,
    review_round: { id: 3, completed: 0, total: items.length, remaining: items.length }
  }))
  return useEnglishSentenceList({ isReview: () => true })
}

test('a late word response preserves completion, counters, current content and draft of its repeat', async t => {
  const originalAudio = globalThis.Audio
  globalThis.Audio = class { addEventListener() {} pause() {} async play() {} }
  t.after(() => { globalThis.Audio = originalAudio })
  const initial = {
    ...sentenceRecord(), text: 'A **focus** word.',
    word_translations: { focus: '重点' }, pronunciations: { focus: '/focus.mp3' },
    sentence_translation: '旧译文'
  }
  const list = mockRound(t, [initial, { ...initial, review_round_item_id: 701 }])
  const word = deferred(), started = deferred()
  t.mock.method(englishApi, 'playWord', () => { started.resolve(); return word.promise })
  t.mock.method(englishApi, 'reviewSentence', async () => ({
    ...initial, review_count: 2, completion_count: 1,
    review_round_item_completed: true, review_round_completed: false
  }))
  await list.load()
  const sentence = list.sentences.value[0]
  const audio = useEnglishAudio(list.sentences, {
    updateSentenceInList: list.updateSentenceInList, refreshActivity: list.refreshActivity
  })
  list.toggleEditor(sentence)
  const playback = audio.playWord(sentence, 'focus')
  await started.promise
  await list.markReviewed(sentence)
  list.updateSentenceInList({ id: sentence.id, sentence_translation: '新保存的译文' }, sentence)
  list.sentences.value[0].ui.editDraft.sentenceTranslation = '还在编辑的译文'
  word.resolve({ ...initial, word_play_counts: { focus: 1 }, word_play_total: 1 })
  await playback
  const fresh = list.sentences.value[0]
  assert.equal(fresh.review_round_item_completed, true)
  assert.equal(fresh.review_count, 2)
  assert.equal(fresh.completion_count, 1)
  assert.equal(fresh.sentence_translation, '新保存的译文')
  assert.equal(fresh.ui.editDraft.sentenceTranslation, '还在编辑的译文')
  assert.equal(fresh.word_play_total, 1)
  assert.equal(fresh.word_play_counts.focus, 1)
  assert.equal(list.sentences.value[1].review_round_item_completed, false)
  assert.equal(list.reviewRound.value.completed, 1)
})

test('out-of-order word responses cannot reduce counts or resurrect an unmarked word', async t => {
  const initial = { ...sentenceRecord(), text: 'A **focus** word.', word_translations: { focus: '重点' } }
  const list = mockRound(t, [initial])
  await list.load()
  const old = list.sentences.value[0]
  list.updateSentenceInList({ ...initial, word_play_total: 2, word_play_counts: { focus: 2 } }, old, { scope: 'word-play' })
  list.updateSentenceInList({ ...initial, word_play_total: 1, word_play_counts: { focus: 1 } }, old, { scope: 'word-play' })
  assert.equal(list.sentences.value[0].word_play_counts.focus, 2)
  list.updateSentenceInList({ id: old.id, text: 'A focus word.', word_translations: {}, word_play_counts: {} }, old)
  list.updateSentenceInList({ ...initial, word_play_total: 3, word_play_counts: { focus: 3 } }, old, { scope: 'word-play' })
  assert.equal(list.sentences.value[0].word_play_total, 3)
  assert.deepEqual(list.sentences.value[0].word_play_counts, {})
  assert.equal(list.sentences.value[0].text, 'A focus word.')
})

test('completion retry reconciles progress after a committed response is lost, without double counting', async t => {
  const list = mockRound(t)
  let calls = 0
  t.mock.method(englishApi, 'reviewSentence', async () => {
    if (++calls === 1) throw new Error('响应丢失')
    return {
      ...sentenceRecord(), completion_count: 1,
      review_round_item_completed: false, review_round_item_is_completed: true,
      review_round_completed: true, review_round_next_at: '2026-09-19T00:00:00Z',
      review_round: { id: 3, total: 1, completed: 1, remaining: 0, is_completed: true, next_round_at: '2026-09-19T00:00:00Z' }
    }
  })
  await list.load()
  await list.markReviewed(list.sentences.value[0])
  assert.equal(list.reviewRound.value.completed, 0)
  assert.match(list.sentences.value[0].ui.message, /响应丢失/)
  await list.markReviewed(list.sentences.value[0])
  assert.equal(list.sentences.value[0].review_round_item_completed, true)
  assert.equal(list.reviewRound.value.completed, 1)
  assert.equal(list.reviewRound.value.remaining, 0)
  assert.equal(list.reviewRound.value.is_completed, true)
  assert.equal(list.reviewRound.value.next_round_at, '2026-09-19T00:00:00Z')
  await list.markReviewed(list.sentences.value[0])
  assert.equal(list.reviewRound.value.completed, 1)
  assert.equal(list.sentences.value[0].completion_count, 1)
})

test('responses from a previous round cannot complete or reload a newly loaded round', async t => {
  for (const expired of [false, true]) {
    const list = mockRound(t)
    const response = deferred()
    t.mock.method(englishApi, 'reviewSentence', () => response.promise)
    await list.load()
    const request = list.markReviewed(list.sentences.value[0])
    list.resetForModeChange()
    const nextItem = { ...sentenceRecord(), review_round_item_id: 800 }
    const next = { id: 4, total: 1, completed: 0, remaining: 1 }
    const loads = t.mock.method(englishApi, 'sentences', async () => ({ items: [nextItem], total: 1, page: 1, review_round: next }))
    await list.load()
    response.resolve({
      ...sentenceRecord(0, true), review_round_expired: expired,
      review_round: { id: 3, total: 1, completed: 1, remaining: 0, is_completed: true }
    })
    await request
    assert.equal(list.reviewRound.value.id, 4)
    assert.equal(list.reviewRound.value.completed, 0)
    assert.equal(list.sentences.value[0].review_round_item_completed, false)
    assert.equal(loads.mock.callCount(), 1)
  }
})

test('concurrent completion snapshots arriving backwards keep authoritative progress', async t => {
  const initial = sentenceRecord()
  const list = mockRound(t, [initial, { ...initial, review_round_item_id: 701 }])
  const first = deferred(), second = deferred()
  t.mock.method(englishApi, 'reviewSentence', (_id, payload) => payload.round_item_id === 700 ? first.promise : second.promise)
  await list.load()
  const one = list.markReviewed(list.sentences.value[0])
  const two = list.markReviewed(list.sentences.value[1])
  second.resolve({ ...initial, review_round_item_is_completed: true, review_round_completed: true,
    review_round: { id: 3, completed: 2, total: 2, remaining: 0, is_completed: true, next_round_at: '2026-09-19T00:00:00Z' } })
  await two
  first.resolve({ ...initial, review_round_item_is_completed: true,
    review_round: { id: 3, completed: 1, total: 2, remaining: 1, is_completed: false } })
  await one
  assert.equal(list.reviewRound.value.completed, 2)
  assert.equal(list.reviewRound.value.remaining, 0)
  assert.equal(list.reviewRound.value.is_completed, true)
  assert.equal(list.reviewRound.value.next_round_at, '2026-09-19T00:00:00Z')
})

test('a list snapshot started before completion cannot put a completed card back into the queue', async t => {
  const list = mockRound(t)
  await list.load()
  const pending = deferred()
  t.mock.method(englishApi, 'sentences', () => pending.promise)
  t.mock.method(englishApi, 'reviewSentence', async () => ({
    ...sentenceRecord(), review_round_item_is_completed: true, review_round_completed: true,
    review_round: { id: 3, total: 1, completed: 1, remaining: 0, is_completed: true }
  }))
  const load = list.load()
  await list.markReviewed(list.sentences.value[0])
  pending.resolve({ items: [sentenceRecord()], total: 1, page: 1,
    review_round: { id: 3, total: 1, completed: 0, remaining: 1 } })
  await load
  assert.equal(list.sentences.value.length, 0)
  assert.equal(list.reviewRound.value.completed, 1)
  assert.equal(list.reviewRound.value.remaining, 0)
})
