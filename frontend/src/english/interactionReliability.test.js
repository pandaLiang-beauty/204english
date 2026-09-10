import assert from 'node:assert/strict'
import test from 'node:test'
import { englishApi } from './api.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { usePassageEditor } from './usePassageEditor.js'
import { roundSentence } from './testFixtures.js'

test('activity refresh preserves repeated review items and filtered library pagination', async () => {
  const originals = { stats: englishApi.stats, sentences: englishApi.sentences }
  englishApi.stats = async () => ({ active: 4 })
  englishApi.sentences = async params => ({
    items: [roundSentence(1), roundSentence(2)], total: 6, page: params.page,
    review_round: { id: 1, total: 6, completed: 0, remaining: 6 }
  })
  try {
    const list = useEnglishSentenceList({ isReview: () => true })
    list.pageSize.value = 2
    await list.load()
    await list.refreshActivity()
    assert.equal(list.total.value, 6)
    assert.equal(list.pageCount.value, 3)
    await list.nextPage()
    await list.nextPage()
    assert.equal(list.page.value, 3)
    englishApi.sentences = async () => ({ items: [roundSentence(1)], total: 1, page: 1 })
    const library = useEnglishSentenceList()
    library.searchInput.value = 'one match'
    await library.applySearch()
    await library.refreshActivity()
    assert.equal(library.total.value, 1)
  } finally { Object.assign(englishApi, originals) }
})

test('a library search does not become a search filter on the review round', async () => {
  const originals = { stats: englishApi.stats, sentences: englishApi.sentences }
  let isReview = false
  let lastRequest
  englishApi.stats = async () => ({ active: 4 })
  englishApi.sentences = async params => { lastRequest = params; return { items: [], total: 0 } }
  try {
    const list = useEnglishSentenceList({ isReview: () => isReview })
    list.searchInput.value = 'context'
    await list.applySearch()
    isReview = true
    list.resetForModeChange()
    await list.load()
    assert.equal(lastRequest.search, '')
    assert.equal(lastRequest.roundQueue, true)
  } finally { Object.assign(englishApi, originals) }
})

test('a late response from an earlier page does not replace the current page', async () => {
  const originals = { stats: englishApi.stats, sentences: englishApi.sentences }
  let releaseOld
  const old = new Promise(resolve => { releaseOld = resolve })
  let calls = 0
  englishApi.stats = async () => ({ active: 2 })
  englishApi.sentences = async () => ++calls === 1 ? old : { items: [roundSentence(2)], total: 2, page: 2 }
  try {
    const list = useEnglishSentenceList()
    const pending = list.load()
    list.page.value = 2
    await list.load()
    releaseOld({ items: [roundSentence(1)], total: 2, page: 1 })
    await pending
    assert.equal(list.page.value, 2)
    assert.equal(list.sentences.value[0].id, 2)
    assert.equal(list.loading.value, false)
  } finally { Object.assign(englishApi, originals) }
})

test('adding marked sentences preserves article edits made while the request runs', async () => {
  const original = englishApi.syncPassageSentences
  let release
  englishApi.syncPassageSentences = () => new Promise(resolve => { release = resolve })
  try {
    const editor = usePassageEditor()
    const passage = { id: 8, title: 'Reading', body_text: 'An **important** sentence.', status: 'reading', selected_sentence_ids: [] }
    await editor.selectPassage(passage)
    const pending = editor.syncSelectedCandidates()
    editor.passageForm.value.bodyText += ' A newer note.'
    editor.handlePassageFormInput({ bodyText: true })
    release({ inserted: 1, reused: 0, passage: { ...passage, selected_sentence_ids: [20] } })
    await pending
    assert.equal(editor.passageForm.value.bodyText, 'An **important** sentence. A newer note.')
    assert.equal(editor.activePassage.value.body_text, editor.passageForm.value.bodyText)
    assert.deepEqual(editor.activePassage.value.selected_sentence_ids, [20])
    assert.equal(editor.passageDirty.value, true)
  } finally { englishApi.syncPassageSentences = original }
})

test('an article action cannot switch back to an article that was left during the request', async () => {
  const original = englishApi.syncPassageSentences
  let release
  englishApi.syncPassageSentences = () => new Promise(resolve => { release = resolve })
  try {
    const editor = usePassageEditor()
    const first = { id: 8, title: 'First', body_text: 'An **important** sentence.', status: 'reading' }
    await editor.selectPassage(first)
    const pending = editor.syncSelectedCandidates()
    await editor.selectPassage({ id: 9, title: 'Second', body_text: 'Keep reading this.', status: 'reading' })
    release({ inserted: 1, passage: { ...first, selected_sentence_ids: [20] } })
    await pending
    assert.equal(editor.activePassage.value.id, 9)
    assert.equal(editor.passageForm.value.bodyText, 'Keep reading this.')
  } finally { englishApi.syncPassageSentences = original }
})
