import { computed, ref } from 'vue'
import { englishApi } from './api.js'

export function useEnglishActivity(context = {}) {
  const stats = ref({})
  const heatmap = ref(null)
  let requestRevision = 0
  const weakNetworkWords = computed(() => stats.value?.word_network?.weak_words || [])
  const legacyReviewTotal = computed(() => heatmap.value?.legacy_total_reviews ?? stats.value?.legacy?.total_reviews ?? 0)
  const heatmapDays = computed(() => heatmap.value?.days || [])
  const heatmapCells = computed(() => {
    const days = heatmapDays.value
    if (!days.length) return []
    const leading = Number(days[0]?.weekday || 0)
    return [...Array.from({ length: leading }, () => null), ...days]
  })
  const heatmapColumns = computed(() => Math.max(1, Math.ceil(heatmapCells.value.length / 7)))
  function heatCellClass(day, size = 'normal') {
    const base = `${size === 'large' ? 'h-3.5 w-3.5' : 'h-3 w-3'} rounded-[3px] border`
    if (!day) return `${base} border-transparent`
    const count = Number(day.total || 0)
    const max = Number(heatmap.value?.max_count || 0)
    if (count <= 0 || max <= 0) return `${base} border-border bg-surface`
    const ratio = count / max
    if (ratio >= 0.75) return `${base} border-primary bg-primary`
    if (ratio >= 0.45) return `${base} border-primary/70 bg-primary/70`
    if (ratio >= 0.2) return `${base} border-primary/40 bg-primary/40`
    return `${base} border-primary/20 bg-primary/20`
  }

  function heatCellTitle(day) {
    if (!day) return ''
    return `${day.date} · ${day.total || 0} 次 · 整句 ${day.sentence_reviews || 0} · 单词 ${day.word_reviews || 0}`
  }

  async function fetchActivity({ includeHeatmap = false } = {}) {
    const revision = ++requestRevision
    const statsRequest = englishApi.stats({
      includeWordNetwork: !context.isReview?.()
    })
    if (includeHeatmap) {
      const [statsResult, heatmapResult] = await Promise.all([
        statsRequest,
        englishApi.heatmap({ days: 119 })
      ])
      if (revision !== requestRevision) return
      stats.value = statsResult
      heatmap.value = heatmapResult
    } else {
      const result = await statsRequest
      if (revision === requestRevision) stats.value = result
    }
  }

  return {
    stats, heatmap, weakNetworkWords, legacyReviewTotal, heatmapCells, heatmapColumns,
    heatCellClass, heatCellTitle, fetchActivity,
    invalidateActivity: () => { requestRevision += 1 }
  }
}
