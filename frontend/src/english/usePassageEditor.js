import { computed, getCurrentInstance, nextTick, onBeforeUnmount, ref } from 'vue'
import { englishApi } from './api.js'
import { emptyPassageForm, passageToForm, payloadFromPassageForm, passageTitle, passageStatusLabel, examTypeLabel, passageTypeLabel, passageActionLabel } from './passagePresentation.js'
import {
  editableElementToMarkdown,
  passageCandidates,
  passageTextToHtml
} from './passageMarkdown.js'

export function usePassageEditor(callbacks = {}) {
  const passages = ref([])
  const todayPassage = ref(null)
  const todayPassages = ref([])
  const activePassage = ref(null)
  const passageTotal = ref(0)
  const passageLoading = ref(false)
  const passageSaving = ref(false)
  const passageAutosaving = ref(false)
  const passageSyncing = ref(false)
  const passageCompleting = ref(false)
  const passageMessage = ref('')
  const passageError = ref('')
  // 同步结果的就地回显。passageMessage 渲染在 main 列顶端，离底部那个同步按钮太远，
  // 点完看不见；这个专供「标注句子」卡片自己显示。
  const passageSyncMessage = ref('')
  const selectedCandidateIndexes = ref([])
  const passageTypeFilter = ref('')
  const passageExamFilter = ref('')
  const passageYearFilter = ref('')
  const passageSearchInput = ref('')
  const passageSearch = ref('')
  const passagePage = ref(1)
  const passagePageSize = 20
  const passagePageCount = computed(() => Math.max(1, Math.ceil(passageTotal.value / passagePageSize)))
  const passageTypeFilters = [
    { value: '', label: '全部' },
    { value: 'reading_a', label: '阅读' },
    { value: 'cloze', label: '完形' },
    { value: 'reading_b', label: '新题型' },
    { value: 'translation', label: '翻译' },
    { value: 'custom', label: '自建' }
  ]
  const passageForm = ref(emptyPassageForm())
  const passageEditorOpen = ref(false)
  const activePassagePanel = ref(null)
  const passageAnnotator = ref(null)
  const passageAnnotatorHtml = ref('')
  const passageDirty = ref(false)
  let passageAutosaveTimer = null
  let passageAutosavePromise = null
  let passageAnnotationSavePromise = null
  let passageEditRevision = 0

  function clearPassageAutosaveTimer() {
    if (passageAutosaveTimer !== null) window.clearTimeout(passageAutosaveTimer)
    passageAutosaveTimer = null
  }

  function schedulePassageAutosave() {
    if (!activePassage.value || typeof window === 'undefined') return
    clearPassageAutosaveTimer()
    passageAutosaveTimer = window.setTimeout(() => {
      passageAutosaveTimer = null
      void persistPassageAutosave()
    }, 900)
  }

  function markPassageDirty() {
    passageDirty.value = true
    passageEditRevision += 1
    schedulePassageAutosave()
  }

  function handlePassageFormInput(options = {}) {
    if (options.bodyText) refreshPassageAnnotator(passageForm.value.bodyText)
    markPassageDirty()
  }

  function refreshPassageAnnotator(text) {
    passageAnnotatorHtml.value = passageTextToHtml(text)
  }

  function passageAnnotatorMarkdown() {
    const el = passageAnnotator.value
    if (!el) return String(passageForm.value.bodyText || '').trim()
    return editableElementToMarkdown(el)
  }

  function syncPassageAnnotatorToForm() {
    const bodyText = passageAnnotatorMarkdown()
    passageForm.value = { ...passageForm.value, bodyText }
    if (activePassage.value) {
      activePassage.value = { ...activePassage.value, body_text: bodyText }
      selectedCandidateIndexes.value = passageCandidates(activePassage.value).map((_, index) => index)
    }
  }

  function selectionInsidePassageAnnotator() {
    const el = passageAnnotator.value
    if (!el || typeof window === 'undefined') return false
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return false
    return el.contains(selection.anchorNode) && el.contains(selection.focusNode)
  }

  function togglePassageBold() {
    const el = passageAnnotator.value
    if (!el || !selectionInsidePassageAnnotator()) return
    el.focus()
    document.execCommand('bold', false)
    syncPassageAnnotatorToForm()
    markPassageDirty()
  }

  function handlePassageAnnotatorInput() {
    syncPassageAnnotatorToForm()
    markPassageDirty()
  }

  function handlePassageAnnotatorKeydown(event) {
    const key = String(event.key || '').toLowerCase()
    const command = event.ctrlKey || event.metaKey
    if (!command || !['b', 's'].includes(key)) return
    event.preventDefault()
    if (event.repeat || event.isComposing) return
    if (key === 'b') togglePassageBold()
    if (key === 's') void savePassageAnnotations()
  }

  function handlePassageAnnotatorPaste(event) {
    event.preventDefault()
    const text = event.clipboardData?.getData('text/plain') || ''
    document.execCommand('insertText', false, text)
    syncPassageAnnotatorToForm()
    markPassageDirty()
  }

  function updatePassageRecords(updated, options = {}) {
    if (!updated) return
    const index = passages.value.findIndex(item => item.id === updated.id)
    if (index >= 0) passages.value.splice(index, 1, updated)
    else passages.value.unshift(updated)
    const todayIndex = todayPassages.value.findIndex(item => item.id === updated.id)
    if (todayIndex >= 0) todayPassages.value.splice(todayIndex, 1, updated)
    if (todayPassage.value?.id === updated.id) todayPassage.value = updated
    if (!options.preserveActive && activePassage.value?.id === updated.id) activePassage.value = updated
  }

  async function persistPassageAutosave() {
    clearPassageAutosaveTimer()
    if (!activePassage.value || !passageDirty.value) return true
    if (passageAutosavePromise) return passageAutosavePromise
    syncPassageAnnotatorToForm()
    const passageId = Number(activePassage.value.id)
    const revision = passageEditRevision
    const payload = payloadFromPassageForm({
      ...passageForm.value,
      status: activePassage.value.status === 'done' ? 'done' : 'reading'
    })
    const expectedPayload = JSON.stringify(payload)
    passageAutosaving.value = true
    passageAutosavePromise = (async () => {
      let succeeded = false
      try {
        const saved = await englishApi.updatePassage(passageId, payload)
        succeeded = true
        const currentPayload = payloadFromPassageForm({
          ...passageForm.value,
          status: activePassage.value?.status === 'done' ? 'done' : 'reading'
        })
        const unchanged = passageEditRevision === revision && JSON.stringify(currentPayload) === expectedPayload
        updatePassageRecords(saved, { preserveActive: !unchanged })
        if (Number(activePassage.value?.id) === passageId) {
          if (unchanged) {
            activePassage.value = {
              ...saved,
              body_text: passageForm.value.bodyText
            }
            passageForm.value = {
              ...passageForm.value,
              status: saved.status || passageForm.value.status
            }
            passageDirty.value = false
          } else {
            activePassage.value = {
              ...activePassage.value,
              ...currentPayload,
              id: passageId
            }
            passageDirty.value = true
          }
        }
        return true
      } catch (err) {
        passageError.value = err?.message || '自动保存标注失败'
        return false
      } finally {
        passageAutosavePromise = null
        passageAutosaving.value = false
        if (succeeded && passageDirty.value) schedulePassageAutosave()
      }
    })()
    return passageAutosavePromise
  }

  async function flushPassageAutosave() {
    clearPassageAutosaveTimer()
    if (passageAutosavePromise) await passageAutosavePromise
    if (!passageDirty.value) return true
    if (activePassage.value) {
      while (passageDirty.value) {
        if (!await persistPassageAutosave()) return false
      }
      return true
    }
    passageError.value = '新文章尚未保存'
    if (typeof window !== 'undefined' && window.confirm('新文章尚未保存，确定放弃这些内容吗？')) {
      passageDirty.value = false
      return true
    }
    return false
  }

  async function loadPassages(options = {}) {
    if (!options.skipAutosave && passageDirty.value && !await flushPassageAutosave()) return
    passageLoading.value = true
    passageError.value = ''
    try {
      const data = await englishApi.passages({
        page: passagePage.value,
        pageSize: passagePageSize,
        passageType: passageTypeFilter.value,
        examType: passageExamFilter.value,
        year: passageYearFilter.value,
        search: passageSearch.value
      })
      passages.value = data.items || []
      todayPassages.value = data.today_items?.length ? data.today_items : (data.today ? [data.today] : [])
      todayPassage.value = todayPassages.value[0] || null
      passageTotal.value = Number(data.total || passages.value.length || 0)

      const activeId = options.activeId || activePassage.value?.id || todayPassage.value?.id || passages.value[0]?.id
      const nextActive = passages.value.find(item => item.id === activeId) || todayPassage.value || passages.value[0] || null
      if (nextActive) {
        await selectPassage(nextActive, { keepMessage: true, skipAutosave: true })
      } else if (!passageForm.value.id) {
        activePassage.value = null
      }
    } catch (err) {
      passageError.value = err?.message || '阅读文章加载失败'
    } finally {
      passageLoading.value = false
    }
  }

  async function setPassageTypeFilter(value) {
    if (!await flushPassageAutosave()) return
    passageTypeFilter.value = value || ''
    passagePage.value = 1
    await loadPassages()
  }

  async function applyPassageFilters() {
    if (!await flushPassageAutosave()) return
    passageSearch.value = passageSearchInput.value.trim()
    passagePage.value = 1
    await loadPassages()
  }

  async function changePassagePage(delta) {
    if (!await flushPassageAutosave()) return
    const next = Math.max(1, Math.min(passagePage.value + delta, passagePageCount.value))
    if (next === passagePage.value) return
    passagePage.value = next
    await loadPassages()
  }

  async function resetPassageForm() {
    if (!await flushPassageAutosave()) return
    activePassage.value = null
    passageForm.value = emptyPassageForm()
    refreshPassageAnnotator('')
    passageEditorOpen.value = true
    passageDirty.value = false
    selectedCandidateIndexes.value = []
    passageMessage.value = ''
    passageError.value = ''
  }

  function applySelectedPassage(passage, options = {}) {
    activePassage.value = passage
    passageForm.value = passageToForm(passage)
    refreshPassageAnnotator(passage?.body_text || '')
    passageEditorOpen.value = false
    passageDirty.value = false
    selectedCandidateIndexes.value = passageCandidates(passage).map((_, index) => index)
    if (!options.keepMessage) {
      passageMessage.value = ''
      passageError.value = ''
    }
  }

  async function selectPassage(passage, options = {}) {
    if (!passage) return false
    if (!options.skipAutosave && Number(activePassage.value?.id) === Number(passage.id) && passageDirty.value) return true
    if (!options.skipAutosave && Number(activePassage.value?.id) !== Number(passage.id)) {
      if (!await flushPassageAutosave()) return false
    }
    applySelectedPassage(passage, options)
    return true
  }

  async function startPassage(passage) {
    if (!passage) return
    if (!await selectPassage(passage)) return
    passageMessage.value = '已打开文章'
    await nextTick()
    activePassagePanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function replacePassage(updated) {
    if (!updated) return
    updatePassageRecords(updated)
    if (todayPassage.value?.id === updated.id || updated.status !== 'done') {
      todayPassage.value = updated.status === 'done' ? todayPassage.value : updated
    }
    applySelectedPassage(updated, { keepMessage: true })
    passageDirty.value = false
  }

  async function savePassage(options = {}) {
    if (passageSaving.value) return null
    const passageId = passageForm.value.id
    const revision = passageEditRevision
    const payload = payloadFromPassageForm(passageForm.value)
    const expectedPayload = JSON.stringify(payload)
    passageSaving.value = true
    if (!options.keepMessage) passageMessage.value = ''
    passageError.value = ''
    try {
      const saved = passageId
        ? await englishApi.updatePassage(passageId, payload)
        : await englishApi.createPassage(payload)
      const sameTarget = passageId
        ? Number(passageForm.value.id) === Number(passageId)
        : !passageForm.value.id
      const currentPayload = payloadFromPassageForm(passageForm.value)
      const unchanged = sameTarget
        && passageEditRevision === revision
        && JSON.stringify(currentPayload) === expectedPayload
      if (!unchanged) {
        updatePassageRecords(saved, { preserveActive: true })
        if (sameTarget) {
          passageForm.value = { ...passageForm.value, id: saved.id }
          activePassage.value = {
            ...(activePassage.value || saved),
            ...currentPayload,
            id: saved.id
          }
          markPassageDirty()
          passageMessage.value = '请求中的版本已保存，当前修改仍待保存'
        }
        return saved
      }
      replacePassage(saved)
      passageMessage.value = options.successMessage || '文章已保存'
      await loadPassages({ activeId: saved.id })
      return saved
    } catch (err) {
      passageError.value = err?.message || '保存阅读文章失败'
      return null
    } finally {
      passageSaving.value = false
    }
  }

  async function savePassageAnnotations(options = {}) {
    if (!activePassage.value && !passageForm.value.bodyText.trim()) return
    if (passageAnnotationSavePromise) return passageAnnotationSavePromise
    const pendingSave = (async () => {
      clearPassageAutosaveTimer()
      if (passageAutosavePromise) await passageAutosavePromise
      clearPassageAutosaveTimer()
      syncPassageAnnotatorToForm()
      if (activePassage.value?.status !== 'done') {
        passageForm.value = { ...passageForm.value, status: 'reading' }
      }
      const saved = await savePassage({
        keepMessage: options.keepMessage,
        successMessage: options.successMessage || '标注已保存'
      })
      if (!saved || passageDirty.value) return null
      return saved
    })()
    passageAnnotationSavePromise = pendingSave
    try {
      return await pendingSave
    } finally {
      if (passageAnnotationSavePromise === pendingSave) passageAnnotationSavePromise = null
    }
  }

  function actionSnapshot() {
    return { id: Number(activePassage.value.id), revision: passageEditRevision, payload: JSON.stringify(payloadFromPassageForm(passageForm.value)) }
  }

  function mergeActionResult(updated, snapshot, status) {
    if (!updated) return false
    updatePassageRecords(updated, { preserveActive: true })
    if (Number(activePassage.value?.id) !== snapshot.id) return false
    const unchanged = passageEditRevision === snapshot.revision
      && JSON.stringify(payloadFromPassageForm(passageForm.value)) === snapshot.payload
    if (unchanged) replacePassage(updated)
    else {
      if (status) passageForm.value = { ...passageForm.value, status }
      activePassage.value = { ...updated, ...payloadFromPassageForm(passageForm.value), id: snapshot.id }
      markPassageDirty()
    }
    return unchanged
  }

  async function syncSelectedCandidates() {
    if (!activePassage.value || passageSyncing.value || !selectedCandidateIndexes.value.length) return
    const selectedIndexes = [...selectedCandidateIndexes.value]
    if (passageDirty.value) {
      const saved = await savePassageAnnotations({ keepMessage: true, successMessage: '标注已保存' })
      if (!saved) return
      selectedCandidateIndexes.value = selectedIndexes.filter(index => index < passageCandidates(activePassage.value).length)
    }
    passageSyncing.value = true
    passageMessage.value = ''
    passageError.value = ''
    passageSyncMessage.value = ''
    const snapshot = actionSnapshot()
    try {
      const result = await englishApi.syncPassageSentences(snapshot.id, { candidate_indexes: [...selectedCandidateIndexes.value] })
      const unchanged = result?.passage ? mergeActionResult(result.passage, snapshot) : passageEditRevision === snapshot.revision
      if (Number(activePassage.value?.id) !== snapshot.id) return
      passageMessage.value = `已加入句库 ${result?.inserted || 0} 句，已有 ${result?.reused || 0} 句。新句子将在下一轮复习。`
      passageSyncMessage.value = passageMessage.value
      if (unchanged) selectedCandidateIndexes.value = []
      await callbacks.refreshActivity?.()
    } catch (err) {
      if (Number(activePassage.value?.id) !== snapshot.id) return
      passageError.value = err?.message || '加入句库失败，请重试'
      passageSyncMessage.value = passageError.value
    } finally {
      passageSyncing.value = false
    }
  }

  async function completeActivePassage() {
    if (!activePassage.value || passageCompleting.value) return
    if (!await flushPassageAutosave()) return
    passageCompleting.value = true
    passageMessage.value = ''
    passageError.value = ''
    const snapshot = actionSnapshot()
    try {
      const updated = await englishApi.completePassage(snapshot.id)
      mergeActionResult(updated, snapshot, 'done')
      if (Number(activePassage.value?.id) === snapshot.id) passageMessage.value = '已记录，这篇读完了。'
    } catch (err) {
      if (Number(activePassage.value?.id) === snapshot.id) passageError.value = err?.message || '记录失败，请重试'
    } finally {
      passageCompleting.value = false
    }
  }

  async function deleteActivePassage() {
    if (!activePassage.value) return
    if (!window.confirm(`确认删除「${passageTitle(activePassage.value)}」吗？`)) return
    passageMessage.value = ''
    passageError.value = ''
    try {
      await englishApi.deletePassage(activePassage.value.id)
      clearPassageAutosaveTimer()
      passageDirty.value = false
      await resetPassageForm()
      await loadPassages()
    } catch (err) {
      passageError.value = err?.message || '删除阅读文章失败'
    }
  }

  if (getCurrentInstance()) {
    onBeforeUnmount(() => {
      clearPassageAutosaveTimer()
      if (activePassage.value) void flushPassageAutosave()
    })
  }

  return {
    passages,
    todayPassage,
    todayPassages,
    activePassage,
    passageTotal,
    passageLoading,
    passageSaving,
    passageAutosaving,
    passageSyncing,
    passageCompleting,
    passageMessage,
    passageError,
    passageSyncMessage,
    selectedCandidateIndexes,
    passageTypeFilter,
    passageExamFilter,
    passageYearFilter,
    passageSearchInput,
    passagePage,
    passagePageCount,
    passageTypeFilters,
    passageForm,
    passageEditorOpen,
    activePassagePanel,
    passageAnnotator,
    passageAnnotatorHtml,
    passageDirty,
    emptyPassageForm,
    passageTitle,
    passageStatusLabel,
    examTypeLabel,
    passageTypeLabel,
    passageActionLabel,
    handlePassageFormInput,
    togglePassageBold,
    handlePassageAnnotatorInput,
    handlePassageAnnotatorKeydown,
    handlePassageAnnotatorPaste,
    flushPassageAutosave,
    loadPassages,
    setPassageTypeFilter,
    applyPassageFilters,
    changePassagePage,
    resetPassageForm,
    selectPassage,
    startPassage,
    savePassage,
    savePassageAnnotations,
    syncSelectedCandidates,
    completeActivePassage,
    deleteActivePassage
  }
}
