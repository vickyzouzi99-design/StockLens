import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const credentials = JSON.parse(readFileSync('../artifacts/ai-review.json', 'utf8'))
test('both providers propose optional contextual indicators without enabling them', async ({page}) => {
  test.setTimeout(150000)
  await page.emulateMedia({reducedMotion:'reduce'})
  await page.goto('/')
  await page.getByLabel('用户名',{exact:true}).fill(credentials.username)
  await page.getByLabel('密码',{exact:true}).fill(credentials.password)
  await page.getByRole('button',{name:'登录工作台',exact:true}).click()
  await expect(page.getByLabel('打开账号菜单')).toBeVisible()
  page.on('dialog',dialog=>dialog.accept())
  let calls = 0
  page.on('request',request=>{if(request.url().endsWith('/api/interpret')) calls++})
  for (const [index,provider] of ['openai','deepseek'].entries()) {
    if(index) await page.getByRole('button',{name:'修改需求 / AI 服务',exact:true}).click()
    await page.getByLabel('描述你的选股需求').fill('找市盈率不超过30倍、利润同比增长至少10%的股票。请根据这个需求建议其他补充指标。')
    await page.getByLabel('AI 服务',{exact:true}).selectOption(provider)
    const responsePromise = page.waitForResponse(response=>response.url().endsWith('/api/interpret'),{timeout:65000})
    await page.getByRole('button',{name:index?'重新解析需求':'解析选股需求',exact:true}).click()
    const response = await responsePromise
    expect(response.status()).toBe(200)
    const data = await response.json()
    expect(data.active_metrics.sort()).toEqual(['pe_max','profit_min'])
    expect(data.parameters.pe_max).toBe(30)
    expect(data.parameters.profit_min).toBe(10)
    expect(data.suggestions.length).toBeGreaterThan(0)
    await expect(page.locator('.condition-card')).toHaveCount(2)
    await expect(page.locator('.ai-suggestions')).toBeVisible()
    const suggestion = data.suggestions[0]
    expect(data.parameters[suggestion.metric]).toBeNull()
    await page.locator('.ai-suggestions article').first().getByRole('button',{name:'加入指标'}).click()
    await expect(page.locator('.condition-card')).toHaveCount(3)
    await expect(page.locator(`#metric-${suggestion.metric}`)).toHaveValue('')
    await expect(page.getByText('AI 补充 · 由你加入',{exact:true})).toBeVisible()
    expect(calls).toBe(index+1)
    await page.screenshot({path:`../artifacts/ai-review-${provider}.png`,fullPage:true})
    console.log(`${provider}: original thresholds preserved; optional suggestions=${data.suggestions.length}; adding suggestion made no extra AI request`)
  }
})
