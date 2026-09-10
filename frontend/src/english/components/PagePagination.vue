<template>
  <nav class="page-pagination" :aria-label="label">
    <button type="button" class="ui-button" :disabled="page <= 1 || loading" @click="$emit('change', -1)"><ChevronLeft />上一页</button>
    <span>第 {{ page }} / {{ pageCount }} 页<span v-if="total !== null" class="hidden sm:inline"> · {{ total }} {{ unit }}</span></span>
    <button type="button" class="ui-button" :disabled="page >= pageCount || loading" @click="$emit('change', 1)">下一页<ChevronRight /></button>
  </nav>
</template>
<script setup>
import { ChevronLeft, ChevronRight } from '@lucide/vue'
defineProps({
  page: { type: Number, required: true }, pageCount: { type: Number, required: true },
  loading: Boolean, total: { type: Number, default: null }, unit: { type: String, default: '句' },
  label: { type: String, default: '列表翻页' }
})
defineEmits(['change'])
</script>
