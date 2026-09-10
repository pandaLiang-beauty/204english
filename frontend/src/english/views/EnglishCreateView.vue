<template>
  <section class="create-layout">
    <div class="surface-panel">
      <div class="segmented-control mb-6" role="group" aria-label="添加方式"><button type="button" :aria-pressed="method === 'single'" @click="method = 'single'">添加一句</button><button type="button" :aria-pressed="method === 'bulk'" @click="method = 'bulk'">批量导入</button></div>
      <div v-if="method === 'single'">
        <SentenceEditor :model-value="draft" :saving="saving" :translating="translatingDraft" submit-label="加入我的句库" @update:model-value="emit('update:draft', $event)" @translate="emit('translate')" @submit="emit('submit')" />
        <p v-if="savedMessage" class="status-message mt-5" role="status">{{ savedMessage }} <RouterLink to="/library" class="underline underline-offset-4">去句库查看</RouterLink></p>
      </div>
      <div v-else>
        <h2 class="section-heading mb-2">一次留下多句话</h2><p class="quiet-note mb-4">每个句子之间空一行。用 **重点词** 标记想学习的词，也可以导入后再标注。</p>
        <textarea :value="bulkText" :disabled="bulkLoading" class="ui-input bulk-textarea" aria-label="批量英文句子" placeholder="Paste your first sentence here.&#10;&#10;Leave a blank line before the next one." @input="updateBulkText" />
        <div class="editor-submit"><p class="quiet-note">已识别 {{ bulkSentences.length }} 句</p><div class="flex gap-2"><button type="button" class="ui-button ghost" :disabled="bulkLoading || !bulkText" @click="emit('reset-bulk')">清空</button><button type="button" class="ui-button primary" :disabled="bulkLoading || !bulkSentences.length" @click="emit('submit-bulk')"><Upload />{{ bulkLoading ? '正在导入…' : `导入 ${bulkSentences.length} 句` }}</button></div></div>
        <p v-if="bulkMessage" class="status-message mt-4" role="status">{{ bulkMessage }}</p>
      </div>
      <p v-if="error" class="status-message error mt-4" role="alert">{{ error }}</p>
    </div>
    <aside class="create-aside">
      <div class="collection-note"><BookOpen /><h2 class="section-heading">在语境里留下句子</h2><p class="quiet-note mt-3">读真题时，把不熟悉的词标出来，再将对应句子加入句库。以后复习时，词和原句会一起出现。</p><RouterLink to="/passages" class="ui-button ghost mt-3">去真题阅读<ArrowRight /></RouterLink></div>
      <section class="recent-sentences"><h2 class="section-heading">最近添加</h2><div v-for="sentence in sentences.slice(0, 5)" :key="sentence.id" class="recent-sentence"><p class="sentence-reader" lang="en">{{ plainSentenceText(sentence.text) }}</p><span class="quiet-note">{{ focusWordCount(sentence) }} 个重点词</span></div><p v-if="!sentences.length" class="quiet-note mt-4">添加的句子会出现在这里。</p></section>
    </aside>
  </section>
</template>
<script setup>
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowRight, BookOpen, Upload } from '@lucide/vue'
import SentenceEditor from '../SentenceEditor.vue'
import { focusWordCount, plainSentenceText } from '../sentencePresentation.js'
const method = ref('single')
const savedMessage = ref('')
const props = defineProps({
  stats: { type: Object, required: true },
  total: { type: Number, required: true },
  draft: { type: Object, required: true },
  saving: { type: Boolean, default: false },
  translatingDraft: { type: Boolean, default: false },
  error: { type: String, default: '' },
  bulkLoading: { type: Boolean, default: false },
  bulkText: { type: String, default: '' },
  bulkSentences: { type: Array, default: () => [] },
  bulkMessage: { type: String, default: '' },
  sentences: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false }
})

const emit = defineEmits([
  'update:draft',
  'translate',
  'submit',
  'reset-bulk',
  'submit-bulk',
  'update:bulk-text',
  'clear-bulk-message'
])

function updateBulkText(event) {
  emit('update:bulk-text', event.target.value)
  emit('clear-bulk-message')
}

watch(() => props.saving, (saving, previous) => {
  if (saving) savedMessage.value = ''
  if (previous && !saving && !props.error && !props.draft.text) savedMessage.value = '已保存到句库，将在下一轮参与复习。'
})
</script>
