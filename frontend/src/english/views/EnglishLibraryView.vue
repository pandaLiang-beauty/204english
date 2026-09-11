<template>
  <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
    <main class="grid w-full min-w-0 max-w-none gap-3">
          <section  class="overflow-hidden rounded-md border border-border bg-surface">
            <div class="hidden grid-cols-[72px_minmax(240px,1.5fr)_230px_minmax(150px,0.8fr)_minmax(170px,0.9fr)_76px] gap-3 border-b border-border bg-surface-2 px-3 py-2 text-[11px] font-medium text-muted xl:grid">
              <div>编号 / 次数</div>
              <div>句子 / 译文</div>
              <div>音频 / 音色</div>
              <div>重点词</div>
              <div>跨句关联</div>
              <div class="text-right">操作</div>
            </div>

            <article
              v-for="sentence in sentences"
              :key="sentence.id"
              class="border-b border-border last:border-b-0"
            >
              <div class="grid gap-3 px-3 py-3 xl:grid-cols-[72px_minmax(240px,1.5fr)_230px_minmax(150px,0.8fr)_minmax(170px,0.9fr)_76px] xl:items-start">
                <div class="min-w-0">
                  <div class="text-sm font-semibold tabular-nums text-text">#{{ sentence.id }}</div>
                  <div class="mt-1 flex flex-wrap gap-x-2 text-[11px] tabular-nums text-muted xl:grid xl:gap-0.5">
                    <span>整句 {{ sentence.review_count }}</span>
                    <span>单词 {{ sentence.word_play_total }}</span>
                  </div>
                  <div class="mt-1 text-[10px] text-muted">{{ compactDate(sentence.updated_at || sentence.created_at) }}</div>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 text-[10px] font-medium text-muted xl:hidden">句子 / 译文</div>
                  <div class="line-clamp-2 text-sm leading-5 text-text">{{ plainSentenceText(sentence.text) }}</div>
                  <div class="mt-1 line-clamp-2 text-xs leading-5 text-muted">
                    {{ sentence.sentence_translation || '暂无译文' }}
                  </div>
                  <div v-if="sentence.ui.message" class="mt-1 text-[11px] text-primary">{{ sentence.ui.message }}</div>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 text-[10px] font-medium text-muted xl:hidden">音频 / 音色</div>
                  <div class="flex min-w-0 items-start gap-2">
                    <button
                      type="button"
                      :class="sentenceAudioButtonClass(sentence)"
                      :disabled="!sentence.audio_available || !sentence.audio_url"
                      :title="sentence.ui.audioPlaying ? '暂停整句' : '播放整句'"
                      @click="toggleSentenceAudio(sentence)"
                    >
                      <Pause v-if="sentence.ui.audioPlaying" class="h-4 w-4" />
                      <Play v-else class="h-4 w-4" />
                      <span class="sr-only">{{ sentence.ui.audioPlaying ? '暂停整句' : '播放整句' }}</span>
                    </button>
                    <div class="min-w-0 text-[11px] leading-5 text-muted">
                      <div :class="sentenceAudioStatusClass(sentence)" :title="sentence.audio_error || ''">
                        {{ sentenceAudioStatusLabel(sentence) }}
                      </div>
                      <div class="truncate text-text" :title="sentenceAudioIdentity(sentence)">
                        当前 {{ sentenceAudioIdentity(sentence) }}
                      </div>
                      <div class="truncate" :title="wordAudioIdentity(sentence)">
                        单词 {{ wordAudioIdentity(sentence) }} · {{ sentence.word_audio_count ?? Object.keys(sentence.pronunciations || {}).length }}/{{ focusWordCount(sentence) }}
                      </div>
                    </div>
                  </div>
                  <select
                    class="mt-1.5 h-7 w-full rounded-md border border-border bg-bg px-1.5 text-[11px] text-text outline-none focus:border-primary disabled:opacity-50"
                    :value="sentenceAudioSelection(sentence)"
                    :disabled="audioSettingsLoading || sentence.ui.audioVoiceSaving"
                    :aria-label="`句子 ${sentence.id} 的整句音色`"
                    @change="changeSentenceAudioVoice(sentence, $event)"
                  >
                    <option value="">跟随全局 · {{ globalSentenceAudioIdentity() }}</option>
                    <optgroup
                      v-for="group in audioVoiceGroups"
                      :key="group.key"
                      :label="group.label"
                    >
                      <option
                        v-for="voice in group.voices"
                        :key="audioVoiceKey(voice.provider, voice.voice)"
                        :value="audioVoiceKey(voice.provider, voice.voice)"
                        :disabled="!voice.available"
                      >
                        {{ audioVoiceOptionLabel(voice) }}
                      </option>
                    </optgroup>
                  </select>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 flex items-center justify-between gap-2 text-[10px] font-medium text-muted xl:hidden">
                    <span>重点词</span><span>{{ focusWordCount(sentence) }}</span>
                  </div>
                  <div v-if="wordEntries(sentence).length" class="flex flex-wrap gap-1.5">
                    <button
                      v-for="entry in wordEntries(sentence).slice(0, 3)"
                      :key="entry.word"
                      type="button"
                      class="max-w-full truncate rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary transition hover:bg-primary/15 disabled:opacity-50"
                      :disabled="sentence.ui.wordPlaying === entry.word"
                      :title="wordEntryTitle(entry)"
                      @click="playWord(sentence, entry.word)"
                    >
                      {{ entry.word }}
                    </button>
                    <span v-if="wordEntries(sentence).length > 3" class="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">
                      +{{ wordEntries(sentence).length - 3 }}
                    </span>
                  </div>
                  <div v-else class="text-[11px] text-muted">无重点词</div>
                </div>

                <div class="min-w-0">
                  <div class="mb-1 flex items-center justify-between gap-2 text-[10px] font-medium text-muted xl:hidden">
                    <span>跨句关联</span><span>{{ networkWords(sentence).length }}</span>
                  </div>
                  <div v-if="networkWords(sentence).length" class="grid gap-1">
                    <div
                      v-for="word in networkWords(sentence).slice(0, 3)"
                      :key="word.key"
                      class="flex min-w-0 items-center justify-between gap-2 text-[11px]"
                      :title="networkWordTitle(word)"
                    >
                      <span class="truncate font-medium text-text">{{ word.surface || word.key }}</span>
                      <span class="shrink-0 tabular-nums text-muted">{{ word.linked_sentences }}句 · 弱{{ Math.round((word.weakness || 0) * 100) }}%</span>
                    </div>
                    <div v-if="networkWords(sentence).length > 3" class="text-[10px] text-muted">
                      另有 {{ networkWords(sentence).length - 3 }} 个关联词
                    </div>
                  </div>
                  <div v-else class="text-[11px] text-muted">无跨句关联</div>
                </div>

                <div class="flex items-start justify-end gap-1 xl:grid xl:grid-cols-2">
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text"
                    :title="sentence.ui.showEditor ? '收起编辑' : '编辑句子'"
                    @click="toggleEditor(sentence)"
                  >
                    <Pencil class="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-danger/40 text-danger transition hover:bg-danger-soft"
                    title="删除句子"
                    @click="deleteSentence(sentence)"
                  >
                    <Trash2 class="h-3.5 w-3.5" />
                  </button>
                </div>

                <audio
                  v-if="sentence.audio_available && sentence.audio_url"
                  :ref="el => setSentenceAudioRef(sentence.id, el)"
                  class="hidden"
                  :src="resolveSentenceAudioSrc(sentence)"
                  :preload="sentence.ui.cachedAudioUrl ? 'auto' : 'none'"
                  @play="handleSentenceAudioPlay(sentence)"
                  @pause="handleSentenceAudioPause(sentence)"
                  @ended="handleSentenceAudioEnded(sentence)"
                />

                <div v-if="sentence.ui.showEditor" class="rounded-md border border-border bg-bg p-3 xl:col-span-6">
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
              </div>
            </article>
          </section>

      <div v-if="loading" class="rounded-lg border border-border bg-surface p-6 text-center text-sm text-muted">
        加载中
      </div>
      <div v-else-if="!sentences.length" class="rounded-lg border border-border bg-surface p-6 text-center text-sm text-muted">
        没有匹配的句子
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
          <span class="font-semibold tabular-nums text-text">{{ pageCount }}</span> 页，
          共 <span class="font-semibold tabular-nums text-text">{{ total }}</span> 条
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

        <aside  class="order-first grid content-start gap-4 xl:order-last xl:sticky xl:top-4">
          <section class="rounded-lg border border-border bg-surface p-4">
            <h2 class="text-sm font-semibold text-text">筛选</h2>
            <div class="mt-3 grid gap-2">
              <div class="relative min-w-0">
                <Search class="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" />
                <input
                  :value="searchInput"
                  @input="emit('update:search-input', $event.target.value)"
                  type="search"
                  class="h-9 w-full rounded-md border border-border bg-bg py-2 pl-9 pr-3 text-sm outline-none transition focus:border-primary"
                  placeholder="搜索句子 / 释义 / 单词"
                  @keydown.enter.prevent="applySearch"
                />
              </div>
              <div class="grid grid-cols-[minmax(0,1fr)_90px] gap-2">
                <select
                  :value="sort"
                  class="h-9 min-w-0 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
                  @change="updateSort"
                >
                  <option value="smart">智能复习</option>
                  <option value="least-reviewed">最少复习</option>
                  <option value="latest">最新添加</option>
                  <option value="oldest">最早添加</option>
                  <option value="id-asc">编号升序</option>
                  <option value="id-desc">编号降序</option>
                  <option value="missing-audio">缺音频</option>
                </select>
                <select
                  :value="pageSize"
                  class="h-9 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
                  @change="updatePageSize"
                >
                  <option v-for="option in pageSizeOptions" :key="option" :value="option">{{ option }}</option>
                </select>
              </div>
              <button
                type="button"
                class="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-60"
                :disabled="loading"
                @click="applySearch"
              >
                <Search class="h-4 w-4" />
                应用
              </button>
            </div>
            <p v-if="error" class="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{{ error }}</p>
          </section>

          <section class="rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">新增</h2>
              <button
                type="button"
                class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-surface-2 hover:text-text"
                @click="emit('update:create-open', !createOpen)"
              >
                <Plus class="h-3.5 w-3.5" />
                {{ createOpen ? '收起' : '单句' }}
              </button>
            </div>
            <div v-if="createOpen" class="mt-3 rounded-md border border-border bg-bg p-3">
              <SentenceEditor
                :model-value="draft"
                :saving="saving"
                :translating="translatingDraft"
                submit-label="保存"
                @update:model-value="emit('update:draft', $event)"
                @translate="translateDraft"
                @submit="createSentence"
              />
            </div>

            <div class="mt-3 border-t border-border pt-3">
              <div class="mb-2 flex items-center justify-between gap-3">
                <h3 class="text-xs font-semibold text-muted">批量导入</h3>
                <div class="flex gap-2">
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
                    :disabled="bulkLoading"
                    title="清空"
                    @click="resetBulkImport"
                  >
                    <RotateCcw class="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground disabled:opacity-60"
                    :disabled="bulkLoading || !bulkSentences.length"
                    title="导入"
                    @click="submitBulkImport"
                  >
                    <Upload class="h-4 w-4" />
                  </button>
                </div>
              </div>
              <textarea
                :value="bulkText"
                class="min-h-32 w-full resize-y rounded-md border border-border bg-bg p-3 text-sm leading-6 outline-none transition focus:border-primary"
                placeholder="Sentence one&#10;&#10;Sentence two"
                @input="updateBulkText"
              />
              <div v-if="bulkSentences.length" class="mt-2 text-xs text-muted">
                已识别 <span class="font-semibold tabular-nums text-text">{{ bulkSentences.length }}</span> 条
              </div>
              <p v-if="bulkMessage" class="mt-2 text-sm text-primary">{{ bulkMessage }}</p>
            </div>
          </section>
        </aside>

  </div>
