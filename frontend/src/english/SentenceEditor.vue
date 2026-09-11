<template>
  <div class="grid gap-3">
    <div class="grid gap-2">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <label class="text-xs font-medium text-muted">句子</label>
        <button
          type="button"
          :disabled="saving || translating || !String(modelValue.text || '').trim()"
          class="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
          @click="emit('translate')"
        >
          <Sparkles class="h-3.5 w-3.5" />
          {{ translating ? '生成中' : '生成翻译' }}
        </button>
      </div>
      <RichMarkedTextEditor
        :model-value="modelValue.text"
        placeholder="句子"
        :disabled="saving"
        min-height-class="min-h-32"
        @update:model-value="value => update('text', value)"
      />
      <label class="text-xs font-medium text-muted">整句翻译</label>
      <textarea
        class="sentence-editor-translation min-h-20 w-full resize-y rounded-md border border-border bg-surface p-3 text-sm leading-6 outline-none transition focus:border-primary"
        :value="modelValue.sentenceTranslation"
        :disabled="saving"
        @input="event => update('sentenceTranslation', event.target.value)"
      />
      <div class="grid gap-3 lg:grid-cols-2">
        <div class="grid gap-2">
          <label class="text-xs font-medium text-muted">英文分块</label>
          <textarea
            class="sentence-editor-segments min-h-20 w-full resize-y rounded-md border border-border bg-surface p-3 text-sm leading-6 outline-none transition focus:border-primary"
            placeholder="The thought / of holding a fixed grin / became the norm."
            :value="modelValue.sentenceSegmentsText"
            :disabled="saving"
            @input="event => update('sentenceSegmentsText', event.target.value)"
          />
        </div>
        <div class="grid gap-2">
          <label class="text-xs font-medium text-muted">中文分块</label>
          <textarea
            class="sentence-editor-segments min-h-20 w-full resize-y rounded-md border border-border bg-surface p-3 text-sm leading-6 outline-none transition focus:border-primary"
            placeholder="这个想法 / 即保持固定笑容 / 成了常态。"
            :value="modelValue.translationSegmentsText"
            :disabled="saving"
            @input="event => update('translationSegmentsText', event.target.value)"
          />
        </div>
      </div>
      <label class="text-xs font-medium text-muted">单词释义</label>
      <textarea
        class="min-h-24 w-full resize-y rounded-md border border-border bg-surface p-3 font-mono text-xs leading-5 outline-none transition focus:border-primary"
        placeholder="word=释义"
        :value="modelValue.translationsText"
        :disabled="saving"
        @input="event => update('translationsText', event.target.value)"
      />
      <label class="text-xs font-medium text-muted">单词提示</label>
      <textarea
        class="min-h-20 w-full resize-y rounded-md border border-border bg-surface p-3 font-mono text-xs leading-5 outline-none transition focus:border-primary"
        placeholder="word=提示"
        :value="modelValue.tipsText"
        :disabled="saving"
        @input="event => update('tipsText', event.target.value)"
      />
      <div class="flex justify-end">
        <button
          type="button"
          :disabled="saving || !String(modelValue.text || '').trim()"
          class="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-60"
          @click="emit('submit')"
        >
          <Check class="h-4 w-4" />
          {{ saving ? '保存中' : submitLabel }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Check, Sparkles } from '@lucide/vue'
import RichMarkedTextEditor from './RichMarkedTextEditor.vue'

const props = defineProps({
  modelValue: { type: Object, required: true },
  saving: { type: Boolean, default: false },
  translating: { type: Boolean, default: false },
  submitLabel: { type: String, default: '保存' }
})
const emit = defineEmits(['update:modelValue', 'translate', 'submit'])

function update(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<style scoped>
.sentence-editor-segments,
.sentence-editor-translation {
  --english-reading-font: Georgia, "Arial Hebrew", "Noto Sans Hebrew", "Times New Roman",
    Times, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "PingFang TC",
    "Microsoft JhengHei", "Noto Sans CJK TC", "Hiragino Sans", "Yu Gothic", Meiryo,
    "Noto Sans CJK JP", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", serif;
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}
</style>
