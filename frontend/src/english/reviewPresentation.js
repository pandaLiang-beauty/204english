export function roundProgress(round) {
  const total = Number(round?.total || 0)
  return total ? Math.min(100, Math.max(0, Number(round?.completed || 0) / total * 100)) : 0
}

export function beijingTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).format(date)
}
