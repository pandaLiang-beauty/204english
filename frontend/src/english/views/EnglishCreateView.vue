<template>
  <section class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
    <main class="grid min-w-0 gap-4 lg:grid-cols-2">
      <section class="rounded-lg border border-border bg-surface p-4">
        <div class="mb-3 flex items-center justify-between gap-3">
          <h2 class="text-sm font-semibold text-text">单句新增</h2>
          <span class="text-xs text-muted tabular-nums">当前 {{ stats.active ?? total }} 句</span>
        </div>
        <SentenceEditor
          :model-value="draft"
          :saving="saving"
          :translating="translatingDraft"
          submit-label="保存句子"
          @update:model-value="emit('update:draft', $event)"
          @translate="emit('translate')"
          @submit="emit('submit')"
        />
        <p v-if="error" class="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{{ error }}</p>
      </section>

      <section class="rounded-lg border border-border bg-surface p-4">
        <div class="mb-3 flex items-center justify-between gap-3">
          <h2 class="text-sm font-semibold text-text">批量导入</h2>
          <div class="flex gap-2">
            <button
              type="button"
              class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted transition hover:bg-surface-2 hover:text-text disabled:opacity-50"
              :disabled="bulkLoading"
              title="清空"
              @click="emit('reset-bulk')"
            >
              <RotateCcw class="h-4 w-4" />
            </button>
            <button
              type="button"
              class="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground disabled:opacity-60"
              :disabled="bulkLoading || !bulkSentences.length"
              @click="emit('submit-bulk')"
            >
              <Upload class="h-4 w-4" />
              {{ bulkLoading ? '导入中' : '导入' }}
            </button>
          </div>
        </div>
        <textarea
          :value="bulkText"
          class="min-h-[24rem] w-full resize-y rounded-md border border-border bg-bg p-3 text-sm leading-6 outline-none transition focus:border-primary"
          placeholder="Sentence one&#10;&#10;Sentence two"
          @input="updateBulkText"
        />
        <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span>
            已识别 <span class="font-semibold tabular-nums text-text">{{ bulkSentences.length }}</span> 条
          </span>
          <span v-if="bulkMessage" class="text-primary">{{ bulkMessage }}</span>
        </div>
      </section>
    </main>

    <aside class="grid content-start gap-4 xl:sticky xl:top-4">
      <section class="rounded-lg border border-border bg-surface p-4">
        <div class="flex items-center justify-between gap-3">
          <h2 class="text-sm font-semibold text-text">最近添加</h2>
          <span class="text-xs text-muted tabular-nums">{{ sentences.length }}</span>
        </div>
        <div v-if="loading" class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
          加载中
        </div>
        <div v-else-if="sentences.length" class="mt-3 grid gap-2">
          <div
            v-for="sentence in sentences"
            :key="sentence.id"
            class="rounded-md border border-border bg-bg px-3 py-2"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="text-xs font-semibold tabular-nums text-muted">#{{ sentence.id }}</div>
              <div class="text-[11px] text-muted">{{ focusWordCount(sentence) }} 词</div>
            </div>
            <div class="mt-1 line-clamp-2 text-sm leading-5 text-text">
              {{ plainSentenceText(sentence.text) }}
            </div>
          </div>
        </div>
        <div v-else class="mt-3 rounded-md border border-border bg-bg px-3 py-4 text-center text-sm text-muted">
          暂无句子
        </div>
      </section>

      <section class="rounded-lg border border-border bg-surface p-4">
        <h2 class="text-sm font-semibold text-text">语料状态</h2>
        <dl class="mt-3 grid gap-2 text-sm">
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">有效句子</dt>
            <dd class="font-semibold tabular-nums">{{ stats.active ?? '-' }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">有音频</dt>
            <dd class="font-semibold tabular-nums">{{ stats.with_audio ?? '-' }}</dd>
          </div>
          <div class="flex items-center justify-between gap-3">
            <dt class="text-muted">跨句关联词</dt>
            <dd class="font-semibold tabular-nums">{{ stats.word_network?.cross_sentence_words ?? 0 }}</dd>
          </div>
        </dl>
      </section>
    </aside>
  </section>
</template>

<script setup>
import { RotateCcw, Upload } from '@lucide/vue'
import SentenceEditor from '../SentenceEditor.vue'
import { focusWordCount, plainSentenceText } from '../sentencePresentation.js'

defineProps({
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
</script>
