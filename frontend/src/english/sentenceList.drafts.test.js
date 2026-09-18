import assert from 'node:assert/strict'
import test from 'node:test'
import { englishApi } from './api.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { deferred, sentenceRecord } from './testFixtures.js'

function setup(t) {
  let mode = 'library'
  const initial = { ...sentenceRecord(), sentence_translation: '旧译文', word_translations: {} }
  delete initial.review_round_item_id
  t.mock.method(englishApi, 'stats', async () => ({ active: 21 }))
  t.mock.method(englishApi, 'heatmap', async () => ({ days: [] }))
  t.mock.method(englishApi, 'sentences', async params => ({
    items: params.page === 2 ? [{ ...initial, id: 8 }] : [initial], total: 21, page: params.page
  }))
  const list = useEnglishSentenceList({ isStats: () => mode === 'stats' })
  return { list, initial, async navigate(next) { mode = next; list.resetForModeChange(); await list.load() } }
}

test('sentence drafts survive statistics, pagination, editor collapse and refresh without autosaving', async t => {
  const { list, navigate } = setup(t)
  const writes = t.mock.method(englishApi, 'updateSentence', async () => { throw new Error('unexpected autosave') })
  await list.load()
  const original = list.sentences.value[0]
  list.toggleEditor(original)
  assert.equal(list.hasPendingChanges(), false)
  original.ui.editDraft.sentenceTranslation = '保留这份草稿'
  assert.equal(list.hasPendingChanges(), true)
  list.toggleEditor(original)
  list.toggleEditor(original)
  assert.equal(original.ui.editDraft.sentenceTranslation, '保留这份草稿')
  await navigate('stats')
  assert.equal(list.sentences.value.length, 0)
  assert.equal(list.hasPendingChanges(), true)
  await navigate('library')
  await list.nextPage()
  assert.equal(list.sentences.value[0].id, 8)
  assert.equal(list.hasPendingChanges(), true)
  await list.prevPage()
  await list.load()
  const restored = list.sentences.value[0]
  assert.equal(restored.ui.showEditor, true)
  assert.equal(restored.ui.editDraft.sentenceTranslation, '保留这份草稿')
  assert.equal(restored.sentence_translation, '旧译文')
  assert.equal(writes.mock.callCount(), 0)
})

test('saving a retained draft clears dirty state and subsequent editing starts from the saved version', async t => {
  const { list, initial, navigate } = setup(t)
  t.mock.method(englishApi, 'updateSentence', async (_id, payload) => { Object.assign(initial, payload); return { ...initial } })
  await list.load()
  list.toggleEditor(list.sentences.value[0])
  list.sentences.value[0].ui.editDraft.sentenceTranslation = '保存后的译文'
  await navigate('stats')
  await navigate('library')
  await list.saveSentence(list.sentences.value[0])
  assert.equal(list.hasPendingChanges(), false)
  list.toggleEditor(list.sentences.value[0])
  assert.equal(list.sentences.value[0].ui.editDraft.sentenceTranslation, '保存后的译文')
  assert.equal(list.hasPendingChanges(), false)
})

test('a save completing on another page preserves a newer edit and the busy state', async t => {
  const { list, initial, navigate } = setup(t)
  const save = deferred()
  t.mock.method(englishApi, 'updateSentence', () => save.promise)
  await list.load()
  const sentence = list.sentences.value[0]
  list.toggleEditor(sentence)
  sentence.ui.editDraft.sentenceTranslation = '提交的译文'
  const request = list.saveSentence(sentence)
  await navigate('stats')
  await navigate('library')
  assert.equal(list.sentences.value[0].ui.saving, true)
  list.sentences.value[0].ui.editDraft.sentenceTranslation = '提交后继续修改'
  save.resolve({ ...initial, sentence_translation: '提交的译文' })
  await request
  assert.equal(list.sentences.value[0].ui.saving, false)
  assert.equal(list.sentences.value[0].ui.editDraft.sentenceTranslation, '提交后继续修改')
  assert.equal(list.sentences.value[0].sentence_translation, '提交的译文')
  assert.equal(list.hasPendingChanges(), true)
  assert.match(list.sentences.value[0].ui.message, /仍待保存/)
})

test('an old translation after paging cannot overwrite a more recently edited draft', async t => {
  const { list, navigate } = setup(t)
  const translation = deferred()
  t.mock.method(englishApi, 'translateText', () => translation.promise)
  await list.load()
  const sentence = list.sentences.value[0]
  list.toggleEditor(sentence)
  sentence.ui.editDraft.text = 'New text to translate.'
  const request = list.translateSentenceDraft(sentence)
  await navigate('stats')
  await navigate('library')
  assert.equal(list.sentences.value[0].ui.translating, true)
  list.sentences.value[0].ui.editDraft.sentenceTranslation = '用户新写的译文'
  translation.resolve({ sentence_translation: '旧 AI 结果' })
  await request
  assert.equal(list.sentences.value[0].ui.editDraft.sentenceTranslation, '用户新写的译文')
  assert.equal(list.sentences.value[0].ui.translating, false)
  assert.equal(list.hasPendingChanges(), true)
})

test('a failed save keeps its draft after navigation and new sentence forms are protected too', async t => {
  const { list, navigate } = setup(t)
  t.mock.method(englishApi, 'updateSentence', async () => { throw new Error('保存暂时失败') })
  await list.load()
  list.toggleEditor(list.sentences.value[0])
  list.sentences.value[0].ui.editDraft.sentenceTranslation = '失败后保留'
  await list.saveSentence(list.sentences.value[0])
  await navigate('stats')
  await navigate('library')
  assert.equal(list.sentences.value[0].ui.editDraft.sentenceTranslation, '失败后保留')
  assert.match(list.sentences.value[0].ui.message, /保存暂时失败/)
  list.sentences.value[0].ui.editDraft.sentenceTranslation = '旧译文'
  assert.equal(list.hasPendingChanges(), false)
  list.draft.value.text = 'New unsaved sentence.'
  assert.equal(list.hasPendingChanges(), true)
  list.draft.value.text = ''
  list.bulkText.value = 'Bulk draft.'
  assert.equal(list.hasPendingChanges(), true)
})
