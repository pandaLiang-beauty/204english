import { test, expect } from '@playwright/test'
import { mockStudy } from './fixtures.js'

test('day and night modes persist and system mode follows the device', async ({ page }) => {
  await mockStudy(page)
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/')
  await page.getByRole('button', { name: '夜间', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.getByRole('button', { name: '日间', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.getByRole('button', { name: '跟随系统', exact: true }).click()
  await page.emulateMedia({ colorScheme: 'dark' })
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
})

test('listening, translation, completion and repeated items keep separate meanings', async ({ page }) => {
  const state = await mockStudy(page)
  await page.goto('/')
  await expect(page.locator('.review-card')).toHaveCount(1)
  await expect(page.locator('.full-translation')).toHaveCount(0)
  await page.getByRole('button', { name: '听整句', exact: true }).click()
  await expect.poll(() => state.events.length).toBe(1)
  expect(state.events[0].complete_round_item).toBe(false)
  expect(state.completed.size).toBe(0)
  await page.getByRole('button', { name: /看译文/ }).click()
  await expect(page.locator('.full-translation')).toContainText('真正的理解')
  await page.getByRole('button', { name: /完成本次/ }).click()
  await expect.poll(() => state.completed.has(1000)).toBe(true)
  await expect(page.locator('.review-sentence')).toContainText('adapt')
  expect(state.completed.has(1012)).toBe(false)
  await page.getByRole('button', { name: '列表浏览', exact: true }).click()
  await expect(page.locator('.review-card')).toHaveCount(20)
  await page.getByRole('navigation', { name: '复习安排翻页' }).getByRole('button', { name: '下一页' }).click()
  await expect(page.locator('.review-card')).toHaveCount(2)
  expect(state.unhandled).toEqual([])
})

test('article selection, autosave, adding sentences and completing reading work', async ({ page }, testInfo) => {
  const state = await mockStudy(page)
  await page.goto('/passages')
  if (testInfo.project.name === 'phone') await page.locator('.today-passage').first().click()
  const reader = page.getByRole('textbox', { name: '文章正文与重点标注' })
  await expect(reader).toBeVisible()
  await reader.press('ControlOrMeta+End')
  await reader.press('End')
  await reader.press('Enter')
  await reader.pressSequentially('A new reading note.')
  await expect.poll(() => state.passages[0].body_text).toContain('A new reading note.')
  await expect(page.locator('.passage-save-state')).toHaveText('已保存')
  await page.getByRole('button', { name: /加入句库 ·/ }).click()
  await expect(page.locator('.selected-sentences .status-message')).toContainText('已加入句库 2 句')
  await expect(reader).toContainText('A new reading note.')
  await page.getByRole('button', { name: '读完这篇', exact: true }).click()
  await expect.poll(() => state.passages[0].status).toBe('done')
  expect(state.unhandled).toEqual([])
})

test('sentence creation failures preserve input and a retry saves successfully', async ({ page }) => {
  const state = await mockStudy(page)
  state.failCreate = true
  await page.goto('/create')
  const input = page.getByRole('textbox', { name: '在这里输入或粘贴英文句子…' })
  await input.fill('A sentence worth returning to.')
  await page.getByRole('button', { name: '加入我的句库', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('保存暂时失败')
  await expect(input).toHaveText('A sentence worth returning to.')
  state.failCreate = false
  await page.getByRole('button', { name: '加入我的句库', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已保存到句库')
  expect(state.sentences[0].text).toBe('A sentence worth returning to.')
})

test('all main screens fit the viewport in both themes without runtime errors', async ({ page }, testInfo) => {
  test.setTimeout(60000)
  const state = await mockStudy(page)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const theme of ['light', 'dark']) {
    for (const [name, path] of [['review', '/'], ['library', '/library'], ['passages', '/passages'], ['create', '/create'], ['stats', '/stats']]) {
      await page.goto(path)
      await expect(page.locator('.workspace-header h1')).toBeVisible()
      await page.getByRole('button', { name: theme === 'light' ? '日间' : '夜间', exact: true }).click()
      if (name === 'review') await expect(page.locator('.review-card')).toBeVisible()
      if (name === 'library') await expect(page.locator('.library-row').first()).toBeVisible()
      if (name === 'passages' && testInfo.project.name === 'phone') await page.locator('.today-passage').first().click()
      await page.evaluate(() => document.fonts.ready)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `${name} ${theme} overflows`).toBe(true)
      await page.screenshot({ path: testInfo.outputPath(`${name}-${theme}.png`), fullPage: true, animations: 'disabled' })
      if (name === 'stats') {
        await page.getByRole('button', { name: '阅读与声音', exact: true }).click()
        await expect(page.locator('.audio-preferences')).toBeVisible()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `settings ${theme} overflows`).toBe(true)
        await page.screenshot({ path: testInfo.outputPath(`settings-${theme}.png`), fullPage: true, animations: 'disabled' })
      }
    }
  }
  expect(errors).toEqual([])
  expect(state.unhandled).toEqual([])
})

test('login offers day and night modes and opens the learning space', async ({ page }, testInfo) => {
  await mockStudy(page)
  await page.route('**/api/auth/me', route => route.fulfill({ status: 401, json: { detail: '请登录' } }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '继续你的学习' })).toBeVisible()
  await page.getByRole('button', { name: '夜间', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.screenshot({ path: testInfo.outputPath('login-dark.png'), fullPage: true })
  await page.getByLabel('登录密码', { exact: true }).fill('isolated-test-password')
  await page.getByRole('button', { name: '进入学习空间', exact: true }).click()
  await expect(page.locator('.review-card')).toBeVisible()
})

test('a word meaning can be edited through labeled fields and saved', async ({ page }) => {
  const state = await mockStudy(page)
  await page.goto('/library')
  await page.getByRole('button', { name: '查看句子 1 的详情', exact: true }).click()
  await page.getByRole('button', { name: '编辑句子', exact: true }).click()
  await page.locator('.editor-details > summary').click()
  await page.getByLabel('词义', { exact: true }).fill('联系；知识之间的关联')
  await page.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect.poll(() => state.sentences[0].word_translations.connections).toBe('联系；知识之间的关联')
  expect(state.sentences[0].text).toContain('**connections**')
})

test('small phones keep navigation and reading controls inside the viewport', async ({ page }) => {
  await mockStudy(page)
  await page.setViewportSize({ width: 320, height: 720 })
  await page.goto('/')
  await expect(page.locator('.review-card')).toBeVisible()
  await expect(page.locator('.navigation-add')).not.toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  for (const button of await page.locator('.review-actions button').all()) {
    const box = await button.boundingBox()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(320)
  }
  await page.goto('/stats')
  await page.getByRole('button', { name: '阅读与声音', exact: true }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
})

test('logging out cannot silently discard an unfinished sentence draft', async ({ page }) => {
  await mockStudy(page)
  await page.goto('/create')
  const input = page.getByRole('textbox', { name: '在这里输入或粘贴英文句子…' })
  await input.fill('Keep my unfinished sentence.')
  page.once('dialog', dialog => dialog.dismiss())
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(input).toHaveText('Keep my unfinished sentence.')
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '继续你的学习' })).toBeVisible()
})
