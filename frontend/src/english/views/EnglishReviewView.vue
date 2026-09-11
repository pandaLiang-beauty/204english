<template>
  <section class="review-workspace" :class="{ 'large-reading': readingSize === 'large' }">
    <p v-if="error" class="status-message error mb-4" role="alert">{{ error }}</p>
    <div v-if="reviewRound" class="round-overview">
      <div class="round-progress">
        <span class="quiet-note">本轮</span>
        <strong>{{ reviewRound.completed || 0 }} / {{ reviewRound.total || 0 }}</strong><span class="quiet-note">次</span>
        <div class="progress-track" role="progressbar" aria-label="本轮完成进度" :aria-valuenow="Math.round(progress)" aria-valuemin="0" aria-valuemax="100"><div :style="{ width: progress + '%' }" /></div>
        <span class="quiet-note">{{ reviewRound.is_completed ? '已完成' : '还剩 ' + (reviewRound.remaining || 0) + ' 次' }}</span>
      </div>
      <p class="quiet-note">{{ reviewRound.is_completed ? '下一轮 ' + (nextRoundTime || '下一个北京时间 08:00') + ' 开始' : '本轮至 ' + roundEndTime + ' · 北京时间' }}</p>
    </div>

    <div class="review-toolbar">
      <p class="quiet-note">本页 {{ sentences.length }} 项<span v-if="stats.today"> · 今日完成 {{ stats.today.sentence_completions || 0 }} 次</span></p>
      <div class="review-reading-tools">
        <div class="review-shortcuts" aria-label="当前句子的快捷键"><span><kbd>Space</kbd>听音</span><span><kbd>T</kbd>译文</span><span><kbd>Enter</kbd>完成并继续</span></div>
        <button type="button" class="ui-button ghost small" :aria-pressed="readingSize === 'large'" @click="setReadingSize(readingSize === 'large' ? 'normal' : 'large')"><span class="text-base">Aa</span>{{ readingSize === 'large' ? '标准字号' : '大字阅读' }}</button>
      </div>
    </div>

    <div v-if="loading" class="surface-panel grid gap-7 py-12" role="status" aria-label="正在准备复习内容"><div class="loading-line w-1/4" /><div class="loading-line" /><div class="loading-line w-4/5" /><p class="quiet-note">正在准备你的复习内容…</p></div>
    <div v-else-if="!sentences.length" class="empty-state">
      <BookOpenCheck />
      <h2>{{ reviewRound?.is_completed ? '这一轮，完成了。' : '从第一句话开始积累' }}</h2>
      <p>{{ reviewRound?.is_completed ? '下一轮将在 ' + (nextRoundTime || '下一个北京时间 08:00') + ' 开始。' : '从真题阅读中选句，或添加你想反复理解的英文。' }}</p>
      <p v-if="reviewRound?.is_completed" class="quiet-note">可以去读一篇文章，也可以先休息一下。</p>
      <RouterLink class="ui-button primary" :to="reviewRound?.is_completed ? '/passages' : '/create'">{{ reviewRound?.is_completed ? '去读一篇文章' : '添加句子' }}<ArrowRight /></RouterLink>
    </div>
    <div v-else class="review-cards" aria-label="本页复习安排">
      <article v-for="(sentence, index) in sentences" :key="sentenceInstanceKey(sentence)"
        :ref="el => setSentenceCardRef(sentence, el)" class="review-card" tabindex="-1" data-review-keyboard-scope
        :aria-labelledby="'review-label-' + sentenceInstanceKey(sentence)" :aria-current="index === activeSentenceIndex ? 'step' : undefined"
        :class="{ 'is-active': index === activeSentenceIndex, 'is-completed': sentence.review_round_item_completed }"
        @click="activateSentence(index)" @focusin="activateSentence(index)">
        <header class="review-card-header">
          <div :id="'review-label-' + sentenceInstanceKey(sentence)" class="review-card-labels">
            <span class="section-label">{{ sentence.review_round_position ? '本轮第 ' + sentence.review_round_position + ' 项' : '第 ' + (index + 1) + ' 句' }}</span>
            <span v-if="sentence.review_repeat_total > 1" class="repeat-badge">本轮第 {{ sentence.review_repeat_index }} / {{ sentence.review_repeat_total }} 次</span>
            <span class="review-state" :class="{ 'is-concealed': !sentence.review_round_item_completed && index !== activeSentenceIndex, 'is-completed': sentence.review_round_item_completed }">{{ sentence.review_round_item_completed ? '已完成' : '当前' }}</span>
          </div>
          <div class="review-actions" role="group" :aria-label="'第 ' + (sentence.review_round_position || index + 1) + ' 项操作'">
            <button type="button" class="ui-button small review-listen-action" :disabled="!sentence.audio_available || !sentence.audio_url" :aria-label="sentence.ui.audioPlaying ? '暂停整句' : '听整句'" title="播放或暂停整句 · 空格" @click.stop="activateSentence(index); toggleSentenceAudio(sentence)"><Pause v-if="sentence.ui.audioPlaying" /><Play v-else /><span>{{ sentence.ui.audioPlaying ? '暂停' : '听整句' }}</span></button>
            <button type="button" class="ui-button small" :disabled="!hasTranslationContent(sentence)" :aria-expanded="sentence.ui.showTranslation" :aria-controls="'translation-' + sentenceInstanceKey(sentence)" title="显示或收起译文 · T" @click.stop="activateSentence(index); sentence.ui.showTranslation = !sentence.ui.showTranslation"><EyeOff v-if="sentence.ui.showTranslation" /><Eye v-else /><span>{{ sentence.ui.showTranslation ? '收译文' : '看译文' }}</span></button>
            <button type="button" class="ui-button small complete-action" :class="{ primary: index === activeSentenceIndex }" :disabled="sentence.ui.reviewing" :aria-busy="sentence.ui.reviewing" title="完成本次安排并继续往下读 · Enter" @click.stop="reviewSentenceAndNext(index)"><Check /><span>{{ sentence.ui.reviewing ? '保存中' : sentence.review_round_item_completed ? '下一句' : '完成并继续' }}</span></button>
            <button type="button" class="ui-icon-button ghost sentence-edit-action" :aria-expanded="sentence.ui.showEditor" :aria-label="sentence.ui.showEditor ? '收起句子编辑' : '编辑句子'" :title="sentence.ui.showEditor ? '收起句子编辑' : '编辑句子'" @click.stop="activateSentence(index); toggleEditor(sentence)"><Pencil /></button>
          </div>
        </header>
        <div v-if="sentence.ui.showEditor" class="review-editor" data-review-keyboard-ignore>
          <p class="quiet-note mb-4">保存修改后，译文和音频会根据新内容更新。</p>
          <SentenceEditor :model-value="sentence.ui.editDraft" :saving="sentence.ui.saving" :translating="sentence.ui.translating" submit-label="保存修改"
            @update:model-value="sentence.ui.editDraft = $event" @translate="translateSentenceDraft(sentence)" @submit="saveSentence(sentence)" />
        </div>
        <div class="review-reading-area">
          <p class="review-sentence sentence-reader" lang="en">
            <template v-for="(token, tokenIndex) in sentenceTokens(sentence.text)" :key="tokenIndex"><button v-if="token.focus" type="button" class="focus-word" :aria-label="'听 ' + token.text + ' 的发音'" @click.stop="playReviewWord(sentence, index, token.text)">{{ token.text }}</button><span v-else class="whitespace-pre-wrap">{{ token.text }}</span></template>
          </p>
          <div class="review-support" :class="{ 'has-vocabulary': wordEntries(sentence).length }">
            <section class="review-translation">
              <h3 class="section-heading">译文</h3>
              <div class="translation-slot">
                <!-- 译文隐藏时保留高度，让本句与后面的句子都留在原位。 -->
                <div :id="'translation-' + sentenceInstanceKey(sentence)" class="translation-panel"
                  :class="{ 'is-concealed': !sentence.ui.showTranslation }" :inert="!sentence.ui.showTranslation" :aria-hidden="!sentence.ui.showTranslation">
                  <p class="full-translation">{{ sentence.sentence_translation || segmentPairs(sentence).map(pair => pair.target).filter(Boolean).join('，') }}</p>
                  <details v-if="segmentPairs(sentence).length > 1" class="segment-details">
                    <summary class="details-toggle">分句对照</summary>
                    <div v-for="(pair, pairIndex) in segmentPairs(sentence)" :key="pairIndex" class="segment-pair"><span>{{ String(pairIndex + 1).padStart(2, '0') }}</span><div><p lang="en">{{ pair.source }}</p><p>{{ pair.target }}</p></div></div>
                  </details>
                </div>
                <p v-if="!sentence.ui.showTranslation" class="translation-hint">{{ hasTranslationContent(sentence) ? '译文已隐藏' : '译文准备中…' }}</p>
              </div>
            </section>
            <section v-if="wordEntries(sentence).length" class="review-vocabulary">
              <h3 class="section-heading">重点词 <span class="word-count">{{ wordEntries(sentence).length }}</span></h3>
              <SentenceWords :sentence="sentence" :play-word="(target, word) => playReviewWord(target, index, word)" :shortcuts="index === activeSentenceIndex" compact />
            </section>
          </div>
          <p v-if="sentence.ui.message" class="status-message mt-3" role="status">{{ sentence.ui.message }}</p>
          <p v-if="!sentence.audio_available || sentence.audio_status !== 'ready'" class="quiet-note mt-3" :class="sentenceAudioStatusClass(sentence)" :title="sentence.audio_error || ''">{{ sentenceAudioStatusLabel(sentence) }}</p>
        </div>
        <audio v-if="sentence.audio_available && sentence.audio_url" :ref="el => setSentenceAudioRef(sentence, el)" class="hidden" :src="resolveSentenceAudioSrc(sentence)" :preload="sentence.ui.cachedAudioUrl ? 'auto' : 'none'"
          @play="handleSentenceAudioPlay(sentence)" @pause="handleSentenceAudioPause(sentence)" @ended="handleSentenceAudioEnded(sentence)" />
      </article>
    </div>
    <PagePagination v-if="pageCount > 1" :page="page" :page-count="pageCount" :loading="loading" label="复习安排翻页" @change="changeReviewPage" />
  </section>
</template>
<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowRight, BookOpenCheck, Check, Eye, EyeOff, Pause, Pencil, Play } from '@lucide/vue'
import SentenceEditor from '../SentenceEditor.vue'
import SentenceWords from '../components/SentenceWords.vue'
import PagePagination from '../components/PagePagination.vue'
import { hasTranslationContent, segmentPairs, sentenceInstanceKey, sentenceTokens, wordEntries } from '../sentencePresentation.js'
import { useReadingPreferences } from '../useReadingPreferences.js'
import { beijingTime, roundProgress } from '../reviewPresentation.js'
const props = defineProps({
  stats: { type: Object, default: () => ({}) },
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

const { readingSize, setReadingSize } = useReadingPreferences()
const progress = computed(() => roundProgress(props.reviewRound))
const roundEndTime = computed(() => beijingTime(props.reviewRound?.expires_at))
const nextRoundTime = computed(() => beijingTime(props.reviewRound?.next_round_at))
function playReviewWord(sentence, index, word) {
  props.activateSentence(index)
  return props.playWord(sentence, word)
}
async function changeReviewPage(delta) {
  await (delta < 0 ? props.prevPage() : props.nextPage())
  if (!props.error) props.activateSentence(0, { scroll: true })
}
</script>
