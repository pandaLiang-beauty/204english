<template>
  <span v-if="pacing" class="review-round-pacing contents">
    <span>第 {{ pacing.day }} / {{ pacing.days }} 天</span>
    <span>日均 {{ pacing.dailyAverage }} 项</span>
    <span>截至今日应完成 <strong class="font-semibold text-text">{{ pacing.target }}</strong> 项</span>
    <span v-if="pacing.behind">还差 <strong class="font-semibold text-text">{{ pacing.behind }}</strong> 项</span>
    <span v-else-if="pacing.ahead" class="text-primary">超前 {{ pacing.ahead }} 项</span>
    <span v-else class="text-primary">已达进度</span>
  </span>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { nextStudyDayAt, reviewRoundPacing } from './reviewRoundPacing.js'

const props = defineProps({ round: { type: Object, required: true } })
const now = ref(Date.now())
const pacing = computed(() => reviewRoundPacing(props.round, now.value))
let timer = null

function refreshClock() {
  now.value = Date.now()
  window.clearTimeout(timer)
  timer = window.setTimeout(refreshClock, nextStudyDayAt(now.value) - now.value + 100)
}

onMounted(() => {
  refreshClock()
  document.addEventListener('visibilitychange', refreshClock)
  window.addEventListener('focus', refreshClock)
})

onBeforeUnmount(() => {
  window.clearTimeout(timer)
  document.removeEventListener('visibilitychange', refreshClock)
  window.removeEventListener('focus', refreshClock)
})
</script>
