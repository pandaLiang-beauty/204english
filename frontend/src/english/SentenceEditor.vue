<template>
  <div class="sentence-editor grid gap-4">
    <RichMarkedTextEditor :model-value="modelValue.text" placeholder="在这里输入或粘贴英文句子…" :disabled="saving" min-height-class="min-h-36" @update:model-value="value => update('text', value)" />
    <div>
      <div class="flex items-center justify-between gap-3 mb-2"><label :for="`${editorId}-translation`" class="section-heading">中文理解 <span class="quiet-note">可自动生成</span></label>
        <button type="button" class="ui-button small" :disabled="saving || translating || !String(modelValue.text || '').trim()" @click="emit('translate')"><Sparkles />{{ translating ? '正在生成…' : '生成翻译与词义' }}</button>
      </div>
      <textarea :id="`${editorId}-translation`" class="ui-input min-h-24 leading-7" :value="modelValue.sentenceTranslation" :disabled="saving" placeholder="可以先留空，保存后会自动补充译文和重点词释义。" @input="update('sentenceTranslation', $event.target.value)" />
    </div>
    <details class="editor-details">
      <summary class="details-toggle">调整重点词与长句分块 <span v-if="words.length" class="word-count">{{ words.length }} 个词</span></summary>
      <div v-if="words.length" class="grid gap-4 mt-3">
        <div v-for="(word, index) in words" :key="word" class="word-edit-row">
          <p class="font-semibold text-primary">{{ word }}</p>
          <label class="grid gap-2 quiet-note">词义<textarea class="ui-input min-h-20" :value="wordValue('translationsText', word)" :disabled="saving" placeholder="这个词在句子中的意思" @input="updateWord('translationsText', word, $event.target.value)" /></label>
          <label class="grid gap-2 quiet-note">理解提示<input class="ui-input" :value="wordValue('tipsText', word)" :disabled="saving" placeholder="可选，记下容易混淆的地方" @input="updateWord('tipsText', word, $event.target.value)" /></label>
        </div>
      </div>
      <p v-else class="quiet-note py-3">先在英文中标记重点词，再生成或填写词义。</p>
      <p class="quiet-note mt-5 mb-3">长句可以用 / 分隔意群，英文和中文依次对应。</p>
      <div class="grid gap-4 md:grid-cols-2">
        <label class="grid gap-2 quiet-note">英文分块<textarea class="ui-input min-h-24 leading-7" :value="modelValue.sentenceSegmentsText" :disabled="saving" placeholder="英文意群 / 英文意群" @input="update('sentenceSegmentsText', $event.target.value)" /></label>
        <label class="grid gap-2 quiet-note">中文分块<textarea class="ui-input min-h-24 leading-7" :value="modelValue.translationSegmentsText" :disabled="saving" placeholder="对应理解 / 对应理解" @input="update('translationSegmentsText', $event.target.value)" /></label>
      </div>
    </details>
    <div class="editor-submit"><p class="quiet-note">译文和音频会随内容自动更新。</p><button type="button" class="ui-button primary" :disabled="saving || !String(modelValue.text || '').trim()" @click="emit('submit')"><Check />{{ saving ? '正在保存…' : submitLabel }}</button></div>
  </div>
</template>
<script setup>
import { computed, useId } from 'vue'
import { Check, Sparkles } from '@lucide/vue'
import RichMarkedTextEditor from './RichMarkedTextEditor.vue'
import { markedWordsFromText } from './passageMarkdown.js'
import { parseMap, stringifyMap } from './sentenceDraft.js'
const props = defineProps({ modelValue: { type: Object, required: true }, saving: Boolean, translating: Boolean, submitLabel: { type: String, default: '保存句子' } })
const emit = defineEmits(['update:modelValue', 'translate', 'submit'])
const editorId = useId()
const words = computed(() => markedWordsFromText(props.modelValue.text).map(item => item.word))
function update(key, value) { emit('update:modelValue', { ...props.modelValue, [key]: value }) }
function wordKey(mapping, word) { return Object.keys(mapping).find(key => key.toLowerCase() === word.toLowerCase()) || word }
function wordValue(field, word) { const mapping = parseMap(props.modelValue[field]); return mapping[wordKey(mapping, word)] || '' }
function updateWord(field, word, value) {
  const mapping = parseMap(props.modelValue[field])
  mapping[wordKey(mapping, word)] = value.replace(/\r?\n/g, ' ')
  update(field, stringifyMap(mapping))
}
</script>
