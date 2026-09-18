import assert from 'node:assert/strict'
import test from 'node:test'

import { englishApi } from './api.js'
import { sentenceDraftPayload } from './sentenceDraft.js'
import { useEnglishSentenceList } from './useEnglishSentenceList.js'
import { sentenceRecord } from './testFixtures.js'

test('the existing translation action fills English definitions while preserving saved Chinese', async () => {
  const originals = {
    stats: englishApi.stats,
    sentences: englishApi.sentences,
    translateText: englishApi.translateText,
    translateWords: englishApi.translateWords
  }
  const chinese = '本义：平易近人的；句中：平易近人'
  const initial = {
    ...sentenceRecord(),
    text: 'An **Approachable**, **stylish** and **modern** person.',
    sentence_translation: '一个平易近人、时尚且现代的人。',
    sentence_segments: ['An approachable, stylish and modern person.'],
    translation_segments: ['一个平易近人、时尚且现代的人。'],
    word_translations: {
      Approachable: chinese,
      stylish: '本义：时尚的；句中：时尚的；英文：fashionable and attractive',
      modern: ''
    },
    word_tips: { Approachable: '保留已确认的用法提示' }
  }
  const requests = []
  englishApi.stats = async () => ({ active: 1 })
  englishApi.sentences = async () => ({ items: [initial], total: 1, page: 1 })
  englishApi.translateText = async () => { throw new Error('the confirmed sentence must be preserved') }
  englishApi.translateWords = async payload => {
    requests.push(payload)
    return {
      items: [],
      word_translations: {
        approachable: '本义：容易接近的；句中：好相处的；英文：friendly and easy to talk to',
        modern: '本义：现代的；句中：现代的；英文：of the present time'
      },
      word_tips: { approachable: '新提示不能覆盖已有提示' }
    }
  }

  try {
    const list = useEnglishSentenceList()
    await list.load()
    const sentence = list.sentences.value[0]
    list.toggleEditor(sentence)
    await list.translateSentenceDraft(sentence)

    assert.deepEqual(requests, [{
      text: initial.text,
      words: ['Approachable', 'modern'],
      sentence_id: initial.id,
      sentence_translation: initial.sentence_translation
    }])
    const payload = sentenceDraftPayload(sentence.ui.editDraft)
    assert.deepEqual(Object.keys(payload).sort(), [
      'sentence_segments', 'sentence_translation', 'text', 'translation_segments', 'word_tips', 'word_translations'
    ])
    assert.equal(payload.word_translations.Approachable, chinese + '；英文：friendly and easy to talk to')
    assert.equal(payload.word_translations.stylish, initial.word_translations.stylish)
    assert.equal(payload.word_translations.modern, '本义：现代的；句中：现代的；英文：of the present time')
    assert.equal(payload.sentence_translation, initial.sentence_translation)
    assert.deepEqual(payload.sentence_segments, initial.sentence_segments)
    assert.deepEqual(payload.translation_segments, initial.translation_segments)
    assert.deepEqual(payload.word_tips, initial.word_tips)
    assert.equal(sentence.word_translations.Approachable, chinese, 'changes remain in the draft until saved')

    await list.translateSentenceDraft(sentence)
    assert.equal(requests.length, 1, 'complete bilingual cards should not be regenerated')
    assert.equal(sentence.ui.message, '整句译文和重点词中英文释义均已存在')
  } finally {
    Object.assign(englishApi, originals)
  }
})
