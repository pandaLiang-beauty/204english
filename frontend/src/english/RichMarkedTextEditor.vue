<template>
  <div class="grid gap-2">
    <div class="flex items-center justify-between gap-3">
      <span class="quiet-note">选中重点词，再点「标记重点」</span>
      <button
        type="button"
        :disabled="disabled"
        title="标记或取消重点 · Ctrl / ⌘ + B"
        class="ui-button small"
        @mousedown.prevent="toggleBold"
        @click="event => event.detail === 0 && toggleBold()"
      >
          <Bold class="h-4 w-4" />
          标记重点
      </button>
    </div>
    <div
      ref="editorEl"
      class="marked-text-editor sentence-editor-text ui-input w-full resize-y overflow-auto p-4 text-base leading-8"
      :class="[minHeightClass, disabled ? 'opacity-60' : '']"
      :contenteditable="disabled ? 'false' : 'true'"
      role="textbox"
      aria-multiline="true"
      :aria-label="placeholder || '英文句子'"
      spellcheck="false"
      :data-placeholder="placeholder"
      @input="emitMarkdown"
      @keydown="handleKeydown"
      @paste="handlePaste"
    />
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref, watch } from 'vue'
import { Bold } from '@lucide/vue'
import { editableElementToMarkdown, markedTextToEditableHtml } from './passageMarkdown'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  minHeightClass: { type: String, default: 'min-h-32' }
})
const emit = defineEmits(['update:modelValue'])

const editorEl = ref(null)

function updateEditorHtml(force = false) {
  const el = editorEl.value
  const activeElement = typeof document === 'undefined' ? null : document.activeElement
  if (!el || (!force && activeElement === el)) return
  const nextHtml = markedTextToEditableHtml(props.modelValue)
  if (el.innerHTML !== nextHtml) el.innerHTML = nextHtml
}

function emitMarkdown() {
  const el = editorEl.value
  if (!el) return
  emit('update:modelValue', editableElementToMarkdown(el))
}

function selectionInsideEditor() {
  const el = editorEl.value
  if (!el || typeof window === 'undefined') return false
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return false
  return el.contains(selection.anchorNode) && el.contains(selection.focusNode)
}

function toggleBold() {
  const el = editorEl.value
  if (!el || props.disabled || !selectionInsideEditor()) return
  el.focus()
  document.execCommand('bold', false)
  emitMarkdown()
}

function handleKeydown(event) {
  const key = String(event.key || '').toLowerCase()
  if ((event.ctrlKey || event.metaKey) && key === 'b') {
    event.preventDefault()
    if (event.repeat || event.isComposing) return
    toggleBold()
  }
}

function handlePaste(event) {
  event.preventDefault()
  const text = event.clipboardData?.getData('text/plain') || ''
  document.execCommand('insertText', false, text)
  emitMarkdown()
}

onMounted(() => updateEditorHtml(true))
watch(() => props.modelValue, () => nextTick(updateEditorHtml))
</script>

<style scoped>
.marked-text-editor {
  --english-reading-font: Georgia, "Arial Hebrew", "Noto Sans Hebrew", "Times New Roman",
    Times, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "PingFang TC",
    "Microsoft JhengHei", "Noto Sans CJK TC", "Hiragino Sans", "Yu Gothic", Meiryo,
    "Noto Sans CJK JP", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", serif;
  font-family: var(--english-reading-font);
  letter-spacing: 0;
}

.marked-text-editor:empty::before {
  content: attr(data-placeholder);
  color: var(--muted);
}

.marked-text-editor :deep(strong),
.marked-text-editor :deep(b) {
  border-radius: 0.25rem;
  background: color-mix(in srgb, var(--primary, #b85c38) 12%, transparent);
  padding: 0.02rem 0.28rem;
  color: var(--primary, #b85c38);
  font-weight: 700;
}
</style>
