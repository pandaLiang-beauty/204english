<template>
  <div class="h-full overflow-y-auto bg-bg text-text">
    <!-- 页宽在这里统一决定：复习模式收窄到 1320px（保证英文行长好读），其余模式 1500px。
         关键是 header 和下面的卡片共用同一个容器宽度，左右边缘对齐——
         原来 header 是整容器宽、而 <main> 又 max-w-[1040px] mx-auto 居中，
         两者对不上，才出现左侧那一大块不对称的空白。 -->
    <div
      :class="[
        'mx-auto grid min-h-full gap-4 px-3 py-4 md:px-5',
        isReview ? 'max-w-[1320px]' : 'max-w-[1500px]'
      ]"
    >
      <header class="border-b border-border pb-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="text-xs font-medium text-muted">英语 · {{ modeLabel }}</div>
            <h1 class="mt-1 text-xl font-semibold tracking-normal text-text">{{ pageTitle }}</h1>
            <div v-if="isReview" class="mt-2 max-w-2xl">
              <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs tabular-nums text-muted">
                <span v-if="reviewRound">
                  本轮 <span class="font-semibold text-text">{{ reviewRound.completed || 0 }} / {{ reviewRound.total || 0 }}</span>
                </span>
                <span v-if="reviewRound">剩余 {{ reviewRound.remaining || 0 }}</span>
                <span v-if="reviewRoundEndTime">本轮结束 {{ reviewRoundEndTime }}（北京时间）</span>
                <span>今日 {{ stats.today?.reviewed_sentences ?? 0 }} 句</span>
                <span>整句 {{ stats.today?.sentence_reviews ?? 0 }} 次</span>
                <span>单词 {{ stats.today?.word_reviews ?? 0 }} 次</span>
              </div>
              <div v-if="reviewRound" class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div
                  class="h-full rounded-full bg-primary transition-[width] duration-300"
                  :style="{ width: `${reviewRoundProgressPercent}%` }"
                />
              </div>
            </div>
            <div v-if="isLibrary" class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs tabular-nums text-muted">
              <span>{{ stats.active ?? total }} 句</span>
              <span>{{ stats.with_audio ?? 0 }} 条整句音频</span>
              <span>{{ stats.word_network?.cross_sentence_words ?? 0 }} 个跨句关联词</span>
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
              @click="load({ resumeRound: true })"
            >
              <RefreshCw class="h-4 w-4" />
              刷新
            </button>
          </div>
        </div>
      </header>

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
        :create-open="createOpen"
        :draft="draft"
        :saving="saving"
        :translating-draft="translatingDraft"
        :bulk-text="bulkText"
        :bulk-loading="bulkLoading"
        :bulk-sentences="bulkSentences"
        :bulk-message="bulkMessage"
        :audio-settings-loading="audioSettingsLoading"
        :audio-voice-groups="audioVoiceGroups"
        :compact-date="compactDate"
        :sentence-audio-button-class="sentenceAudioButtonClass"
        :sentence-audio-status-class="sentenceAudioStatusClass"
        :sentence-audio-status-label="sentenceAudioStatusLabel"
        :sentence-audio-identity="sentenceAudioIdentity"
        :word-audio-identity="wordAudioIdentity"
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
        :translate-draft="translateDraft"
        :create-sentence="createSentence"
        :reset-bulk-import="resetBulkImport"
        :submit-bulk-import="submitBulkImport"
        @update:search-input="searchInput = $event"
        @update:sort="sort = $event"
        @update:page-size="pageSize = $event"
        @update:create-open="createOpen = $event"
        @update:draft="draft = $event"
        @update:bulk-text="bulkText = $event"
        @clear-bulk-message="bulkMessage = ''"
      />
      <EnglishReviewView
        v-else
        :sentences="sentences"
        :error="error"
        :loading="loading"
        :review-round="reviewRound"
        :active-sentence-index="activeSentenceIndex"
        :keyboard-enabled="keyboardEnabled"
        :page="page"
        :page-count="pageCount"
        :set-sentence-card-ref="setSentenceCardRef"
        :sentence-card-class="sentenceCardClass"
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
const props = defineProps({
  mode: { type: String, default: 'review' }
})


const isLibrary = computed(() => props.mode === 'library')
const isCreate = computed(() => props.mode === 'create')
const isStats = computed(() => props.mode === 'stats')
const isPassages = computed(() => props.mode === 'passages')
const isReview = computed(() => !isLibrary.value && !isCreate.value && !isStats.value && !isPassages.value)
const needsAudioSettings = computed(() => isLibrary.value || isStats.value)
const modeLabel = computed(() => {
  if (isPassages.value) return '阅读'
  if (isCreate.value) return '新增'
  if (isLibrary.value) return '句库'
  if (isStats.value) return '统计'
  return '复习'
})
const pageTitle = computed(() => {
  if (isPassages.value) return '每日阅读'
  if (isCreate.value) return '新增语料'
  if (isLibrary.value) return '句库管理'
  if (isStats.value) return '复习统计'
  return '智能复习队列'
})
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

const reviewRoundProgressPercent = computed(() => {
  const totalItems = Number(reviewRound.value?.total || 0)
  if (!totalItems) return 0
  return Math.min(100, Math.max(0, Number(reviewRound.value?.completed || 0) / totalItems * 100))
})

const reviewRoundEndTime = computed(() => {
  const value = new Date(String(reviewRound.value?.expires_at || ''))
  if (Number.isNaN(value.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23'
  }).format(value)
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
  return Boolean(passagesView.value?.hasPendingChanges?.())
}

async function flushPendingChanges() {
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
  sentenceCardClass,
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
  sentenceAudioIdentity,
  wordAudioIdentity,
  sentenceAudioButtonClass,
  sentenceAudioStatusLabel,
  sentenceAudioStatusClass
} = useEnglishAudioSettings({
  updateSentenceInList,
  scheduleAudioStatusRefresh
})

watch(() => props.mode, async () => {
  resetForModeChange()
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
