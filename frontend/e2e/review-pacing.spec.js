import { test, expect } from '@playwright/test'
import { mockStudy } from './fixtures.js'

test('round pacing is a cumulative reminder and keeps review available when ahead', async ({ page }, testInfo) => {
  await page.clock.install({ time: new Date('2026-09-15T02:00:00Z') })
  const state = await mockStudy(page, {
    scheduledCount: 710,
    completedCount: 117,
    startedAt: '2026-09-10T00:00:00+00:00',
    expiresAt: '2026-09-18T00:00:00+00:00'
  })
  await page.goto('/')
  const summary = page.locator('.review-progress-summary')
  const pacing = summary.locator('.review-round-pacing')
  await expect(pacing).toContainText('第 6 / 8 天')
  await expect(pacing).toContainText('日均 89 项')
  await expect(pacing).toContainText('截至今日应完成 533 项')
  await expect(summary).toContainText('本轮 117 / 710')
  await expect(pacing).toContainText('还差 416 项')
  await expect(page.getByText('进度仅供参考，可以自由多做或少做。', { exact: true })).toHaveCount(0)
  expect(await page.locator('.english-workspace').evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('review-pacing.png') })

  await page.locator('.english-review-card').first().getByRole('button', { name: '完成并下一句', exact: true }).click()
  await expect(summary).toContainText('本轮 118 / 710')
  await expect(pacing).toContainText('还差 415 项')

  // Simulate progress from another session, then refresh the existing queue.
  for (let index = 0; index < 600; index += 1) state.completed.add(1000 + index)
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(pacing).toContainText('超前 67 项')
  const next = page.locator('.english-review-card').first()
  await expect(next.getByRole('heading', { name: '本轮第 601 句', exact: true })).toBeVisible()
  await next.getByRole('button', { name: '完成并下一句', exact: true }).click()
  await expect(summary).toContainText('本轮 601 / 710')
  await expect(pacing).toContainText('超前 68 项')

  // A page kept open over Beijing 08:00 updates the reminder automatically.
  await page.clock.fastForward('22:00:01')
  await expect(pacing).toContainText('第 7 / 8 天')
  await expect(pacing).toContainText('截至今日应完成 622 项')
  await expect(pacing).toContainText('还差 21 项')
  expect(state.unhandled).toEqual([])
})
