import assert from 'node:assert/strict'
import test from 'node:test'
import { englishApi } from './api.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { deferred, sentenceRecord } from './testFixtures.js'

test('a slow review load and activity response cannot overwrite the library', async t => {
  let mode = 'review'
  const review = deferred(), stats = deferred()
  t.mock.method(englishApi, 'stats', () => mode === 'review' ? stats.promise : Promise.resolve({ active: 710 }))
  t.mock.method(englishApi, 'sentences', () => mode === 'review' ? review.promise : Promise.resolve({
    items: [{ id: 710, text: 'Library sentence.' }], page: 1, total: 710
  }))
  const list = useEnglishSentenceList({ isReview: () => mode === 'review' })
  const old = list.load()
  mode = 'library'
  list.resetForModeChange()
  list.sort.value = 'id-desc'
  list.pageSize.value = 40
  await list.load()
  review.resolve({ items: [sentenceRecord()], page: 15, total: 1050, review_round: { id: 12 } })
  stats.resolve({ active: 700 })
  await old
  assert.equal(list.sentences.value[0].id, 710)
  assert.equal(list.page.value, 1)
  assert.equal(list.total.value, 710)
  assert.equal(list.stats.value.active, 710)
  assert.equal(list.reviewRound.value, null)
  assert.equal(list.loading.value, false)
})

test('stale errors and finally blocks do not clear a newer loading indicator', async t => {
  const first = deferred(), second = deferred()
  let requests = 0
  t.mock.method(englishApi, 'stats', async () => ({ active: 1 }))
  t.mock.method(englishApi, 'sentences', () => ++requests === 1 ? first.promise : second.promise)
  const list = useEnglishSentenceList()
  const old = list.load()
  const current = list.load()
  first.reject(new Error('旧请求失败'))
  await old
  assert.equal(list.loading.value, true)
  assert.equal(list.error.value, '')
  second.resolve({ items: [], total: 0, page: 1 })
  await current
  assert.equal(list.loading.value, false)
  assert.equal(list.error.value, '')
})

test('a delayed resume-page response cannot restore a review page after changing modes', async t => {
  let mode = 'review'
  const resume = deferred(), started = deferred()
  t.mock.method(englishApi, 'stats', async () => ({ active: 2 }))
  t.mock.method(englishApi, 'sentences', async params => {
    if (mode === 'library') return { items: [{ id: 8, text: 'Library.' }], page: 1, total: 2 }
    if (params.page === 2) { started.resolve(); return resume.promise }
    return { items: [sentenceRecord(0, true)], page: 1, total: 2,
      review_round: { id: 3, remaining: 1, resume_page: 2 } }
  })
  const list = useEnglishSentenceList({ isReview: () => mode === 'review' })
  const old = list.load()
  await started.promise
  mode = 'library'
  list.resetForModeChange()
  await list.load()
  resume.resolve({ items: [sentenceRecord()], page: 2, total: 2, review_round: { id: 3 } })
  await old
  assert.equal(list.sentences.value[0].id, 8)
  assert.equal(list.page.value, 1)
  assert.equal(list.reviewRound.value, null)
})

test('statistics, pagination and component disposal also invalidate obsolete loads', async t => {
  const pending = deferred()
  let mode = 'stats'
  t.mock.method(englishApi, 'stats', () => mode === 'stats' ? pending.promise : Promise.resolve({ active: 1 }))
  t.mock.method(englishApi, 'heatmap', async () => ({ days: [{ date: 'old' }] }))
  t.mock.method(englishApi, 'sentences', async () => ({ items: [sentenceRecord()], page: 2, total: 1 }))
  const list = useEnglishSentenceList({ isStats: () => mode === 'stats' })
  const old = list.load()
  mode = 'library'
  list.resetForModeChange()
  await list.load()
  pending.resolve({ active: 99 })
  await old
  assert.equal(list.sentences.value.length, 1)
  assert.equal(list.heatmap.value, null)
  assert.equal(list.stats.value.active, 1)
  const response = deferred()
  t.mock.method(englishApi, 'sentences', () => response.promise)
  const load = list.load()
  list.dispose()
  response.resolve({ items: [], total: 0, page: 1 })
  await load
  assert.equal(list.sentences.value.length, 1)
  assert.equal(list.loading.value, false)
})

test('activity refresh never replaces a filtered list total', async t => {
  t.mock.method(englishApi, 'stats', async () => ({ active: 710 }))
  t.mock.method(englishApi, 'sentences', async () => ({ items: [sentenceRecord()], page: 1, total: 1 }))
  const list = useEnglishSentenceList()
  list.appliedSearch.value = 'familiarity'
  await list.load()
  await list.refreshActivity()
  assert.equal(list.total.value, 1)
  assert.equal(list.pageCount.value, 1)
})
