import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { makeSnapshot, metricKeys } from '../src/strategies'

const credentials = JSON.parse(readFileSync('../artifacts/ai-review.json', 'utf8'))
test('screening defaults to matching rows, permits all rows and preserves zero-match state', async ({ page }) => {
  let aiCalls = 0
  page.on('request', request => { if (request.url().endsWith('/api/interpret')) aiCalls++ })
  await page.goto('/')
  await page.getByLabel('用户名', { exact: true }).fill(credentials.username)
  await page.getByLabel('密码', { exact: true }).fill(credentials.password)
  await page.getByRole('button', { name: '登录工作台', exact: true }).click()
  await expect(page.getByLabel('AI 服务', { exact: true })).toHaveValue('deepseek')
  const library = await (await page.request.get('/api/account/strategies')).json()
  const draft = Object.fromEntries(metricKeys.map(key => [key, key === 'pe_max' ? '30' : ''])) as Record<typeof metricKeys[number], string>
  const now = new Date().toISOString()
  const name = '默认符合列表-' + Date.now()
  const item = { schemaVersion: 2, id: name, name, query: '市盈率不超过30倍', provider: 'deepseek', createdAt: now, updatedAt: now,
    snapshot: makeSnapshot(draft, ['pe_max'], null) }
  expect((await page.request.put('/api/account/strategies', { data: { revision: library.revision, items: [...library.items, item] } })).ok()).toBeTruthy()
  await page.getByLabel('打开账号菜单').click()
  await page.getByRole('button', { name: '我的策略', exact: true }).click()
  await page.locator('.strategy-drawer article').filter({ has: page.getByRole('heading', { name, exact: true }) }).getByRole('button', { name: '载入并编辑' }).click()
  const response = page.waitForResponse(r => r.url().endsWith('/api/screen'))
  await page.getByRole('button', { name: '确认并执行筛选', exact: true }).click()
  const result = await (await response).json()
  expect(result.summary.selected).toBeGreaterThan(0)
  await expect(page.locator('.filter-button.active')).toContainText('符合')
  await expect(page.locator('.stock-table tbody tr')).toHaveCount(result.summary.selected)
  await page.locator('.filter-group button').filter({ hasText: /^全部/ }).click()
  await expect(page.locator('.stock-table tbody tr')).toHaveCount(result.results.length)
  await page.locator('#metric-pe_max').fill('0.000001')
  await page.getByRole('button', { name: '按当前条件重新筛选', exact: true }).click()
  await expect(page.locator('.filter-group button[aria-pressed=true]')).toContainText('符合')
  await expect(page.locator('.stock-table tbody tr')).toHaveCount(0)
  await expect(page.locator('.no-rows')).toContainText('本次没有符合全部条件的股票')
  expect(aiCalls).toBe(0)
})
