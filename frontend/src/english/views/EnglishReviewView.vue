<template>
  <div class="grid gap-4">
    <main class="grid w-full min-w-0 max-w-none gap-4">
      <p v-if="error" class="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{{ error }}</p>
          <article
            v-for="(sentence, index) in sentences"
            :key="sentenceInstanceKey(sentence)"
            :ref="el => setSentenceCardRef(sentence, el)"
            data-review-keyboard-scope
            :class="sentenceCardClass(sentence, index)"
            @click="activateSentence(index)"
          >
            <div class="flex flex-wrap items-start justify-between gap-3 border-b border-border bg-surface/80 px-4 py-3 md:px-5">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <h2 class="text-sm font-semibold text-text">
                    {{ sentence.review_round_position ? `本轮第 ${sentence.review_round_position} 句` : '智能复习' }}
                  </h2>
                  <span v-if="index === activeSentenceIndex && keyboardEnabled" class="text-xs font-medium text-primary">当前</span>
                  <span
                    v-if="!sentence.audio_available || sentence.audio_status !== 'ready'"
                    class="text-xs"
                    :class="sentenceAudioStatusClass(sentence)"
                    :title="sentence.audio_error || ''"
                  >
                    {{ sentenceAudioStatusLabel(sentence) }}
                  </span>
                </div>
                <div v-if="sentence.ui.message || sentence.ui.status" class="mt-2">
                  <span v-if="sentence.ui.message" class="rounded-md bg-primary/10 px-2 py-1 text-xs text-primary">
                    {{ sentence.ui.message }}
                  </span>
                  <span v-else-if="sentence.ui.status" class="rounded-md bg-surface-2 px-2 py-1 text-xs text-muted">
                    {{ sentence.ui.status }}
                  </span>
                </div>
              </div>

              <div class="flex flex-wrap justify-end gap-2">
                <button
                  v-if="sentence.audio_available && sentence.audio_url"
                  type="button"
                  class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
                  :class="sentence.ui.audioPlaying ? 'border-primary bg-primary/10 text-primary' : ''"
                  :title="sentence.ui.audioPlaying ? '暂停整句（Space）' : '播放整句（Space）'"
                  @click.stop="activateSentence(index); toggleSentenceAudio(sentence)"
                >
                  <Pause v-if="sentence.ui.audioPlaying" class="h-4 w-4" />
                  <Play v-else class="h-4 w-4" />
                  {{ sentence.ui.audioPlaying ? '暂停' : '播放' }}
                </button>
                <button
                  type="button"
                  class="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-60"
                  :disabled="sentence.ui.reviewing"
                  :aria-busy="sentence.ui.reviewing"
                  :title="sentence.review_round_item_completed ? '进入下一句（Enter / J）' : '完成并进入下一句（Enter / J）'"
                  @click.stop="reviewSentenceAndNext(index)"
                >
                  <Check class="h-4 w-4" />
                  {{ sentence.ui.reviewing ? '记录中' : sentence.review_round_item_completed ? '下一句' : '完成并下一句' }}
                </button>
                <button
                  type="button"
                  class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
                  :disabled="!hasTranslationContent(sentence)"
                  title="显示或隐藏翻译（T）"
                  @click.stop="activateSentence(index); sentence.ui.showTranslation = !sentence.ui.showTranslation"
                >
                  <Eye class="h-4 w-4" />
                  {{ sentence.ui.showTranslation ? '隐藏翻译' : '显示翻译' }}
                </button>
                <button
                  type="button"
                  class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
                  :title="sentence.ui.showEditor ? '收起句子编辑' : '编辑句子并自动更新音频'"
                  @click.stop="activateSentence(index); toggleEditor(sentence)"
                >
                  <Pencil class="h-4 w-4" />
                  {{ sentence.ui.showEditor ? '收起编辑' : '编辑' }}
                </button>
              </div>
            </div>

            <div
              v-if="sentence.ui.showEditor"
              data-review-keyboard-ignore
              class="mx-4 mt-4 rounded-md border border-border bg-surface p-3 md:mx-5"
              @click.stop="activateSentence(index)"
            >
              <p class="mb-3 text-xs leading-5 text-muted">
                修改正文后保存，旧整句音频会立即失效，并按新正文自动重新生成；旧翻译若已不匹配也会自动更新。
              </p>
              <SentenceEditor
                :model-value="sentence.ui.editDraft"
                :saving="sentence.ui.saving"
                :translating="sentence.ui.translating"
                submit-label="保存修改"
                @update:model-value="sentence.ui.editDraft = $event"
                @translate="translateSentenceDraft(sentence)"
                @submit="saveSentence(sentence)"
              />
            </div>

            <div class="sentence-reader px-5 py-7 text-[18px] leading-[2] text-text md:px-8 md:py-8 md:text-[20px] md:leading-[2.05]">
              <template v-for="(token, index) in sentenceTokens(sentence.text)" :key="index">
                <button
                  v-if="token.focus"
                  type="button"
                  class="rounded-md bg-primary/10 px-1.5 font-semibold text-primary underline-offset-4 transition hover:bg-primary/15 hover:underline"
                  @click="playWord(sentence, token.text)"
                >{{ token.text }}</button>
                <span v-else class="whitespace-pre-wrap">{{ token.text }}</span>
              </template>
            </div>

                <audio
                  v-if="sentence.audio_available && sentence.audio_url"
                  :ref="el => setSentenceAudioRef(sentence, el)"
              class="hidden"
              :src="resolveSentenceAudioSrc(sentence)"
              :preload="sentence.ui.cachedAudioUrl ? 'auto' : 'none'"
              @play="handleSentenceAudioPlay(sentence)"
              @pause="handleSentenceAudioPause(sentence)"
              @ended="handleSentenceAudioEnded(sentence)"
            />

            <div class="grid gap-3 border-t border-border bg-surface/60 px-4 py-4 md:px-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
              <section class="rounded-md border border-border bg-bg p-3">
                <h3 class="text-xs font-semibold text-muted">整句翻译</h3>
                <div v-if="segmentPairs(sentence).length">
                  <div class="mt-2 text-sm leading-6 text-text">
                    <template v-for="(pair, pairIndex) in segmentPairs(sentence)" :key="`${sentence.id}-${pairIndex}`">
                      <span v-if="pairIndex" class="px-1.5 text-muted">//</span>
                      <span>{{ pair.source }}</span>
                    </template>
                  </div>
                  <div
                    :class="[
                      'mt-1 text-sm leading-6 text-text',
                      sentence.ui.showTranslation ? '' : 'invisible'
                    ]"
                  >
                    <template v-for="(pair, pairIndex) in segmentPairs(sentence)" :key="`${sentence.id}-translation-${pairIndex}`">
                      <span v-if="pairIndex" class="px-1.5 text-muted">//</span>
                      <span>{{ pair.target }}</span>
                    </template>
                  </div>
                </div>
                <div v-else class="mt-2 text-sm text-muted">暂无分块翻译</div>
              </section>

              <section class="rounded-md border border-dashed border-border bg-bg p-3">
                <div class="mb-2 flex items-center justify-between gap-2">
                  <h3 class="text-xs font-semibold text-muted">重点词</h3>
                  <div class="text-[11px] text-muted tabular-nums">{{ wordEntries(sentence).length }}</div>
                </div>
                <div v-if="wordEntries(sentence).length" class="flex flex-wrap gap-2">
                  <span
                    v-for="entry in wordEntries(sentence)"
                    :key="entry.word"
                    class="inline-flex max-w-full items-center gap-2 rounded-md border border-primary/25 bg-primary/10 px-2 py-1.5 text-sm text-primary"
                  >
                    <span class="min-w-0 break-words">
                      <span class="font-semibold">{{ entry.word }}</span>
                      <span class="text-muted"> = {{ entry.meaning || '未填释义' }}</span>
                      <span v-if="entry.tip" class="text-muted"> · {{ entry.tip }}</span>
                    </span>
                    <span class="grid shrink-0 justify-items-center gap-1">
                      <button
                        type="button"
                        class="inline-flex h-7 w-8 items-center justify-center rounded-md border border-primary/30 text-primary transition hover:bg-primary/10 disabled:opacity-50"
                        :disabled="sentence.ui.wordPlaying === entry.word"
                        :title="entry.audio ? '播放读音' : '无读音'"
                        @click="playWord(sentence, entry.word)"
                      >
                        <Volume2 class="h-4 w-4" />
                      </button>
                    </span>
                  </span>
                </div>
                <div v-else class="text-sm text-muted">暂无重点词</div>
              </section>
            </div>
          </article>

      <div v-if="loading" class="rounded-lg border border-border bg-surface p-6 text-center text-sm text-muted">
        加载中
      </div>
      <div v-else-if="!sentences.length" class="rounded-lg border border-border bg-surface p-6 text-center text-sm text-muted">
        {{
          reviewRound?.is_completed
            ? '当前安排已完成，下一份安排将在明天 8:00 开始'
            : reviewRound?.remaining
              ? '本页句子已经完成，可前往下一页或刷新继续'
              : '没有匹配的句子'
        }}
      </div>

      <nav class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-3 text-sm">
        <button
          type="button"
          class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-40"
          :disabled="page <= 1 || loading"
          @click="prevPage"
        >
          <ChevronLeft class="h-4 w-4" />
          上一页
        </button>
        <div class="text-muted">
          第 <span class="font-semibold tabular-nums text-text">{{ page }}</span> /
          <span class="font-semibold tabular-nums text-text">{{ pageCount }}</span> 页
        </div>
        <button
          type="button"
          class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-40"
          :disabled="page >= pageCount || loading"
          @click="nextPage"
        >
          下一页
          <ChevronRight class="h-4 w-4" />
        </button>
      </nav>
    </main>
  </div>
</template>

<script setup>
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  Pause,
  Pencil,
  Play,
  Volume2
} from '@lucide/vue'
import SentenceEditor from '../SentenceEditor.vue'
import {
  hasTranslationContent,
  segmentPairs,
  sentenceInstanceKey,
  sentenceTokens,
  wordEntries
} from '../sentencePresentation.js'

defineProps({
  sentences: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  reviewRound: { type: Object, default: null },
  activeSentenceIndex: { type: Number, default: 0 },
  keyboardEnabled: { type: Boolean, default: false },
  page: { type: Number, required: true },
  pageCount: { type: Number, required: true },
  setSentenceCardRef: { type: Function, required: true },
  sentenceCardClass: { type: Function, required: true },
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
</script>

<style scoped>
.sentence-reader {
  --english-reading-font: Georgia, "Arial Hebrew", "Noto Sans Hebrew", "Times New Roman",
    Times, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "PingFang TC",
    "Microsoft JhengHei", "Noto Sans CJK TC", "Hiragino Sans", "Yu Gothic", Meiryo,
    "Noto Sans CJK JP", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", serif;
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}

.sentence-reader button {
  font-family: inherit;
}
</style>
