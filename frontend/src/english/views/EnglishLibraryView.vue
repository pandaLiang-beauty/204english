<template>
  <section class="library-workspace">
    <form class="library-toolbar" role="search" @submit.prevent="applySearch">
      <div class="library-search"><Search /><input :value="searchInput" type="search" class="ui-input" aria-label="搜索句子、译文或重点词" placeholder="搜索句子、译文或重点词…" @input="emit('update:search-input', $event.target.value)" /></div>
      <button type="submit" class="ui-button" :disabled="loading">搜索</button>
      <select :value="sort" class="ui-input library-sort" aria-label="句库排序" @change="updateSort">
        <option value="id-desc">最近添加</option><option value="smart">按复习优先级</option><option value="least-reviewed">整句播放最少</option><option value="oldest">最早添加</option><option value="id-asc">编号从小到大</option><option value="missing-audio">优先查看缺音频</option>
      </select>
      <RouterLink class="ui-button primary library-add" to="/create"><Plus />添加句子</RouterLink>
    </form>
    <div class="library-list-heading"><p>共 <strong>{{ total }}</strong> 句 <span class="quiet-note">· 点击句子查看完整内容</span></p><label class="quiet-note">每页 <select :value="pageSize" aria-label="每页句子数量" @change="updatePageSize"><option v-for="option in pageSizeOptions" :key="option" :value="option">{{ option }}</option></select> 句</label></div>
    <p v-if="error" class="status-message error mb-4" role="alert">{{ error }}</p>
    <div v-if="loading" class="surface-panel grid gap-6" role="status"><div v-for="item in 3" :key="item" class="loading-line" /><p class="quiet-note">正在打开句库…</p></div>
    <div v-else-if="!sentences.length" class="empty-state"><Library /><h2>{{ searchInput ? '还没有找到这句话' : '你的句库，从这里开始' }}</h2><p>{{ searchInput ? '试试句子中的英文单词，或换一个中文关键词。' : '从文章中选句，也可以直接添加想学习的英文。' }}</p><RouterLink v-if="!searchInput" class="ui-button primary" to="/create">添加第一句<Plus /></RouterLink></div>
    <div v-else class="library-list">
      <article v-for="sentence in sentences" :key="sentence.id" class="library-row">
        <div class="library-row-main">
          <span class="library-id">#{{ sentence.id }}</span>
          <button type="button" class="library-sentence-button" :aria-expanded="openSentenceId === sentence.id" @click="openSentenceId = openSentenceId === sentence.id ? null : sentence.id">
            <p class="library-english sentence-reader" lang="en">{{ plainSentenceText(sentence.text) }}</p>
            <p class="library-chinese">{{ sentence.sentence_translation || '译文准备中…' }}</p>
            <div class="library-meta"><span>{{ focusWordCount(sentence) }} 个重点词</span><span>整句已听 {{ sentence.review_count || 0 }} 次</span><span>{{ compactDate(sentence.created_at) }} 添加</span></div>
          </button>
          <div class="library-row-actions">
            <button type="button" class="ui-icon-button" :disabled="!sentence.audio_available || !sentence.audio_url" :aria-label="sentence.ui.audioPlaying ? `暂停句子 ${sentence.id}` : `听句子 ${sentence.id}`" @click="toggleSentenceAudio(sentence)"><Pause v-if="sentence.ui.audioPlaying" /><Play v-else /></button>
            <button type="button" class="ui-icon-button ghost" :aria-expanded="openSentenceId === sentence.id" :aria-label="`查看句子 ${sentence.id} 的详情`" @click="openSentenceId = openSentenceId === sentence.id ? null : sentence.id"><ChevronDown :class="{ 'rotate-180': openSentenceId === sentence.id }" /></button>
          </div>
        </div>
        <div v-if="openSentenceId === sentence.id" class="library-detail">
          <div class="library-full-text"><p class="sentence-reader" lang="en">{{ plainSentenceText(sentence.text) }}</p><p>{{ sentence.sentence_translation || '译文准备中…' }}</p></div>
          <SentenceWords :sentence="sentence" :play-word="playWord" />
          <details class="library-audio-settings">
            <summary class="details-toggle">音色与关联词</summary>
            <div class="grid gap-4 md:grid-cols-2">
              <div><label :for="`voice-${sentence.id}`" class="quiet-note">这句话的朗读音色</label><select :id="`voice-${sentence.id}`" class="ui-input mt-2" :value="sentenceAudioSelection(sentence)" :disabled="audioSettingsLoading || sentence.ui.audioVoiceSaving" @change="changeSentenceAudioVoice(sentence, $event)">
                <option value="">跟随默认 · {{ globalSentenceAudioIdentity() }}</option>
                <optgroup v-for="group in audioVoiceGroups" :key="group.key" :label="group.label"><option v-for="voice in group.voices" :key="audioVoiceKey(voice.provider, voice.voice)" :value="audioVoiceKey(voice.provider, voice.voice)" :disabled="!voice.available">{{ audioVoiceOptionLabel(voice) }}</option></optgroup>
              </select><p class="quiet-note mt-2" :class="sentenceAudioStatusClass(sentence)">{{ sentenceAudioStatusLabel(sentence) }}</p></div>
              <div><p class="quiet-note mb-2">也出现在其他句子中的词</p><div class="flex flex-wrap gap-2"><span v-for="word in networkWords(sentence)" :key="word.key" class="repeat-badge" :title="networkWordTitle(word)">{{ word.surface || word.key }} · {{ word.linked_sentences }} 句</span><span v-if="!networkWords(sentence).length" class="quiet-note">还没有跨句关联词</span></div></div>
            </div>
          </details>
          <div class="library-detail-actions"><button type="button" class="ui-button" @click="toggleEditor(sentence)"><Pencil />{{ sentence.ui.showEditor ? '收起编辑' : '编辑句子' }}</button><button type="button" class="ui-button ghost danger" @click="deleteSentence(sentence)"><Trash2 />删除句子</button></div>
          <div v-if="sentence.ui.showEditor" class="mt-5"><SentenceEditor :model-value="sentence.ui.editDraft" :saving="sentence.ui.saving" :translating="sentence.ui.translating" submit-label="保存修改" @update:model-value="sentence.ui.editDraft = $event" @translate="translateSentenceDraft(sentence)" @submit="saveSentence(sentence)" /></div>
        </div>
        <p v-if="sentence.ui.message" class="status-message mx-5 mb-4" role="status">{{ sentence.ui.message }}</p>
        <audio v-if="sentence.audio_available && sentence.audio_url" :ref="el => setSentenceAudioRef(sentence.id, el)" class="hidden" :src="resolveSentenceAudioSrc(sentence)" :preload="sentence.ui.cachedAudioUrl ? 'auto' : 'none'" @play="handleSentenceAudioPlay(sentence)" @pause="handleSentenceAudioPause(sentence)" @ended="handleSentenceAudioEnded(sentence)" />
      </article>
    </div>
    <PagePagination :page="page" :page-count="pageCount" :loading="loading" :total="total" label="句库翻页" @change="$event < 0 ? prevPage() : nextPage()" />
  </section>
</template>
<script setup>
import { nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ChevronDown, Library, Pause, Pencil, Play, Plus, Search, Trash2 } from '@lucide/vue'
import SentenceEditor from '../SentenceEditor.vue'
import SentenceWords from '../components/SentenceWords.vue'
import PagePagination from '../components/PagePagination.vue'
import { focusWordCount, networkWordTitle, networkWords, plainSentenceText } from '../sentencePresentation.js'
const openSentenceId = ref(null)
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
  audioSettingsLoading: { type: Boolean, default: false },
  audioVoiceGroups: { type: Array, default: () => [] },
  compactDate: { type: Function, required: true },
  sentenceAudioStatusClass: { type: Function, required: true },
  sentenceAudioStatusLabel: { type: Function, required: true },
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
})

const emit = defineEmits(['update:search-input', 'update:sort', 'update:page-size'])

function updateSort(event) {
  emit('update:sort', event.target.value)
  nextTick(() => props.reloadFirstPage())
}

function updatePageSize(event) {
  emit('update:page-size', Number(event.target.value))
  nextTick(() => props.reloadFirstPage())
}

</script>
