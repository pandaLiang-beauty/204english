<template>
      <section class="passages-workspace grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside class="grid content-start gap-4 xl:sticky xl:top-4">
          <section class="rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">今日阅读</h2>
              <span class="text-xs text-muted tabular-nums">2 篇 · 英一/英二</span>
            </div>
            <div v-if="todayPassages.length" class="mt-3 grid gap-2">
              <div
                v-for="(passage, index) in todayPassages"
                :key="passage.id"
                class="rounded-md border border-primary/25 bg-primary/10 p-3"
              >
                <div class="text-xs font-medium text-primary">建议 {{ index + 1 }}</div>
                <button
                  type="button"
                  class="mt-1 block w-full text-left text-sm font-semibold text-text transition hover:text-primary"
                  @click="startPassage(passage)"
                >
                  {{ passageTitle(passage) }}
                </button>
                <div class="mt-2 flex flex-wrap gap-1.5 text-[11px] text-muted">
                  <span class="rounded bg-surface px-1.5 py-0.5">{{ passageStatusLabel(passage.status) }}</span>
                  <span class="rounded bg-surface px-1.5 py-0.5">{{ passageTypeLabel(passage.passage_type) }}</span>
                  <span v-if="passage.year" class="rounded bg-surface px-1.5 py-0.5">{{ passage.year }}</span>
                  <span v-if="passage.exam_type" class="rounded bg-surface px-1.5 py-0.5">{{ examTypeLabel(passage.exam_type) }}</span>
                </div>
                <button
                  type="button"
                  class="mt-3 inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground transition hover:opacity-90"
                  @click="startPassage(passage)"
                >
                  <Bold class="h-3.5 w-3.5" />
                  {{ passageActionLabel(passage) }}
                </button>
              </div>
            </div>
            <div v-else class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              暂无未完成阅读
            </div>
          </section>

          <section class="grid min-h-0 rounded-lg border border-border bg-surface p-4">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">文章队列</h2>
              <button
                type="button"
                class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-surface-2 hover:text-text"
                @click="resetPassageForm"
              >
                <Plus class="h-3.5 w-3.5" />
                新文章
              </button>
            </div>
            <div class="mt-3 flex flex-wrap gap-1.5">
              <button
                v-for="option in passageTypeFilters"
                :key="option.value || 'all'"
                type="button"
                :class="[
                  'rounded-md border px-2 py-1 text-xs transition',
                  passageTypeFilter === option.value
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border bg-bg text-muted hover:bg-surface-2 hover:text-text'
                ]"
                @click="setPassageTypeFilter(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="mt-3 grid grid-cols-2 gap-2">
              <select
                v-model="passageExamFilter"
                class="h-8 rounded-md border border-border bg-bg px-2 text-xs outline-none focus:border-primary"
                @change="applyPassageFilters"
              >
                <option value="">英一 / 英二</option>
                <option value="english1">英语一</option>
                <option value="english2">英语二</option>
              </select>
              <input
                v-model="passageYearFilter"
                type="number"
                min="1900"
                max="2200"
                class="h-8 rounded-md border border-border bg-bg px-2 text-xs outline-none focus:border-primary"
                placeholder="年份"
                @keydown.enter.prevent="applyPassageFilters"
              />
            </div>
            <div class="mt-2 flex gap-2">
              <div class="relative min-w-0 flex-1">
                <Search class="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-muted" />
                <input
                  v-model="passageSearchInput"
                  type="search"
                  class="h-8 w-full rounded-md border border-border bg-bg pl-8 pr-2 text-xs outline-none focus:border-primary"
                  placeholder="年份 / Text / 标题"
                  @keydown.enter.prevent="applyPassageFilters"
                />
              </div>
              <button
                type="button"
                class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted hover:bg-surface-2 hover:text-text"
                title="搜索文章"
                @click="applyPassageFilters"
              >
                <Search class="h-3.5 w-3.5" />
              </button>
            </div>
            <div v-if="passageLoading" class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              加载中
            </div>
            <div v-else-if="passages.length" class="mt-3 grid gap-2">
              <button
                v-for="passage in passages"
                :key="passage.id"
                type="button"
                class="rounded-md border px-3 py-2 text-left transition"
                :class="activePassage?.id === passage.id ? 'border-primary bg-primary/10' : 'border-border bg-bg hover:bg-surface-2'"
                @click="selectPassage(passage)"
              >
                <div class="flex items-center justify-between gap-3">
                  <span class="min-w-0 truncate text-sm font-semibold text-text">{{ passageTitle(passage) }}</span>
                  <span class="shrink-0 text-[11px] text-muted">#{{ passage.id }}</span>
                </div>
                <div class="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted">
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ passageStatusLabel(passage.status) }}</span>
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ passageTypeLabel(passage.passage_type) }}</span>
                  <span v-if="passage.year" class="rounded bg-surface-2 px-1.5 py-0.5">{{ passage.year }}</span>
                  <span v-if="passage.exam_type" class="rounded bg-surface-2 px-1.5 py-0.5">{{ examTypeLabel(passage.exam_type) }}</span>
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ markedWordCount(passage) }} 标词</span>
                  <span class="rounded bg-surface-2 px-1.5 py-0.5">{{ candidateCount(passage) }} 标注句</span>
                </div>
              </button>
            </div>
            <div v-else class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
              暂无文章
            </div>
            <div class="mt-3 flex items-center justify-between gap-2 text-xs text-muted">
              <button
                type="button"
                class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border disabled:opacity-40"
                :disabled="passagePage <= 1 || passageLoading"
                title="上一页"
                @click="changePassagePage(-1)"
              >
                <ChevronLeft class="h-3.5 w-3.5" />
              </button>
              <span class="tabular-nums">{{ passagePage }} / {{ passagePageCount }} · {{ passageTotal }}</span>
              <button
                type="button"
                class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border disabled:opacity-40"
                :disabled="passagePage >= passagePageCount || passageLoading"
                title="下一页"
                @click="changePassagePage(1)"
              >
                <ChevronRight class="h-3.5 w-3.5" />
              </button>
            </div>
          </section>
        </aside>

        <main class="grid min-w-0 content-start gap-4">
          <p v-if="passageMessage" class="rounded-md bg-primary/10 px-3 py-2 text-sm text-primary">{{ passageMessage }}</p>
          <p v-if="passageError" class="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{{ passageError }}</p>

          <section
            v-if="activePassage"
            ref="activePassagePanel"
            class="mx-auto grid w-full max-w-[980px] gap-4"
          >
            <div class="border-b border-border pb-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-xs text-muted">阅读文章 #{{ activePassage.id }}</div>
                  <h2 class="mt-1 text-xl font-semibold leading-7 text-text">{{ passageTitle(activePassage) }}</h2>
                  <div class="mt-2 flex flex-wrap gap-1.5 text-xs text-muted">
                    <span>{{ passageStatusLabel(activePassage.status) }}</span>
                    <span>{{ passageTypeLabel(activePassage.passage_type) }}</span>
                    <span v-if="activePassage.year">{{ activePassage.year }}</span>
                    <span v-if="activePassage.exam_type">{{ examTypeLabel(activePassage.exam_type) }}</span>
                    <span>{{ activePassage.body_text?.length || 0 }} 字符</span>
                    <span>{{ markedWordCount(activePassage) }} 标词</span>
                    <span>{{ candidateCount(activePassage) }} 标注句</span>
                    <span>已同步 {{ activePassage.selected_sentence_ids?.length || 0 }} 句</span>
                  </div>
                </div>
                <div class="flex flex-wrap justify-end gap-2">
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
                    :disabled="passageSaving"
                    @click="savePassageAnnotations"
                  >
                    <Check class="h-4 w-4" />
                    {{ passageSaving ? '保存中' : '保存标注' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-primary/40 px-3 text-sm text-primary transition hover:bg-primary/10 disabled:opacity-50"
                    :disabled="passageSyncing || !selectedCandidateIndexes.length"
                    @click="syncSelectedCandidates"
                  >
                    <Upload class="h-4 w-4" />
                    {{ passageSyncing ? '同步中' : `同步 ${selectedCandidateIndexes.length} 句` }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
                    :disabled="passageCompleting || activePassage.status === 'done'"
                    @click="completeActivePassage"
                  >
                    <Check class="h-4 w-4" />
                    {{ activePassage.status === 'done' ? '已完成' : passageCompleting ? '记录中' : '完成阅读' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
                    @click="passageEditorOpen = !passageEditorOpen"
                  >
                    <Pencil class="h-4 w-4" />
                    {{ passageEditorOpen ? '收起编辑' : '编辑信息' }}
                  </button>
                  <button
                    type="button"
                    class="inline-flex h-9 items-center gap-1.5 rounded-md border border-danger/40 px-3 text-sm text-danger transition hover:bg-danger-soft"
                    @click="deleteActivePassage"
                  >
                    <Trash2 class="h-4 w-4" />
                    删除
                  </button>
                </div>
              </div>
            </div>

            <article class="overflow-hidden rounded-lg border border-border bg-bg shadow-sm">
              <div class="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface/80 px-4 py-3 md:px-5">
                <div>
                  <h3 class="text-sm font-semibold text-text">阅读标注</h3>
                  <div class="mt-1 text-xs text-muted">{{ activePassage.source_label || '手动文章' }}</div>
                </div>
                <button
                  type="button"
                  class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text"
                  title="加粗选中内容"
                  :disabled="passageSaving"
                  @mousedown.prevent="togglePassageBold"
                >
                  <Bold class="h-4 w-4" />
                </button>
              </div>
              <div
                ref="passageAnnotator"
                class="passage-annotator mx-auto min-h-[36rem] w-full max-w-[780px] px-5 py-7 text-[17px] leading-[2] text-text outline-none transition focus:bg-surface/25 md:px-8 md:py-10 md:text-[18px] md:leading-[2.05]"
                :contenteditable="passageSaving ? 'false' : 'true'"
                :aria-disabled="passageSaving"
                role="textbox"
                aria-multiline="true"
                spellcheck="false"
                @input="handlePassageAnnotatorInput"
                @keydown="handlePassageAnnotatorKeydown"
                @paste="handlePassageAnnotatorPaste"
                v-html="passageAnnotatorHtml"
              />
            </article>

            <section class="rounded-lg border border-border bg-surface p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-text">标注句子</h3>
                  <div class="mt-1 text-xs text-muted tabular-nums">{{ candidateCount(activePassage) }} 句 · {{ markedWordCount(activePassage) }} 词</div>
                </div>
                <button
                  type="button"
                  class="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-60"
                  :disabled="passageSyncing || !selectedCandidateIndexes.length"
                  @click="syncSelectedCandidates"
                >
                  <Upload class="h-3.5 w-3.5" />
                  {{ passageSyncing ? '同步中' : `同步 ${selectedCandidateIndexes.length} 句` }}
                </button>
              </div>
              <div v-if="passageCandidates(activePassage).length" class="mt-3 grid gap-2">
                <label
                  v-for="(candidate, index) in passageCandidates(activePassage)"
                  :key="`${candidate.text}-${index}`"
                  class="grid cursor-pointer gap-2 rounded-md border border-border bg-bg p-3 transition hover:border-primary/40"
                >
                  <div class="flex items-start gap-3">
                    <input
                      v-model="selectedCandidateIndexes"
                      type="checkbox"
                      class="mt-1 h-4 w-4 accent-primary"
                      :value="index"
                    />
                    <div class="min-w-0">
                      <div class="text-[15px] font-medium leading-7 text-text">
                        <template v-for="(token, tokenIndex) in sentenceTokens(candidate.text)" :key="tokenIndex">
                          <span
                            v-if="token.focus"
                            class="rounded bg-primary/10 px-1 font-semibold text-primary"
                          >{{ token.text }}</span>
                          <span v-else>{{ token.text }}</span>
                        </template>
                      </div>
                      <div class="mt-2 flex flex-wrap gap-1.5 text-[11px] text-muted">
                        <span v-if="candidate.reason" class="rounded bg-bg px-1.5 py-0.5">{{ candidate.reason }}</span>
                        <span
                          v-for="word in candidate.focus_words || []"
                          :key="`${candidate.text}-${word.word}`"
                          class="rounded bg-bg px-1.5 py-0.5"
                        >
                          {{ word.word }}
                        </span>
                      </div>
                    </div>
                  </div>
                </label>
              </div>
              <div v-else class="mt-3 rounded-md border border-dashed border-border bg-surface px-3 py-4 text-center text-sm text-muted">
                暂无标注句
              </div>
            </section>
          </section>

          <section v-else-if="!passageEditorOpen" class="rounded-lg border border-border bg-surface p-6">
            <h2 class="text-sm font-semibold text-text">选择一篇文章开始阅读</h2>
            <p class="mt-2 text-sm text-muted">左侧队列里选择文章，或者新增一篇文章。</p>
          </section>

          <section v-if="passageEditorOpen || !activePassage" class="rounded-lg border border-border bg-surface p-4">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-text">{{ passageForm.id ? '编辑信息' : '新增阅读文章' }}</h2>
              <div class="flex flex-wrap gap-2">
                <button
                  v-if="passageForm.id"
                  type="button"
                  class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-surface-2 hover:text-text"
                  :disabled="passageSaving"
                  @click="resetPassageForm"
                >
                  <Plus class="h-3.5 w-3.5" />
                  新文章
                </button>
                <button
                  type="button"
                  class="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-60"
                  :disabled="passageSaving || !passageForm.bodyText.trim()"
                  @click="savePassage"
                >
                  <Check class="h-3.5 w-3.5" />
                  {{ passageSaving ? '保存中' : '保存文章' }}
                </button>
              </div>
            </div>

            <div class="grid gap-3 lg:grid-cols-[1fr_130px_120px_140px]">
              <input
                v-model="passageForm.title"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                placeholder="标题，例如 2026 英语一 Text 1"
                @input="handlePassageFormInput"
              />
              <select
                v-model="passageForm.passageType"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
                @change="handlePassageFormInput"
              >
                <option value="custom">自建文章</option>
                <option value="reading_a">阅读理解</option>
                <option value="cloze">完形填空</option>
                <option value="reading_b">新题型</option>
                <option value="translation">翻译材料</option>
              </select>
              <input
                v-model="passageForm.year"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                inputmode="numeric"
                placeholder="年份"
                @input="handlePassageFormInput"
              />
              <select
                v-model="passageForm.examType"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-2 text-sm outline-none transition focus:border-primary"
                @change="handlePassageFormInput"
              >
                <option value="">类型</option>
                <option value="english1">英语一</option>
                <option value="english2">英语二</option>
              </select>
            </div>
            <div class="mt-3 grid gap-3 lg:grid-cols-2">
              <input
                v-model="passageForm.sourceLabel"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                placeholder="来源标签，例如 考研真题"
                @input="handlePassageFormInput"
              />
              <input
                v-model="passageForm.sourceUrl"
                :disabled="passageSaving"
                class="h-9 rounded-md border border-border bg-bg px-3 text-sm outline-none transition focus:border-primary"
                placeholder="来源链接，可留空"
                @input="handlePassageFormInput"
              />
            </div>
            <textarea
              v-model="passageForm.bodyText"
              :disabled="passageSaving"
              class="mt-3 min-h-[18rem] w-full resize-y rounded-md border border-border bg-bg p-3 text-sm leading-6 outline-none transition focus:border-primary"
              placeholder="粘贴一篇考研英语文章原文"
              @input="handlePassageFormInput({ bodyText: true })"
            />
          </section>
        </main>
      </section>

</template>

<script setup>
import {
  Bold,
  Check,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  Search,
  Trash2,
  Upload
} from '@lucide/vue'
import {
  candidateCount,
  markedWordCount,
  passageCandidates
} from '../passageMarkdown'
import { usePassageEditor } from '../usePassageEditor'
import { sentenceTokens } from '../sentencePresentation.js'

const props = defineProps({
  refreshActivity: { type: Function, required: true }
})

const {
  passages,
  todayPassages,
  activePassage,
  passageTotal,
  passageLoading,
  passageSaving,
  passageSyncing,
  passageCompleting,
  passageMessage,
  passageError,
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
} = usePassageEditor({
  refreshActivity: props.refreshActivity
})

defineExpose({
  flushPendingChanges: flushPassageAutosave,
  hasPendingChanges: () => passageDirty.value,
  loadPassages
})
</script>

<style scoped>
/* 408 的卷面只把正文保留为亮纸色；辅助区使用更收敛的暖灰。
   阅读页此前所有卡片都继承近白的 surface，长时间看真题会显得刺眼。
   在这个工作区覆盖 token，既不影响句子复习等页面，也保留深色主题。 */
:global(:root[data-theme="light"]) .passages-workspace {
  --surface: #f6f4ef;
  --surface-2: #ece8df;
  --border: #d7d0c3;
}

.passage-annotator {
  --english-reading-font: Georgia, "Arial Hebrew", "Noto Sans Hebrew", "Times New Roman",
    Times, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "PingFang TC",
    "Microsoft JhengHei", "Hiragino Sans", "Yu Gothic", Meiryo, "Noto Sans CJK JP",
    "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", serif;
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}

.passage-annotator :deep(p) {
  margin: 0 0 1.45rem;
  text-wrap: pretty;
}

.passage-annotator :deep(p:last-child) {
  margin-bottom: 0;
}

.passage-annotator :deep(strong),
.passage-annotator :deep(b) {
  border-radius: 0.25rem;
  background: color-mix(in srgb, var(--primary, #b85c38) 12%, transparent);
  padding: 0.02rem 0.28rem;
  color: var(--primary, #b85c38);
  font-weight: 700;
}
</style>
