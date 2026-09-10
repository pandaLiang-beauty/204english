<template>
  <section class="passage-layout" :class="{ 'mobile-reading': mobileReading, 'large-reading': readingSize === 'large' }">
    <aside class="passage-browser">
      <section class="today-reading">
        <div class="flex items-center justify-between"><h2 class="section-heading">今天读什么</h2><span class="quiet-note">{{ todayPassages.length }} 篇推荐</span></div>
        <button v-for="(passage, index) in todayPassages" :key="passage.id" type="button" class="today-passage" @click="openPassage(passage)">
          <span class="today-index">0{{ index + 1 }}</span><span class="min-w-0"><span class="today-title">{{ passageTitle(passage) }}</span><span class="quiet-note">{{ passageTypeLabel(passage.passage_type) }} · {{ passage.status === 'done' ? '已读完' : '继续阅读' }}</span></span><ArrowUpRight />
        </button>
        <p v-if="!todayPassages.length" class="quiet-note mt-4">可以从下面选一篇，按自己的节奏阅读。</p>
      </section>
      <section class="passage-catalog">
        <div class="flex items-center justify-between"><h2 class="section-heading">真题与文章 <span class="word-count">{{ passageTotal }}</span></h2><button type="button" class="ui-button ghost small" @click="newPassage"><Plus />添加</button></div>
        <form class="passage-filters" role="search" @submit.prevent="applyPassageFilters">
          <div class="library-search"><Search /><input v-model="passageSearchInput" class="ui-input" type="search" aria-label="搜索文章" placeholder="搜索标题或 Text…" /></div>
          <div class="grid grid-cols-2 gap-2"><select v-model="passageExamFilter" class="ui-input" aria-label="考试类型" @change="applyPassageFilters"><option value="">英语一 / 二</option><option value="english1">英语一</option><option value="english2">英语二</option></select><input v-model="passageYearFilter" class="ui-input" type="number" min="1900" max="2200" aria-label="文章年份" placeholder="全部年份" @change="applyPassageFilters" /></div>
          <div class="flex gap-2"><select v-model="passageTypeFilter" class="ui-input" aria-label="题型" @change="applyPassageFilters"><option v-for="option in passageTypeFilters" :key="option.value" :value="option.value">{{ option.value ? passageTypeLabel(option.value) : '全部题型' }}</option></select><button type="submit" class="ui-button">筛选</button></div>
        </form>
        <p v-if="passageLoading" role="status" class="quiet-note py-5">正在查找文章…</p>
        <div v-else class="passage-catalog-list">
          <button v-for="passage in passages" :key="passage.id" type="button" class="passage-option" :aria-current="activePassage?.id === passage.id ? 'true' : undefined" @click="openPassage(passage)">
            <span class="passage-option-title">{{ passageTitle(passage) }}</span><span class="passage-option-meta"><span>{{ passageTypeLabel(passage.passage_type) }}</span><span :class="{ 'text-success': passage.status === 'done' }">{{ passageStatusLabel(passage.status) }}</span></span>
          </button>
          <p v-if="!passages.length" class="quiet-note py-5">没有匹配的文章，试试其他年份或题型。</p>
        </div>
        <PagePagination :page="passagePage" :page-count="passagePageCount" :loading="passageLoading" label="文章翻页" @change="changePassagePage" />
      </section>
    </aside>

    <div class="passage-reader-column">
      <button type="button" class="ui-button ghost passage-mobile-back" @click="mobileReading = false; scrollTop()"><ChevronLeft />选择其他文章</button>
      <p v-if="passageMessage" class="status-message mb-4" role="status">{{ passageMessage }}</p>
      <p v-if="passageError" class="status-message error mb-4" role="alert">{{ passageError }}</p>
      <section v-if="activePassage" ref="activePassagePanel" class="passage-reading-panel">
        <header class="passage-heading">
          <div class="flex flex-wrap items-center gap-2 section-label"><span>{{ examTypeLabel(activePassage.exam_type) || '自由阅读' }}</span><span>·</span><span>{{ passageTypeLabel(activePassage.passage_type) }}</span><span v-if="activePassage.status === 'done'" class="completed-badge"><Check />已读完</span></div>
          <h2>{{ passageTitle(activePassage) }}</h2>
          <div class="passage-heading-bottom"><span class="quiet-note">{{ activePassage.source_label || '我的阅读材料' }} · 已加入句库 {{ activePassage.selected_sentence_ids?.length || 0 }} 句</span><button type="button" class="ui-button ghost small" @click="togglePassageSettings"><Pencil />文章信息</button></div>
        </header>
        <article class="passage-paper">
          <div class="passage-mark-toolbar">
            <button type="button" class="ui-button small" title="选中单词后标记重点 · Ctrl / ⌘ + B" :disabled="passageSaving" @pointerdown.prevent @click="togglePassageBold"><Bold />标记重点</button>
            <span class="quiet-note marking-hint">选中单词，再标记</span>
            <span class="passage-save-state" role="status">{{ passageSaving || passageAutosaving ? '正在保存…' : passageDirty ? '修改待保存' : '已保存' }}</span>
            <button type="button" class="ui-button ghost small" :aria-pressed="readingSize === 'large'" title="切换正文字号" @click="setReadingSize(readingSize === 'large' ? 'normal' : 'large')">Aa</button>
          </div>
          <div ref="passageAnnotator" class="passage-annotator" :contenteditable="passageSaving ? 'false' : 'true'" :aria-disabled="passageSaving" role="textbox" aria-label="文章正文与重点标注" aria-multiline="true" lang="en" spellcheck="false" @input="handlePassageAnnotatorInput" @keydown="handlePassageAnnotatorKeydown" @paste="handlePassageAnnotatorPaste" v-html="passageAnnotatorHtml" />
          <div class="passage-paper-footer"><span class="quiet-note">正文和重点标注会自动保存</span><button type="button" class="ui-button small ghost" :disabled="passageSaving || !passageDirty" @click="savePassageAnnotations"><Check />立即保存</button></div>
        </article>
        <section class="selected-sentences">
          <div class="selected-sentences-heading"><div><h3 class="section-heading">留下值得复习的句子</h3><p class="quiet-note mt-2">带有重点标记的句子会出现在这里。勾选后加入句库。</p></div><span class="word-count">{{ candidateCount(activePassage) }} 句</span></div>
          <div v-if="passageCandidates(activePassage).length" class="passage-candidates">
            <label v-for="(candidate, index) in passageCandidates(activePassage)" :key="`${candidate.text}-${index}`" class="passage-candidate">
              <input v-model="selectedCandidateIndexes" type="checkbox" :value="index" :aria-label="`选择第 ${index + 1} 个标注句`" />
              <span class="sentence-reader" lang="en"><template v-for="(token, tokenIndex) in sentenceTokens(candidate.text)" :key="tokenIndex"><strong v-if="token.focus">{{ token.text }}</strong><span v-else>{{ token.text }}</span></template></span>
            </label>
          </div>
          <p v-else class="quiet-note selected-empty">遇到不熟悉的词，选中它并点「标记重点」。</p>
          <div class="selected-sentences-actions"><p class="quiet-note">新句子将在下一轮参与复习</p><button type="button" class="ui-button primary" :disabled="passageSyncing || !selectedCandidateIndexes.length" @click="syncSelectedCandidates"><Plus />{{ passageSyncing ? '正在加入…' : `加入句库 · ${selectedCandidateIndexes.length} 句` }}</button></div>
          <p v-if="passageSyncMessage" class="status-message mt-4" role="status">{{ passageSyncMessage }}</p>
        </section>
        <div class="reading-finish"><p class="quiet-note">读完并留下需要复习的句子，就可以结束这篇了。</p><button type="button" class="ui-button" :disabled="passageCompleting || activePassage.status === 'done'" @click="completeActivePassage"><Check />{{ activePassage.status === 'done' ? '这篇已读完' : passageCompleting ? '正在记录…' : '读完这篇' }}</button></div>
      </section>
      <div v-else-if="!passageEditorOpen" class="empty-state"><BookOpen /><h2>选一篇，慢慢读</h2><p>从今日推荐开始，也可以添加自己的阅读材料。</p><button type="button" class="ui-button primary" @click="newPassage"><Plus />添加文章</button></div>
      <section v-if="passageEditorOpen" ref="passageSettingsPanel" class="surface-panel passage-form">
        <div class="flex items-center justify-between gap-3 mb-5"><h2 class="section-heading">{{ passageForm.id ? '文章信息' : '添加阅读文章' }}</h2><button v-if="passageForm.id" type="button" class="ui-button ghost small" @click="passageEditorOpen = false">收起</button></div>
        <div class="grid gap-4">
          <label class="grid gap-2 quiet-note">文章标题<input v-model="passageForm.title" :disabled="passageSaving" class="ui-input" placeholder="例如：2026 英语一 Text 1" @input="handlePassageFormInput" /></label>
          <div class="grid grid-cols-2 gap-3"><label class="grid gap-2 quiet-note">题型<select v-model="passageForm.passageType" :disabled="passageSaving" class="ui-input" @change="handlePassageFormInput"><option value="custom">自建文章</option><option value="reading_a">阅读理解</option><option value="cloze">完形填空</option><option value="reading_b">新题型</option><option value="translation">翻译材料</option></select></label><label class="grid gap-2 quiet-note">考试类型<select v-model="passageForm.examType" :disabled="passageSaving" class="ui-input" @change="handlePassageFormInput"><option value="">其他阅读材料</option><option value="english1">英语一</option><option value="english2">英语二</option></select></label></div>
          <div class="grid grid-cols-2 gap-3"><label class="grid gap-2 quiet-note">年份<input v-model="passageForm.year" :disabled="passageSaving" type="number" min="1900" max="2200" class="ui-input" placeholder="可选" @input="handlePassageFormInput" /></label><label class="grid gap-2 quiet-note">来源<input v-model="passageForm.sourceLabel" :disabled="passageSaving" class="ui-input" placeholder="可选，如考研真题" @input="handlePassageFormInput" /></label></div>
          <label class="grid gap-2 quiet-note">来源链接<input v-model="passageForm.sourceUrl" :disabled="passageSaving" class="ui-input" placeholder="可选" @input="handlePassageFormInput" /></label>
          <label class="grid gap-2 quiet-note">文章正文<textarea v-model="passageForm.bodyText" :disabled="passageSaving" class="ui-input min-h-64 leading-8" placeholder="粘贴英文文章，保留自然段落。" @input="handlePassageFormInput({ bodyText: true })" /></label>
          <div class="flex items-center justify-between gap-3"><button v-if="passageForm.id" type="button" class="ui-button ghost danger" @click="deleteActivePassage"><Trash2 />删除文章</button><button type="button" class="ui-button primary ml-auto" :disabled="passageSaving || !passageForm.bodyText.trim()" @click="savePassage"><Check />{{ passageSaving ? '正在保存…' : '保存文章' }}</button></div>
        </div>
      </section>
    </div>
  </section>
