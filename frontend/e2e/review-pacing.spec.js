import { test, expect } from '@playwright/test'
import { mockStudy } from './fixtures.js'

test('round pacing is a cumulative reminder and keeps review available when ahead', async ({ page }, testInfo) => {
  await page.clock.install({ time: new Date('2026-09-15T02:00:00Z') })
  const state = await mockStudy(page, {
    scheduledCount: 1041,
    completedCount: 117,
    startedAt: '2026-09-10T00:00:00+00:00',
    expiresAt: '2026-09-21T00:00:00+00:00'
  })
  await page.goto('/')
  const summary = page.locator('.review-progress-summary')
  const pacing = summary.locator('.review-round-pacing')
  await expect(pacing).toContainText('第 6 / 11 天')
  await expect(pacing).toContainText('日均 95 项')
  await expect(pacing).toContainText('截至今日应完成 568 项')
  await expect(summary).toContainText('本轮 117 / 1041')
  await expect(pacing).toContainText('还差 451 项')
  await expect(page.getByText('进度仅供参考，可以自由多做或少做。', { exact: true })).toHaveCount(0)
  expect(await page.locator('.english-workspace').evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('review-pacing.png') })

  await page.locator('.english-review-card').first().getByRole('button', { name: '完成并下一句', exact: true }).click()
  await expect(summary).toContainText('本轮 118 / 1041')
  await expect(pacing).toContainText('还差 450 项')

  // Simulate progress from another session, then refresh the existing queue.
  for (let index = 0; index < 600; index += 1) state.completed.add(1000 + index)
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(pacing).toContainText('超前 32 项')
  const next = page.locator('.english-review-card').first()
  await expect(next.getByRole('heading', { name: '本轮第 601 句', exact: true })).toBeVisible()
  await next.getByRole('button', { name: '完成并下一句', exact: true }).click()
  await expect(summary).toContainText('本轮 601 / 1041')
  await expect(pacing).toContainText('超前 33 项')

  // A page kept open over Beijing 08:00 updates the reminder automatically.
  await page.clock.fastForward('22:00:01')
  await expect(pacing).toContainText('第 7 / 11 天')
  await expect(pacing).toContainText('截至今日应完成 663 项')
  await expect(pacing).toContainText('还差 62 项')
  expect(state.unhandled).toEqual([])
})
