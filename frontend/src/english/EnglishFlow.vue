<template>
  <div class="workspace" :data-view="mode">
      <header class="workspace-header">
        <div class="min-w-0">
          <p class="section-label">{{ modeEyebrow }}</p>
          <h1>{{ pageTitle }}</h1>
          <p class="workspace-description">{{ pageDescription }}</p>
        </div>
        <div class="workspace-actions">
          <span class="workspace-date">{{ todayLabel }}</span>
          <button type="button" class="ui-button ghost" :disabled="loading" aria-label="刷新当前页面" title="刷新当前页面" @click="load({ resumeRound: true })">
            <RefreshCw :class="{ 'animate-spin': loading }" /><span class="refresh-label">刷新</span>
          </button>
        </div>
      </header>
      <p v-if="isStats && error" class="status-message error mb-4" role="alert">{{ error }}</p>
      <EnglishStatsView
        v-if="isStats"
        :stats="stats"
        :heatmap="heatmap"
        :heatmap-cells="heatmapCells"
        :heatmap-columns="heatmapColumns"
        :legacy-review-total="legacyReviewTotal"
        :weak-network-words="weakNetworkWords"
        :heat-cell-class="heatCellClass"
        :heat-cell-title="heatCellTitle"
        :audio-settings="audioSettings"
        :selected-global-voice="selectedGlobalVoice"
        :audio-settings-loading="audioSettingsLoading"
        :audio-settings-saving="audioSettingsSaving"
        :audio-settings-applying="audioSettingsApplying"
        :audio-settings-message="audioSettingsMessage"
        :audio-settings-error="audioSettingsError"
        :preview-loading-voice="previewLoadingVoice"
        :preview-playing-voice="previewPlayingVoice"
        :voice-provider-filter="voiceProviderFilter"
        :audio-voice-groups="audioVoiceGroups"
        :filtered-audio-voice-groups="filteredAudioVoiceGroups"
        :kokoro-voice-count="kokoroVoiceCount"
        :edge-voice-count="edgeVoiceCount"
        :audio-voice-key="audioVoiceKey"
        :audio-voice-option-label="audioVoiceOptionLabel"
        :voice-provider-filter-button-class="voiceProviderFilterButtonClass"
        :global-sentence-audio-identity="globalSentenceAudioIdentity"
        @update:selected-global-voice="selectedGlobalVoice = $event"
        @save-global-audio-settings="saveGlobalAudioSettings"
        @apply-global-audio-settings="applyGlobalAudioSettings"
        @update:voice-provider-filter="voiceProviderFilter = $event"
        @play-voice-preview="playVoicePreview"
      />
      <EnglishPassagesView
        v-else-if="isPassages"
        ref="passagesView"
        :refresh-activity="refreshActivity"
      />
      <EnglishCreateView
        v-else-if="isCreate"
        :stats="stats"
        :total="total"
        :draft="draft"
        :saving="saving"
        :translating-draft="translatingDraft"
        :error="error"
        :bulk-loading="bulkLoading"
        :bulk-text="bulkText"
        :bulk-sentences="bulkSentences"
        :bulk-message="bulkMessage"
        :sentences="sentences"
        :loading="loading"
        @update:draft="draft = $event"
        @translate="translateDraft"
        @submit="createSentence"
        @reset-bulk="resetBulkImport"
        @submit-bulk="submitBulkImport"
        @update:bulk-text="bulkText = $event"
        @clear-bulk-message="bulkMessage = ''"
      />

      <EnglishLibraryView
        v-else-if="isLibrary"
        :sentences="sentences"
        :error="error"
        :loading="loading"
        :page="page"
        :page-count="pageCount"
        :total="total"
        :search-input="searchInput"
        :sort="sort"
        :page-size="pageSize"
        :page-size-options="pageSizeOptions"
        :audio-settings-loading="audioSettingsLoading"
        :audio-voice-groups="audioVoiceGroups"
        :compact-date="compactDate"
        :sentence-audio-status-class="sentenceAudioStatusClass"
        :sentence-audio-status-label="sentenceAudioStatusLabel"
        :sentence-audio-selection="sentenceAudioSelection"
        :global-sentence-audio-identity="globalSentenceAudioIdentity"
        :audio-voice-key="audioVoiceKey"
        :audio-voice-option-label="audioVoiceOptionLabel"
        :toggle-sentence-audio="toggleSentenceAudio"
        :change-sentence-audio-voice="changeSentenceAudioVoice"
        :play-word="playWord"
        :toggle-editor="toggleEditor"
        :delete-sentence="deleteSentence"
        :translate-sentence-draft="translateSentenceDraft"
        :save-sentence="saveSentence"
        :resolve-sentence-audio-src="resolveSentenceAudioSrc"
        :set-sentence-audio-ref="setSentenceAudioRef"
        :handle-sentence-audio-play="handleSentenceAudioPlay"
        :handle-sentence-audio-pause="handleSentenceAudioPause"
        :handle-sentence-audio-ended="handleSentenceAudioEnded"
        :apply-search="applySearch"
        :reload-first-page="reloadFirstPage"
        :prev-page="prevPage"
        :next-page="nextPage"
        @update:search-input="searchInput = $event"
        @update:sort="sort = $event"
        @update:page-size="pageSize = $event"
      />
      <EnglishReviewView
        v-else
        :sentences="sentences"
        :error="error"
        :loading="loading"
        :review-round="reviewRound"
        :stats="stats"
        :active-sentence-index="activeSentenceIndex"
        :page="page"
        :page-count="pageCount"
        :set-sentence-card-ref="setSentenceCardRef"
        :activate-sentence="activateSentence"
        :sentence-audio-status-class="sentenceAudioStatusClass"
        :sentence-audio-status-label="sentenceAudioStatusLabel"
        :toggle-sentence-audio="toggleSentenceAudio"
        :review-sentence-and-next="reviewSentenceAndNext"
        :toggle-editor="toggleEditor"
        :translate-sentence-draft="translateSentenceDraft"
        :save-sentence="saveSentence"
        :play-word="playWord"
        :resolve-sentence-audio-src="resolveSentenceAudioSrc"
        :set-sentence-audio-ref="setSentenceAudioRef"
        :handle-sentence-audio-play="handleSentenceAudioPlay"
        :handle-sentence-audio-pause="handleSentenceAudioPause"
        :handle-sentence-audio-ended="handleSentenceAudioEnded"
        :prev-page="prevPage"
        :next-page="nextPage"
      />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RefreshCw } from '@lucide/vue'