</template>
<script setup>
import { nextTick, ref } from 'vue'
import { ArrowUpRight, Bold, BookOpen, Check, ChevronLeft, Pencil, Plus, Search, Trash2 } from '@lucide/vue'
import { candidateCount, passageCandidates } from '../passageMarkdown.js'
import { usePassageEditor } from '../usePassageEditor.js'
import { sentenceTokens } from '../sentencePresentation.js'
import { useReadingPreferences } from '../useReadingPreferences.js'
import PagePagination from '../components/PagePagination.vue'
const { readingSize, setReadingSize } = useReadingPreferences()
const mobileReading = ref(false)
const passageSettingsPanel = ref(null)
function scrollTop() { window.scrollTo({ top: 0 }) }
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
  passageTitle,
  passageStatusLabel,
  examTypeLabel,
  passageTypeLabel,
  handlePassageFormInput,
  togglePassageBold,
  handlePassageAnnotatorInput,
  handlePassageAnnotatorKeydown,
  handlePassageAnnotatorPaste,
  flushPassageAutosave,
  loadPassages,
  applyPassageFilters,
  changePassagePage,
  resetPassageForm,
  selectPassage,
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

async function openPassage(passage) {
  if (!await selectPassage(passage)) return
  mobileReading.value = true
  await nextTick()
  activePassagePanel.value?.scrollIntoView({ block: 'start' })
}
async function newPassage() {
  await resetPassageForm()
  if (activePassage.value) return
  mobileReading.value = true
  await nextTick()
  passageSettingsPanel.value?.scrollIntoView({ block: 'start' })
}
async function togglePassageSettings() {
  passageEditorOpen.value = !passageEditorOpen.value
  if (passageEditorOpen.value) { await nextTick(); passageSettingsPanel.value?.scrollIntoView({ block: 'start' }) }
}
</script>
