import { reactive, toRefs } from 'vue'
import { englishApi } from './api.js'
import { markedWordsFromText } from './passageMarkdown.js'
import {
  applyTranslationToDraft,
  applyWordTranslationsToDraft,
  missingMarkedWords,
  sentenceDraftPayload,
  sentenceToDraft,
  translationSourceKey
} from './sentenceDraft.js'

// Editing belongs to the sentence, independently of the visible page or repeat.
// Keep one reactive draft so an in-flight save/translation sees subsequent edits.
export function createSentenceEditor({ updateSentenceInList, onSaved }) {
  const entries = new Map()
  const draftKey = draft => JSON.stringify(draft)
  const isDirty = entry => draftKey(entry.ui.editDraft) !== entry.savedKey

  function entryFor(sentence) {
    const id = Number(sentence.id)
    let entry = entries.get(id)
    if (!entry) {
      const editDraft = sentenceToDraft(sentence)
      entry = {
        savedKey: draftKey(editDraft),
        ui: reactive({ editDraft, showEditor: false, saving: false, translating: false, message: '' })
      }
      entries.set(id, entry)
    }
    return entry
  }

  function uiFields(sentence) {
    const entry = entryFor(sentence)
    if (!isDirty(entry) && !entry.ui.saving && !entry.ui.translating) {
      entry.ui.editDraft = sentenceToDraft(sentence)
      entry.savedKey = draftKey(entry.ui.editDraft)
    }
    return toRefs(entry.ui)
  }

  function toggleEditor(sentence) {
    const { ui } = entryFor(sentence)
    ui.showEditor = !ui.showEditor
    ui.message = ''
  }

  async function translateSentenceDraft(sentence) {
    if (!sentence) return
    const { ui } = entryFor(sentence)
    if (ui.translating) return
    const editDraft = ui.editDraft
    const text = String(editDraft?.text || '').trim()
    if (!text) return
    const expectedDraft = draftKey(editDraft)
    ui.translating = true
    ui.message = ''
    try {
      const words = markedWordsFromText(text).map(item => item.word)
      const sourceUnchanged = (
        translationSourceKey(text) === translationSourceKey(sentence.text)
        && Boolean(String(editDraft?.sentenceTranslation || '').trim())
      )
      const missingWords = missingMarkedWords(editDraft, { includeMissingEnglish: true })
      if (sourceUnchanged && !missingWords.length) {
        ui.message = '整句译文和重点词中英文释义均已存在'
        return
      }
      const wordsOnly = sourceUnchanged && missingWords.length > 0
      const result = wordsOnly
        ? await englishApi.translateWords({ text, words: missingWords, sentence_id: sentence.id, sentence_translation: editDraft.sentenceTranslation })
        : await englishApi.translateText({ text, words, sentence_id: sentence.id })
      if (draftKey(ui.editDraft) !== expectedDraft) {
        ui.message = '内容已修改，已忽略旧翻译结果'
        return
      }
      ui.editDraft = wordsOnly
        ? applyWordTranslationsToDraft(ui.editDraft, result)
        : applyTranslationToDraft(ui.editDraft, result)
      ui.message = wordsOnly
        ? `已补充 ${missingWords.length} 个重点词释义（含英文解释），保存后生效`
        : '已生成翻译，保存后生效'
    } catch (err) {
      ui.message = err?.message || '生成翻译失败'
    } finally {
      ui.translating = false
    }
  }

  async function saveSentence(sentence) {
    if (!sentence) return
    const entry = entryFor(sentence)
    const { ui } = entry
    if (ui.saving) return
    const expectedDraft = draftKey(ui.editDraft)
    const payload = sentenceDraftPayload(ui.editDraft)
    ui.saving = true
    ui.message = ''
    try {
      const updated = await englishApi.updateSentence(sentence.id, payload)
      const fresh = updateSentenceInList(updated, sentence)
      const savedDraft = sentenceToDraft(updated)
      entry.savedKey = draftKey(savedDraft)
      if (draftKey(ui.editDraft) !== expectedDraft) {
        ui.showEditor = true
        ui.message = '请求中的版本已保存，当前修改仍待保存'
      } else {
        ui.editDraft = savedDraft
        ui.showEditor = false
        onSaved(fresh)
      }
      return fresh
    } catch (err) {
      ui.message = err?.message || '保存失败'
      return undefined
    } finally {
      ui.saving = false
    }
  }

  return {
    uiFields,
    toggleEditor,
    translateSentenceDraft,
    saveSentence,
    hasPendingChanges: () => [...entries.values()].some(entry => isDirty(entry) || entry.ui.saving || entry.ui.translating),
    forget: sentenceId => entries.delete(Number(sentenceId))
  }
}
