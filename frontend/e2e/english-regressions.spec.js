import { test, expect } from '@playwright/test'
import { mockStudy } from './fixtures.js'

const nav = (page, label) => page.getByRole('navigation', { name: '英语复习导航' }).getByRole('button', { name: label, exact: true })
const firstArticle = page => page.locator('.english-workspace article').first()
const unloadIsProtected = page => page.evaluate(() => {
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  return event.defaultPrevented
})

test('sentence drafts survive mode changes and browser history, with leave protection until saved', async ({ page }) => {
  const state = await mockStudy(page)
  await page.goto('/library')
  await firstArticle(page).getByTitle('编辑句子', { exact: true }).click()
  const translation = firstArticle(page).locator('.sentence-editor-translation')
  await translation.fill('切换页面后继续编辑的译文。')
  expect(await unloadIsProtected(page)).toBe(true)
  await nav(page, '统计').click()
  await expect(page).toHaveURL(/\/stats$/)
  expect(await unloadIsProtected(page)).toBe(true)
  await page.goBack()
  await expect(page).toHaveURL(/\/library$/)
  await expect(translation).toHaveValue('切换页面后继续编辑的译文。')
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await expect(translation).toHaveValue('切换页面后继续编辑的译文。')
  expect(state.requests.filter(request => request.method === 'PUT')).toHaveLength(0)
  const dialogSeen = page.waitForEvent('dialog')
  const logout = page.getByRole('button', { name: '退出', exact: true }).click()
  const dialog = await dialogSeen
  expect(dialog.message()).toContain('未保存的句子修改')
  await dialog.dismiss()
  await logout
  await expect(translation).toHaveValue('切换页面后继续编辑的译文。')
  expect(state.requests.some(request => request.path === '/api/auth/logout')).toBe(false)
  await firstArticle(page).getByRole('button', { name: '保存修改', exact: true }).click()
  await expect.poll(() => state.sentences[0].sentence_translation).toBe('切换页面后继续编辑的译文。')
  await expect(translation).toBeHidden()
  expect(await unloadIsProtected(page)).toBe(false)
  expect(state.unhandled).toEqual([])
})

test('completion retry restores the round count when the first response is lost', async ({ page }) => {
  const state = await mockStudy(page)
  let attempts = 0
  await page.route('**/api/english/sentences/1/review', async route => {
    const payload = route.request().postDataJSON()
    state.completed.add(payload.round_item_id)
    if (++attempts === 1) return route.abort('failed')
    return route.fulfill({ json: {
      ...state.sentences[0], review_round_item_id: payload.round_item_id,
      review_round_item_completed: false, review_round_item_is_completed: true,
      review_round_completed: false, review_round: { id: 11, total: 22, completed: 1, remaining: 21, is_completed: false }
    } })
  })
  await page.goto('/')
  const first = page.locator('.english-review-card').first()
  await first.getByRole('button', { name: '完成并下一句', exact: true }).click()
  await expect(first.getByRole('button', { name: '完成并下一句', exact: true })).toBeEnabled()
  await expect(page.locator('.review-progress-summary')).toContainText('0 / 22')
  await first.getByRole('button', { name: '完成并下一句', exact: true }).click()
  await expect(page.locator('.review-progress-summary')).toContainText('1 / 22')
  expect(state.completed.size).toBe(1)
  expect(attempts).toBe(2)
})

test('passage candidate count keeps decimals and abbreviations within their sentences', async ({ page }) => {
  const state = await mockStudy(page)
  state.passages[0].body_text = 'The **CEO** earns $18.9 million. Dr. Smith is **hiring** in the U.S. this year.'
  await page.goto('/passages')
  await expect(page.locator('.passage-annotator')).toContainText('$18.9 million')
  await page.getByRole('button', { name: '同步 2 句', exact: true }).last().click()
  await expect.poll(() => state.passages[0].selected_sentence_ids.length).toBe(2)
  expect(state.requests.find(request => request.path.endsWith('/sync-sentences')).payload.candidate_indexes).toEqual([0, 1])
})
