<template>
  <section class="review-workspace" :class="{ 'large-reading': readingSize === 'large' }">
    <p v-if="error" class="status-message error mb-4" role="alert">{{ error }}</p>
    <div v-if="reviewRound" class="round-overview">
      <div class="round-numbers">
        <p class="section-label">本轮进度</p>
        <p><strong>{{ reviewRound.completed || 0 }}</strong><span>/ {{ reviewRound.total || 0 }} 次</span></p>
      </div>
      <div class="round-track">
        <div class="flex justify-between gap-3 text-xs"><span>{{ reviewRound.is_completed ? '本轮安排已完成' : `还有 ${reviewRound.remaining || 0} 次，按自己的节奏来` }}</span><span class="muted">{{ Math.round(progress) }}%</span></div>
        <div class="progress-track" role="progressbar" aria-label="本轮完成进度" :aria-valuenow="Math.round(progress)" aria-valuemin="0" aria-valuemax="100"><div :style="{ width: `${progress}%` }" /></div>
        <p class="quiet-note">{{ reviewRound.is_completed ? `下一轮 ${nextRoundTime || '下一个北京时间 08:00'} 开始` : `本轮至 ${roundEndTime} · 北京时间` }}</p>
      </div>
      <div class="today-completions"><span class="quiet-note">今日已完成</span><strong>{{ stats.today?.sentence_completions ?? 0 }}<small> 次</small></strong></div>
    </div>

    <div class="review-toolbar">
      <div class="segmented-control" role="group" aria-label="复习显示方式">
        <button type="button" :aria-pressed="reviewLayout === 'focus'" @click="setReviewLayout('focus')"><Focus />逐句专注</button>
        <button type="button" :aria-pressed="reviewLayout === 'list'" @click="setReviewLayout('list')"><List />列表浏览</button>
      </div>
      <button type="button" class="ui-button ghost small" :aria-pressed="readingSize === 'large'" @click="setReadingSize(readingSize === 'large' ? 'normal' : 'large')"><span class="text-base">Aa</span>{{ readingSize === 'large' ? '标准字号' : '大字阅读' }}</button>
    </div>

    <div class="review-layout" :class="{ 'review-list-layout': reviewLayout === 'list' }">
      <div class="min-w-0">
        <div v-if="loading" class="surface-panel grid gap-7 py-12" role="status" aria-label="正在准备复习内容"><div class="loading-line w-1/4" /><div class="loading-line" /><div class="loading-line w-4/5" /><p class="quiet-note">正在准备你的复习内容…</p></div>
        <div v-else-if="!sentences.length" class="empty-state">
          <BookOpenCheck />
          <h2>{{ reviewRound?.is_completed ? '这一轮，完成了。' : '从第一句话开始积累' }}</h2>
          <p>{{ reviewRound?.is_completed ? `下一轮将在 ${nextRoundTime || '下一个北京时间 08:00'} 开始。` : '从真题阅读中选句，或添加你想反复理解的英文。' }}</p>
          <p v-if="reviewRound?.is_completed" class="quiet-note">可以去读一篇文章，也可以先休息一下。</p>
          <RouterLink class="ui-button primary" :to="reviewRound?.is_completed ? '/passages' : '/create'">{{ reviewRound?.is_completed ? '去读一篇文章' : '添加句子' }}<ArrowRight /></RouterLink>
        </div>
        <div v-else class="review-cards">
          <article v-for="{ sentence, index } in visibleSentences" :key="sentenceInstanceKey(sentence)"
            :ref="el => setSentenceCardRef(sentence, el)" class="review-card" data-review-keyboard-scope
            :class="{ 'is-active': index === activeSentenceIndex, 'is-completed': sentence.review_round_item_completed }"
            @click="activateSentence(index)">
            <header class="review-card-header">
              <div class="flex flex-wrap items-center gap-2">
                <span class="section-label">{{ sentence.review_round_position ? `本轮第 ${sentence.review_round_position} 项` : `第 ${index + 1} 句` }}</span>
                <span v-if="sentence.review_repeat_total > 1" class="repeat-badge">本轮第 {{ sentence.review_repeat_index }} / {{ sentence.review_repeat_total }} 次</span>
                <span v-if="sentence.review_round_item_completed" class="completed-badge"><Check />已完成本次</span>
              </div>
              <button type="button" class="ui-button ghost small" :aria-expanded="sentence.ui.showEditor" @click.stop="activateSentence(index); toggleEditor(sentence)"><Pencil />{{ sentence.ui.showEditor ? '收起' : '编辑' }}</button>
            </header>
            <div v-if="sentence.ui.showEditor" class="review-editor" data-review-keyboard-ignore>
              <p class="quiet-note mb-4">保存修改后，译文和音频会根据新内容更新。</p>
              <SentenceEditor :model-value="sentence.ui.editDraft" :saving="sentence.ui.saving" :translating="sentence.ui.translating" submit-label="保存修改"
                @update:model-value="sentence.ui.editDraft = $event" @translate="translateSentenceDraft(sentence)" @submit="saveSentence(sentence)" />
            </div>
            <div class="review-reading-area">
              <p class="review-sentence sentence-reader" lang="en">
                <template v-for="(token, tokenIndex) in sentenceTokens(sentence.text)" :key="tokenIndex"><button v-if="token.focus" type="button" class="focus-word" :aria-label="`听 ${token.text} 的发音`" @click.stop="activateSentence(index); playWord(sentence, token.text)">{{ token.text }}</button><span v-else class="whitespace-pre-wrap">{{ token.text }}</span></template>
              </p>
              <div v-if="sentence.ui.showTranslation" :id="`translation-${sentenceInstanceKey(sentence)}`" class="translation-panel">
                <p class="section-label">对照理解</p>
                <p class="full-translation">{{ sentence.sentence_translation || segmentPairs(sentence).map(pair => pair.target).filter(Boolean).join('，') }}</p>
                <details v-if="segmentPairs(sentence).length > 1" class="segment-details">
                  <summary class="details-toggle">拆开长句，逐段理解</summary>
                  <div v-for="(pair, pairIndex) in segmentPairs(sentence)" :key="pairIndex" class="segment-pair"><span>{{ String(pairIndex + 1).padStart(2, '0') }}</span><div><p lang="en">{{ pair.source }}</p><p>{{ pair.target }}</p></div></div>
                </details>
              </div>
              <p v-else class="translation-hint">先试着理解，再点「看译文」。</p>
              <section v-if="wordEntries(sentence).length" class="review-vocabulary">
                <div class="flex items-center justify-between gap-2"><h3 class="section-heading">句中重点词 <span class="word-count">{{ wordEntries(sentence).length }}</span></h3><span class="quiet-note">点击喇叭听发音</span></div>
                <SentenceWords :sentence="sentence" :play-word="playWord" :shortcuts="index === activeSentenceIndex" />
              </section>
              <p v-if="sentence.ui.message" class="status-message mt-4" role="status">{{ sentence.ui.message }}</p>
              <p v-if="!sentence.audio_available || sentence.audio_status !== 'ready'" class="quiet-note mt-4" :class="sentenceAudioStatusClass(sentence)" :title="sentence.audio_error || ''">{{ sentenceAudioStatusLabel(sentence) }}</p>
            </div>
            <audio v-if="sentence.audio_available && sentence.audio_url" :ref="el => setSentenceAudioRef(sentence, el)" class="hidden" :src="resolveSentenceAudioSrc(sentence)" :preload="sentence.ui.cachedAudioUrl ? 'auto' : 'none'"
              @play="handleSentenceAudioPlay(sentence)" @pause="handleSentenceAudioPause(sentence)" @ended="handleSentenceAudioEnded(sentence)" />
            <footer class="review-actions">
              <button type="button" class="ui-button" :disabled="!sentence.audio_available || !sentence.audio_url" :aria-label="sentence.ui.audioPlaying ? '暂停整句' : '听整句'" title="播放或暂停整句 · 空格" @click.stop="activateSentence(index); toggleSentenceAudio(sentence)"><Pause v-if="sentence.ui.audioPlaying" /><Play v-else /><span>{{ sentence.ui.audioPlaying ? '暂停' : '听整句' }}</span><kbd>Space</kbd></button>
              <button type="button" class="ui-button" :disabled="!hasTranslationContent(sentence)" :aria-expanded="sentence.ui.showTranslation" :aria-controls="`translation-${sentenceInstanceKey(sentence)}`" title="显示或收起译文 · T" @click.stop="activateSentence(index); sentence.ui.showTranslation = !sentence.ui.showTranslation"><EyeOff v-if="sentence.ui.showTranslation" /><Eye v-else /><span>{{ sentence.ui.showTranslation ? '收译文' : '看译文' }}</span><kbd>T</kbd></button>
              <button type="button" class="ui-button primary complete-action" :disabled="sentence.ui.reviewing" :aria-busy="sentence.ui.reviewing" title="完成本次并继续 · Enter" @click.stop="reviewSentenceAndNext(index)"><Check /><span>{{ sentence.ui.reviewing ? '保存中' : sentence.review_round_item_completed ? '下一句' : '完成本次' }}</span><kbd>↵</kbd></button>
            </footer>
          </article>
        </div>
        <div v-if="sentences.length && !loading && reviewLayout === 'focus'" class="sentence-navigation">
          <button type="button" class="ui-button ghost" :disabled="activeSentenceIndex === 0 && page <= 1" @click="moveActiveSentence(-1)"><ChevronLeft />上一句</button>
          <span class="quiet-note">本页 {{ activeSentenceIndex + 1 }} / {{ sentences.length }} 项</span>
          <button type="button" class="ui-button ghost" :disabled="activeSentenceIndex >= sentences.length - 1 && page >= pageCount" @click="moveActiveSentence(1)">下一句<ChevronRight /></button>
        </div>
        <PagePagination v-if="pageCount > 1" :page="page" :page-count="pageCount" :loading="loading" label="复习安排翻页" @change="$event < 0 ? prevPage() : nextPage()" />
      </div>
      <aside v-if="sentences.length && reviewLayout === 'focus'" class="review-aside">
        <details class="review-queue" :open="wideScreen">
          <summary class="details-toggle"><span>本页安排 <span class="word-count">{{ sentences.length }}</span></span></summary>
          <div class="queue-items">
            <button v-for="(sentence, index) in sentences" :key="sentenceInstanceKey(sentence)" type="button" class="queue-item" :aria-current="index === activeSentenceIndex ? 'step' : undefined" @click="activateSentence(index, { scroll: true })">
              <span class="queue-index"><Check v-if="sentence.review_round_item_completed" /><template v-else>{{ String(sentence.review_round_position || index + 1).padStart(2, '0') }}</template></span>
              <span class="queue-sentence">{{ plainSentenceText(sentence.text) }}</span>
              <span v-if="sentence.review_repeat_total > 1" class="queue-repeat">{{ sentence.review_repeat_index }}/{{ sentence.review_repeat_total }}</span>
            </button>
          </div>
        </details>
        <div class="keyboard-guide">
          <p class="section-label">留在阅读的节奏里</p>
          <p><span>听整句 / 暂停</span><kbd>Space</kbd></p><p><span>看译文</span><kbd>T</kbd></p><p><span>完成本次</span><kbd>Enter</kbd></p><p><span>切换句子</span><span><kbd>↑</kbd> <kbd>↓</kbd></span></p>
          <div class="quiet-note">听音会记录播放次数。<br />点「完成本次」后，才会完成这一项安排。</div>
        </div>
      </aside>
    </div>
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowRight, BookOpenCheck, Check, ChevronLeft, ChevronRight, Eye, EyeOff, Focus, List, Pause, Pencil, Play } from '@lucide/vue'
import SentenceEditor from '../SentenceEditor.vue'
import SentenceWords from '../components/SentenceWords.vue'
import PagePagination from '../components/PagePagination.vue'
import { hasTranslationContent, plainSentenceText, segmentPairs, sentenceInstanceKey, sentenceTokens, wordEntries } from '../sentencePresentation.js'
import { useReadingPreferences } from '../useReadingPreferences.js'
import { beijingTime, roundProgress } from '../reviewPresentation.js'
const props = defineProps({
  stats: { type: Object, default: () => ({}) },
  moveActiveSentence: { type: Function, required: true },
  sentences: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  reviewRound: { type: Object, default: null },
  activeSentenceIndex: { type: Number, default: 0 },
  page: { type: Number, required: true },
  pageCount: { type: Number, required: true },
  setSentenceCardRef: { type: Function, required: true },
  activateSentence: { type: Function, required: true },
  sentenceAudioStatusClass: { type: Function, required: true },
  sentenceAudioStatusLabel: { type: Function, required: true },
  toggleSentenceAudio: { type: Function, required: true },
  reviewSentenceAndNext: { type: Function, required: true },
  toggleEditor: { type: Function, required: true },
  translateSentenceDraft: { type: Function, required: true },
  saveSentence: { type: Function, required: true },
  playWord: { type: Function, required: true },
  resolveSentenceAudioSrc: { type: Function, required: true },
  setSentenceAudioRef: { type: Function, required: true },
  handleSentenceAudioPlay: { type: Function, required: true },
  handleSentenceAudioPause: { type: Function, required: true },
  handleSentenceAudioEnded: { type: Function, required: true },
  prevPage: { type: Function, required: true },
  nextPage: { type: Function, required: true }
})

const { reviewLayout, readingSize, setReviewLayout, setReadingSize } = useReadingPreferences()
const wideScreen = window.matchMedia('(min-width: 1200px)').matches
const progress = computed(() => roundProgress(props.reviewRound))
const roundEndTime = computed(() => beijingTime(props.reviewRound?.expires_at))
const nextRoundTime = computed(() => beijingTime(props.reviewRound?.next_round_at))
const visibleSentences = computed(() => {
  const entries = props.sentences.map((sentence, index) => ({ sentence, index }))
  return reviewLayout.value === 'list' ? entries : entries.slice(props.activeSentenceIndex, props.activeSentenceIndex + 1)
})
</script>