import EnglishCreateView from './views/EnglishCreateView.vue'
import EnglishLibraryView from './views/EnglishLibraryView.vue'
import EnglishPassagesView from './views/EnglishPassagesView.vue'
import EnglishReviewView from './views/EnglishReviewView.vue'
import EnglishStatsView from './views/EnglishStatsView.vue'
import { useEnglishAudio } from './useEnglishAudio'
import { useEnglishAudioSettings } from './useEnglishAudioSettings'
import { useEnglishSentenceList } from './useEnglishSentenceList'
import { useReviewNavigator } from './useReviewNavigator'
import { emptySentenceDraft, sentenceDraftPayload, sentenceToDraft } from './sentenceDraft.js'
const props = defineProps({
  mode: { type: String, default: 'review' }
})


const isLibrary = computed(() => props.mode === 'library')
const isCreate = computed(() => props.mode === 'create')
const isStats = computed(() => props.mode === 'stats')
const isPassages = computed(() => props.mode === 'passages')
const isReview = computed(() => !isLibrary.value && !isCreate.value && !isStats.value && !isPassages.value)
const needsAudioSettings = computed(() => isLibrary.value || isStats.value)
const pageCopy = {
  review: ['DAILY PRACTICE', '句子复习', '连续阅读，随时听音和对照译文。'],
  passages: ['READ IN CONTEXT', '从一篇真题开始', '读文章，标出重点，把值得复习的句子留下来。'],
  library: ['YOUR COLLECTION', '我的句库', '积累下来的每一句，都可以在这里找到。'],
  create: ['ADD TO YOUR COLLECTION', '留下一句值得学习的英文', '手动添加或批量导入，新句子将在下一轮参与复习。'],
  stats: ['YOUR LEARNING JOURNEY', '看见一点一滴的积累', '回顾学习记录，也把阅读和听音调整得更合适。']
}
const modeEyebrow = computed(() => (pageCopy[props.mode] || pageCopy.review)[0])
const pageTitle = computed(() => (pageCopy[props.mode] || pageCopy.review)[1])
const pageDescription = computed(() => (pageCopy[props.mode] || pageCopy.review)[2])
const todayLabel = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())
const passagesView = ref(null)
let audioControls
let reviewNavigator
const keyboardEnabled = computed(() => (
  !isCreate.value
  && !isStats.value
  && !isPassages.value
  && !isLibrary.value
))

const {
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
  sort,
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
  resetForModeChange,
  disposeRoundBoundaryTimer
} = useEnglishSentenceList({
  isCreate: () => isCreate.value,
  isStats: () => isStats.value,
  isPassages: () => isPassages.value,
  isReview: () => isReview.value,
  loadPassages: (...args) => passagesView.value?.loadPassages?.(...args),
  audioControls: () => audioControls,
  onSentencesLoaded: (items, round) => {
    const nextIndex = round ? items.findIndex(item => !item.review_round_item_completed) : 0
    reviewNavigator?.activateSentence(nextIndex >= 0 ? nextIndex : 0)
  }
})

