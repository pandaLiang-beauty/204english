const STUDY_DAY_MS = 24 * 60 * 60 * 1000

export function reviewRoundPacing(round, now = Date.now()) {
  const total = Math.max(0, Number(round?.total || 0))
  const startedAt = Date.parse(String(round?.started_at || ''))
  const expiresAt = Date.parse(String(round?.expires_at || ''))
  if (!total || !Number.isFinite(startedAt) || !Number.isFinite(expiresAt) || expiresAt <= startedAt) return null

  const days = Math.max(1, Math.ceil((expiresAt - startedAt) / STUDY_DAY_MS))
  // UTC midnight is Beijing 08:00, independent of the device's time zone.
  const elapsedDays = Math.floor(now / STUDY_DAY_MS) - Math.floor(startedAt / STUDY_DAY_MS)
  const day = now < startedAt ? 0 : Math.min(days, Math.max(1, elapsedDays + 1))
  const target = Math.min(total, Math.ceil(total * day / days))
  const completed = Math.min(total, Math.max(0, Number(round?.completed || 0)))
  return {
    days,
    day,
    dailyAverage: Math.ceil(total / days),
    target,
    completed,
    behind: Math.max(0, target - completed),
    ahead: Math.max(0, completed - target)
  }
}

export function nextStudyDayAt(now = Date.now()) {
  return (Math.floor(now / STUDY_DAY_MS) + 1) * STUDY_DAY_MS
}