</template>

<script setup>
import {
  ChevronLeft,
  ChevronRight,
  Pause,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  Upload
} from '@lucide/vue'
import SentenceEditor from '../SentenceEditor.vue'
import {
  focusWordCount,
  networkWordTitle,
  networkWords,
  plainSentenceText,
  wordEntries,
  wordEntryTitle
} from '../sentencePresentation.js'

const props = defineProps({
  sentences: { type: Array, default: () => [] },
  error: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  page: { type: Number, required: true },
  pageCount: { type: Number, required: true },
  total: { type: Number, required: true },
  searchInput: { type: String, default: '' },
  sort: { type: String, required: true },
  pageSize: { type: Number, required: true },
  pageSizeOptions: { type: Array, default: () => [] },
  createOpen: { type: Boolean, default: false },
  draft: { type: Object, required: true },
  saving: { type: Boolean, default: false },
  translatingDraft: { type: Boolean, default: false },
  bulkText: { type: String, default: '' },
  bulkLoading: { type: Boolean, default: false },
  bulkSentences: { type: Array, default: () => [] },
  bulkMessage: { type: String, default: '' },
  audioSettingsLoading: { type: Boolean, default: false },
  audioVoiceGroups: { type: Array, default: () => [] },
  compactDate: { type: Function, required: true },
  sentenceAudioButtonClass: { type: Function, required: true },
  sentenceAudioStatusClass: { type: Function, required: true },
  sentenceAudioStatusLabel: { type: Function, required: true },
  sentenceAudioIdentity: { type: Function, required: true },
  wordAudioIdentity: { type: Function, required: true },
  sentenceAudioSelection: { type: Function, required: true },
  globalSentenceAudioIdentity: { type: Function, required: true },
  audioVoiceKey: { type: Function, required: true },
  audioVoiceOptionLabel: { type: Function, required: true },
  toggleSentenceAudio: { type: Function, required: true },
  changeSentenceAudioVoice: { type: Function, required: true },
  playWord: { type: Function, required: true },
  toggleEditor: { type: Function, required: true },
  deleteSentence: { type: Function, required: true },
  translateSentenceDraft: { type: Function, required: true },
  saveSentence: { type: Function, required: true },
  resolveSentenceAudioSrc: { type: Function, required: true },
  setSentenceAudioRef: { type: Function, required: true },
  handleSentenceAudioPlay: { type: Function, required: true },
  handleSentenceAudioPause: { type: Function, required: true },
  handleSentenceAudioEnded: { type: Function, required: true },
  applySearch: { type: Function, required: true },
  reloadFirstPage: { type: Function, required: true },
  prevPage: { type: Function, required: true },
  nextPage: { type: Function, required: true },
  translateDraft: { type: Function, required: true },
  createSentence: { type: Function, required: true },
  resetBulkImport: { type: Function, required: true },
  submitBulkImport: { type: Function, required: true }
})

const emit = defineEmits([
  'update:search-input',
  'update:sort',
  'update:page-size',
  'update:create-open',
  'update:draft',
  'update:bulk-text',
  'clear-bulk-message'
])

function updateSort(event) {
  emit('update:sort', event.target.value)
  props.reloadFirstPage()
}

function updatePageSize(event) {
  emit('update:page-size', Number(event.target.value))
  props.reloadFirstPage()
}

function updateBulkText(event) {
  emit('update:bulk-text', event.target.value)
  emit('clear-bulk-message')
}
</script>