function applyListDefaultsForMode() {
  if (isLibrary.value) {
    sort.value = 'id-desc'
    pageSize.value = 40
  } else if (isReview.value) {
    sort.value = 'smart'
    pageSize.value = 20
  }
}

function hasPendingChanges() {
  return Boolean(passagesView.value?.hasPendingChanges?.()) || changedSentenceEdits().length > 0
    || JSON.stringify(draft.value) !== JSON.stringify(emptySentenceDraft()) || Boolean(bulkText.value.trim())
}

function changedSentenceEdits() {
  return sentences.value.filter(sentence => sentence.ui.showEditor
    && JSON.stringify(sentenceDraftPayload(sentence.ui.editDraft)) !== JSON.stringify(sentenceDraftPayload(sentenceToDraft(sentence))))
}

async function flushPendingChanges({ leavingApp = false } = {}) {
  const changed = changedSentenceEdits()
  const newDraft = JSON.stringify(draft.value) !== JSON.stringify(emptySentenceDraft()) || Boolean(bulkText.value.trim())
  if (changed.length || (leavingApp && newDraft)) {
    if (!window.confirm(leavingApp ? '还有未保存的内容。确定放弃并退出登录吗？' : '句子的修改还没有保存。要放弃修改并离开吗？')) return false
    changed.forEach(sentence => { sentence.ui.showEditor = false; sentence.ui.editDraft = sentenceToDraft(sentence) })
    if (leavingApp) { draft.value = emptySentenceDraft(); bulkText.value = '' }
  }
  return await passagesView.value?.flushPendingChanges?.() ?? true
}

defineExpose({
  flushPendingChanges,
  hasPendingChanges
})

audioControls = useEnglishAudio(sentences, {
  shouldSkipStatusRefresh: () => isReview.value || isPassages.value || isStats.value,
  refreshAudioStatus: () => load(),
  updateSentenceInList,
  refreshActivity,
  markReviewed,
  reloadRound: reloadFirstPage
})

const {
  scheduleAudioStatusRefresh,
  resolveSentenceAudioSrc,
  setSentenceAudioRef,
  toggleSentenceAudio,
  stopAllAudio,
  playWord,
  handleSentenceAudioEnded,
  handleSentenceAudioPlay,
  handleSentenceAudioPause,
  disposeAudioResources
} = audioControls

reviewNavigator = useReviewNavigator({
  sentences,
  page,
  pageCount,
  loading,
  nextPage,
  prevPage,
  markReviewed,
  reloadFirstPage,
  toggleEditor,
  stopAllAudio,
  toggleSentenceAudio,
  playWord,
  isEnabled: () => keyboardEnabled.value
})

const {
  activeSentenceIndex,
  setSentenceCardRef,
  activateSentence,
  reviewSentenceAndNext,
  handleEnglishKeyboard
} = reviewNavigator

const {
  audioSettings,
  selectedGlobalVoice,
  audioSettingsLoading,
  audioSettingsSaving,
  audioSettingsApplying,
  audioSettingsMessage,
  audioSettingsError,
  previewLoadingVoice,
  previewPlayingVoice,
  voiceProviderFilter,
  audioVoiceGroups,
  filteredAudioVoiceGroups,
  kokoroVoiceCount,
  edgeVoiceCount,
  audioVoiceKey,
  loadAudioSettings,
  saveGlobalAudioSettings,
  applyGlobalAudioSettings,
  stopVoicePreview,
  playVoicePreview,
  sentenceAudioSelection,
  changeSentenceAudioVoice,
  compactDate,
  audioVoiceOptionLabel,
  voiceProviderFilterButtonClass,
  globalSentenceAudioIdentity,
  sentenceAudioStatusLabel,
  sentenceAudioStatusClass
} = useEnglishAudioSettings({
  updateSentenceInList,
  scheduleAudioStatusRefresh
})

watch(() => props.mode, async () => {
  stopAllAudio()
  stopVoicePreview()
  resetForModeChange()
  window.scrollTo({ top: 0 })
  activeSentenceIndex.value = 0
  applyListDefaultsForMode()
  const tasks = [load()]
  if (needsAudioSettings.value) tasks.push(loadAudioSettings({ quiet: true }))
  await Promise.all(tasks)
}, { flush: 'post' })

watch(sentences, items => {
  if (!items.length) {
    activeSentenceIndex.value = 0
    return
  }
  if (activeSentenceIndex.value >= items.length) {
    activeSentenceIndex.value = items.length - 1
  }
})

onMounted(() => {
  window.addEventListener('keydown', handleEnglishKeyboard)
  applyListDefaultsForMode()
  load()
  if (needsAudioSettings.value) loadAudioSettings()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleEnglishKeyboard)
  stopVoicePreview()
  disposeRoundBoundaryTimer()
  disposeAudioResources()
})
</script>
