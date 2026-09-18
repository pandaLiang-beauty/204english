import { computed, reactive, ref } from 'vue'
import { englishApi } from './api.js'
import { createReviewEventQueue } from './createReviewEventQueue.js'
import { createSentenceEditor } from './createSentenceEditor.js'
import { mergeSentenceUpdate } from './mergeSentenceUpdate.js'
import { mergeReviewRoundState } from './reviewRoundState.js'
import { markedWordsFromText } from './passageMarkdown.js'
import {
  applyTranslationToDraft,
  emptySentenceDraft,
  sentenceDraftPayload,
  splitBulkSentences
} from './sentenceDraft.js'
import { sentenceInstanceKey } from './sentencePresentation.js'

export function useEnglishSentenceList(context = {}) {
  const sentences = ref([])
  const stats = ref({})
  const heatmap = ref(null)
  const error = ref('')
  const loading = ref(false)
  const saving = ref(false)
  const translatingDraft = ref(false)
  const page = ref(1)
  const pageSize = ref(20)
  const pageSizeOptions = [10, 20, 40, 80]
  const total = ref(0)
  const searchInput = ref('')
  const appliedSearch = ref('')
  const sort = ref('smart')
  const createOpen = ref(false)
  const draft = ref(emptySentenceDraft())
  const bulkText = ref('')
  const bulkLoading = ref(false)
  const bulkMessage = ref('')
  const reviewRound = ref(null)
  const roundInitialized = ref(false)
  const translationRefreshTimers = new Map()
  let roundBoundaryTimer = null
  let loadGeneration = 0
  let activityGeneration = 0
  let disposed = false
  const modeKey = () => [context.isReview?.(), context.isStats?.(), context.isPassages?.(), context.isCreate?.()].join(':')

  const pageCount = computed(() => Math.max(1, Math.ceil(total.value / Number(pageSize.value || 20))))
  const weakNetworkWords = computed(() => stats.value?.word_network?.weak_words || [])
  const legacyReviewTotal = computed(() => heatmap.value?.legacy_total_reviews ?? stats.value?.legacy?.total_reviews ?? 0)
  const heatmapDays = computed(() => heatmap.value?.days || [])
  const heatmapCells = computed(() => {
    const days = heatmapDays.value
    if (!days.length) return []
    const leading = Number(days[0]?.weekday || 0)
    return [...Array.from({ length: leading }, () => null), ...days]
  })
  const heatmapColumns = computed(() => Math.max(1, Math.ceil(heatmapCells.value.length / 7)))
  const bulkSentences = computed(() => splitBulkSentences(bulkText.value))

  function needsGeneratedTranslation(sentence) {
    if (sentence?.translation_pending) return true
    if (!String(sentence?.sentence_translation || '').trim()) return true
    return Object.values(sentence?.word_translations || {}).some(value => !String(value || '').trim())
  }

  function clearTranslationRefresh(sentenceId) {
    if (typeof window === 'undefined') return
    const timer = translationRefreshTimers.get(Number(sentenceId))
    if (timer) window.clearTimeout(timer)
    translationRefreshTimers.delete(Number(sentenceId))
  }

  function scheduleTranslationRefresh(sentenceId, expectedText, attempt = 0) {
    if (typeof window === 'undefined') return
    const delays = [15000, 20000, 30000, 45000]
    if (attempt >= delays.length) return
    const id = Number(sentenceId)
    clearTranslationRefresh(id)
    const timer = window.setTimeout(async () => {
      translationRefreshTimers.delete(id)
      const current = sentences.value.find(item => Number(item.id) === id)
      if (!current || String(current.text || '') !== String(expectedText || '')) return
      try {
        const updated = await englishApi.sentence(id)
        if (String(updated?.text || '') !== String(expectedText || '')) return
        const decorated = updateSentenceInList(updated, current)
        if (!needsGeneratedTranslation(decorated)) {
          decorated.ui.message = '翻译已自动更新'
          audioControls().scheduleAudioStatusRefresh?.(12000)
          return
        }
        if (attempt + 1 < delays.length) {
          decorated.ui.message = '已保存，正在自动翻译'
          scheduleTranslationRefresh(id, expectedText, attempt + 1)
        } else {
          decorated.ui.message = '自动翻译尚未完成，可点生成翻译重试'
        }
      } catch (err) {
        if (attempt + 1 < delays.length) {
          scheduleTranslationRefresh(id, expectedText, attempt + 1)
        } else if (current?.ui) {
          current.ui.message = err?.message || '自动翻译状态刷新失败'
        }
      }
    }, delays[attempt])
    translationRefreshTimers.set(id, timer)
  }

  function createUiState(sentence, previous = {}) {
    const previousUi = previous.ui || {}
    const sentenceAudioChanged = Boolean(previous.id && previous.audio_url !== sentence?.audio_url)
    if (sentenceAudioChanged && typeof URL !== 'undefined') {
      if (previousUi.cachedAudioUrl) URL.revokeObjectURL(previousUi.cachedAudioUrl)
      if (previousUi.pendingCachedAudioUrl) URL.revokeObjectURL(previousUi.pendingCachedAudioUrl)
    }
    return reactive({
      ...sentenceEditor.uiFields(sentence),
      showTranslation: Boolean(previousUi.showTranslation),
      status: previousUi.status || '',
      audioVoiceSaving: false,
      reviewing: Boolean(previousUi.reviewing),
      reviewPending: Number(previousUi.reviewPending || 0),
      wordPlaying: '',
      audioPlaying: Boolean(previousUi.audioPlaying),
      cachedAudioUrl: sentenceAudioChanged ? '' : (previousUi.cachedAudioUrl || ''),
      pendingCachedAudioUrl: sentenceAudioChanged ? '' : (previousUi.pendingCachedAudioUrl || ''),
      wordAudioCache: previousUi.wordAudioCache || {},
      audioPreloadPromise: null
    })
  }

  function decorateSentenceRecord(item, previous = {}) {
    return {
      ...item,
      word_translations: item.word_translations || {},
      word_tips: item.word_tips || {},
      word_play_counts: item.word_play_counts || {},
      sentence_segments: item.sentence_segments || [],
      translation_segments: item.translation_segments || [],
      pronunciations: item.pronunciations || {},
      word_network: item.word_network || previous.word_network || item.algorithm?.word_network || {},
      ui: createUiState(item, previous)
    }
  }

  function heatCellClass(day, size = 'normal') {
    const base = `${size === 'large' ? 'h-3.5 w-3.5' : 'h-3 w-3'} rounded-[3px] border`
    if (!day) return `${base} border-transparent`
    const count = Number(day.total || 0)
    const max = Number(heatmap.value?.max_count || 0)
    if (count <= 0 || max <= 0) return `${base} border-border bg-surface`
    const ratio = count / max
    if (ratio >= 0.75) return `${base} border-primary bg-primary`
    if (ratio >= 0.45) return `${base} border-primary/70 bg-primary/70`
    if (ratio >= 0.2) return `${base} border-primary/40 bg-primary/40`
    return `${base} border-primary/20 bg-primary/20`
  }

  function heatCellTitle(day) {
    if (!day) return ''
    return `${day.date} · ${day.total || 0} 次 · 整句 ${day.sentence_reviews || 0} · 单词 ${day.word_reviews || 0}`
  }

  function audioControls() {
    return context.audioControls?.() || {}
  }

  function clearRoundBoundaryTimer() {
    if (typeof window !== 'undefined' && roundBoundaryTimer !== null) {
      window.clearTimeout(roundBoundaryTimer)
    }
    roundBoundaryTimer = null
  }

  function scheduleRoundBoundaryRefresh() {
    clearRoundBoundaryTimer()
    if (typeof window === 'undefined' || !context.isReview?.() || !reviewRound.value) return
    const targetText = reviewRound.value.is_completed
      ? reviewRound.value.next_round_at
      : reviewRound.value.expires_at
    const target = Date.parse(String(targetText || ''))
    if (!Number.isFinite(target)) return
    const delay = Math.max(250, target - Date.now() + 250)
    roundBoundaryTimer = window.setTimeout(async () => {
      roundBoundaryTimer = null
      if (!context.isReview?.()) return
      roundInitialized.value = false
      await load({ resumeRound: true })
    }, Math.min(delay, 2147483647))
  }

  async function fetchActivity({ includeHeatmap = false, isCurrent = () => true } = {}) {
    const generation = ++activityGeneration
    const mode = modeKey()
    const [statsResult, heatmapResult] = await Promise.all([
      englishApi.stats({ includeWordNetwork: !context.isReview?.() }),
      includeHeatmap ? englishApi.heatmap({ days: 119 }) : null
    ])
    if (disposed || generation !== activityGeneration || mode !== modeKey() || !isCurrent()) return
    stats.value = statsResult
    if (includeHeatmap) heatmap.value = heatmapResult
  }

  async function load(options = {}) {
    if (disposed) return
    const generation = ++loadGeneration
    const mode = modeKey()
    const isCurrent = () => !disposed && generation === loadGeneration && mode === modeKey()
    loading.value = true
    error.value = ''
    try {
      if (context.isPassages?.()) {
        audioControls().disposeSentenceCaches?.(sentences.value)
        sentences.value = []
        await context.loadPassages?.()
        return
      }

      if (context.isStats?.()) {
        await fetchActivity({ includeHeatmap: true, isCurrent })
        if (!isCurrent()) return
        audioControls().disposeSentenceCaches?.(sentences.value)
        sentences.value = []
        return
      }

      const usesRoundQueue = Boolean(
        context.isReview?.()
        && sort.value === 'smart'
        && !appliedSearch.value
      )
      const shouldResumeRound = Boolean(
        usesRoundQueue
        && (options.resumeRound || !roundInitialized.value)
      )
      const sentenceParams = (
        context.isCreate?.()
          ? { page: 1, pageSize: 10, sort: 'latest' }
          : {
              page: page.value,
              pageSize: Number(pageSize.value || 20),
              search: appliedSearch.value,
              sort: sort.value,
              roundQueue: usesRoundQueue,
              resume: shouldResumeRound
            }
      )
      // Statistics do not own list totals or pagination.
      const [, firstPage] = await Promise.all([
        fetchActivity({ isCurrent }),
        englishApi.sentences(sentenceParams)
      ])
      if (!isCurrent()) return
      let data = firstPage
      const visibleItems = result => usesRoundQueue && result.review_round
        ? (result.items || []).filter(item => !item.review_round_item_completed
          && !sentences.value.find(current => sentenceInstanceKey(current) === sentenceInstanceKey(item))?.review_round_item_completed)
        : (result.items || [])

      const resumePage = Number(data.review_round?.resume_page || 0)
      const loadedPage = Number(data.page || page.value || 1)
      if (
        usesRoundQueue
        && !visibleItems(data).length
        && Number(data.review_round?.remaining || 0) > 0
        && resumePage > 0
        && resumePage !== loadedPage
      ) {
        data = await englishApi.sentences({
          ...sentenceParams,
          page: resumePage,
          resume: false
        })
        if (!isCurrent()) return
      }

      const previousByKey = new Map(sentences.value.map(sentence => [sentenceInstanceKey(sentence), sentence]))
      const nextItems = visibleItems(data).map(item => {
        const previous = previousByKey.get(sentenceInstanceKey(item)) || {}
        return decorateSentenceRecord(mergeSentenceUpdate(previous, item), previous)
      }).filter(item => !usesRoundQueue || !data.review_round || !item.review_round_item_completed)
      const nextKeys = new Set(nextItems.map(sentenceInstanceKey))
      sentences.value.forEach(sentence => {
        if (!nextKeys.has(sentenceInstanceKey(sentence))) audioControls().disposeSentenceCaches?.([sentence])
      })
      sentences.value = nextItems
      total.value = data.total ?? nextItems.length
      page.value = Number(data.page || page.value || 1)
      reviewRound.value = mergeReviewRoundState(reviewRound.value, data.review_round)
      if (data.review_round) roundInitialized.value = true
      scheduleRoundBoundaryRefresh()
      context.onSentencesLoaded?.(nextItems, data.review_round || null)
      audioControls().resetPreloadWindow?.()
      if (!context.isCreate?.()) audioControls().schedulePreloadWindow?.(0)
    } catch (err) {
      if (isCurrent()) error.value = err?.message || '英语数据加载失败'
    } finally {
      if (isCurrent()) loading.value = false
    }
  }

  async function refreshActivity() {
    if (context.isPassages?.()) return true
    try {
      await fetchActivity({ includeHeatmap: Boolean(context.isStats?.()) })
      return true
    } catch (_err) {
      return false
    }
  }

  async function reloadFirstPage() {
    page.value = 1
    await load()
  }

  async function applySearch() {
    appliedSearch.value = searchInput.value.trim()
    await reloadFirstPage()
  }

  async function prevPage() {
    if (page.value <= 1) return
    page.value -= 1
    await load()
  }

  async function nextPage() {
    if (page.value >= pageCount.value) return
    page.value += 1
    await load()
  }

  async function createSentence() {
    saving.value = true
    error.value = ''
    try {
      await englishApi.createSentence(sentenceDraftPayload(draft.value))
      draft.value = emptySentenceDraft()
      createOpen.value = false
      await reloadFirstPage()
      audioControls().scheduleAudioStatusRefresh?.()
    } catch (err) {
      error.value = err?.message || '创建句子失败'
    } finally {
      saving.value = false
    }
  }

  async function translateDraft() {
    const text = String(draft.value.text || '').trim()
    if (!text || translatingDraft.value) return
    const expectedDraft = JSON.stringify(draft.value)
    translatingDraft.value = true
    error.value = ''
    try {
      const words = markedWordsFromText(text).map(item => item.word)
      const result = await englishApi.translateText({ text, words })
      if (JSON.stringify(draft.value) !== expectedDraft) return
      draft.value = applyTranslationToDraft(draft.value, result)
    } catch (err) {
      error.value = err?.message || '生成翻译失败'
    } finally {
      translatingDraft.value = false
    }
  }

  function resetBulkImport() {
    bulkText.value = ''
    bulkMessage.value = ''
  }

  async function submitBulkImport() {
    const items = bulkSentences.value
    if (!items.length) return
    bulkLoading.value = true
    bulkMessage.value = ''
    try {
      const result = await englishApi.createSentencesBulk(items.map(text => ({
          text,
          word_translations: {},
          word_tips: {},
          sentence_translation: '',
          sentence_segments: [],
          translation_segments: []
        })))
      bulkMessage.value = `已新增 ${result.created || 0} 条，复用 ${result.reused || 0} 条`
      bulkText.value = ''
      await reloadFirstPage()
      audioControls().scheduleAudioStatusRefresh?.(45000)
    } catch (err) {
      bulkMessage.value = err?.message || '批量导入失败'
    } finally {
      bulkLoading.value = false
    }
  }

  const sentenceEditor = createSentenceEditor({
    updateSentenceInList,
    onSaved: fresh => {
      const audioNeedsRegeneration = Boolean(fresh.audio_needs_regeneration)
      if (needsGeneratedTranslation(fresh)) {
        fresh.ui.message = audioNeedsRegeneration
          ? '已保存，翻译和音频已进入更新流程'
          : '已保存，正在自动翻译'
        scheduleTranslationRefresh(fresh.id, fresh.text)
      } else {
        fresh.ui.message = audioNeedsRegeneration
          ? '已保存，音频已进入重新生成队列'
          : '已保存'
      }
      if (!context.isReview?.()) audioControls().scheduleAudioStatusRefresh?.()
    }
  })
  const { toggleEditor, translateSentenceDraft, saveSentence } = sentenceEditor

  function hasPendingChanges() {
    return sentenceEditor.hasPendingChanges()
      || JSON.stringify(draft.value) !== JSON.stringify(emptySentenceDraft())
      || Boolean(bulkText.value.trim()) || saving.value || bulkLoading.value || translatingDraft.value
  }

  async function deleteSentence(sentence) {
    if (!window.confirm(`确认删除句子 #${sentence.id} 吗？`)) return
    clearTranslationRefresh(sentence.id)
    sentence.ui.message = ''
    try {
      await englishApi.deleteSentence(sentence.id)
      sentenceEditor.forget(sentence.id)
      audioControls().disposeSentenceCaches?.([sentence])
      await load()
    } catch (err) {
      sentence.ui.message = err?.message || '删除失败'
    }
  }

  function updateSentenceInList(updated, previous, { scope } = {}) {
    const targetKey = sentenceInstanceKey(previous || updated)
    const index = sentences.value.findIndex(item => sentenceInstanceKey(item) === targetKey)
    const old = sentences.value[index] || previous || {}
    const merged = mergeSentenceUpdate(old, updated, scope)
    if (scope && index === -1) return { ...merged, ui: old.ui }
    const decorated = decorateSentenceRecord(merged, old)
    if (index !== -1) sentences.value.splice(index, 1, decorated)
    return decorated
  }

  function handleReviewRoundExpired() {
    roundInitialized.value = false
    return reloadFirstPage()
  }

  function handleReviewRoundCompleted(updated) {
    roundInitialized.value = false
    if (!reviewRound.value) return
    reviewRound.value = {
      ...reviewRound.value,
      is_completed: true,
      next_round_at: updated.review_round_next_at || reviewRound.value.next_round_at
    }
    scheduleRoundBoundaryRefresh()
  }

  const { markReviewed } = createReviewEventQueue({
    sentences,
    reviewRound,
    updateSentenceInList,
    refreshActivity,
    audioControls,
    onRoundExpired: handleReviewRoundExpired,
    onRoundCompleted: handleReviewRoundCompleted
  })
  function resetForModeChange() {
    loadGeneration += 1
    activityGeneration += 1
    loading.value = false
    clearRoundBoundaryTimer()
    if (typeof window !== 'undefined') {
      translationRefreshTimers.forEach(timer => window.clearTimeout(timer))
      translationRefreshTimers.clear()
    }
    page.value = 1
    roundInitialized.value = false
    reviewRound.value = null
    createOpen.value = false
    error.value = ''
  }

  function dispose() {
    resetForModeChange()
    disposed = true
  }

  return {
    sentences,
    stats,
    heatmap,
    error,
    loading,
    saving,
    translatingDraft,
    page,
    pageSize,
    pageSizeOptions,
    total,
    searchInput,
    appliedSearch,
    sort,
    createOpen,
    draft,
    bulkText,
    bulkLoading,
    bulkMessage,
    reviewRound,
    pageCount,
    weakNetworkWords,
    legacyReviewTotal,
    heatmapCells,
    heatmapColumns,
    bulkSentences,
    heatCellClass,
    heatCellTitle,
    load,
    refreshActivity,
    reloadFirstPage,
    applySearch,
    prevPage,
    nextPage,
    createSentence,
    translateDraft,
    resetBulkImport,
    submitBulkImport,
    toggleEditor,
    translateSentenceDraft,
    saveSentence,
    deleteSentence,
    updateSentenceInList,
    markReviewed,
    hasPendingChanges,
    resetForModeChange,
    dispose
  }
}
