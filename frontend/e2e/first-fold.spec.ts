import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const credentials = JSON.parse(readFileSync('../artifacts/ai-review.json', 'utf8'))
test('prominent login workflow and complete composer boundary note in first viewport', async ({page}) => {
  await page.goto('/')
  await expect(page.getByRole('button',{name:'登录工作台',exact:true})).toBeVisible()
  for(const [width,height] of [[1440,900],[1280,800],[768,1024],[390,844]]) {
    await page.setViewportSize({width,height})
    const flow = page.getByRole('navigation',{name:'选股流程'})
    await expect(flow).toBeVisible()
    const box = await flow.boundingBox()
    const card = await page.locator('.auth-card').boundingBox()
    if(width>=768) {
      const story = await page.locator('.auth-story').boundingBox()
      expect(Math.abs(story!.y+story!.height/2-(height/2+32))).toBeLessThan(2)
      await page.evaluate(()=>window.scrollTo(0,200))
      const scrolled=await page.locator('.auth-story').boundingBox()
      expect(Math.abs(scrolled!.y-story!.y)).toBeLessThan(2)
      await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}))
    } else expect(box!.y).toBeLessThan(card!.y)
    expect(await flow.evaluate(node=>Number.parseFloat(getComputedStyle(node).fontSize))).toBeGreaterThanOrEqual(14)
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({path:`../artifacts/login-workflow-${width}.png`,fullPage:true})
  }
  await page.getByLabel('用户名',{exact:true}).fill(credentials.username)
  await page.getByLabel('密码',{exact:true}).fill(credentials.password)
  await page.getByRole('button',{name:'登录工作台',exact:true}).click()
  await expect(page.getByLabel('打开账号菜单')).toBeVisible()
  await expect(page.getByText('AI 不生成股票数据，不直接给出买卖建议',{exact:true})).toBeInViewport({ratio:1})
  for(const [width,height] of [[1440,900],[1280,800],[1280,600],[1280,500],[768,1024],[390,844],[390,740]]) {
    await page.setViewportSize({width,height})
    await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}))
    const hint = page.getByText('AI 不生成股票数据，不直接给出买卖建议',{exact:true})
    await expect(hint).toBeInViewport({ratio:1})
    const box = await hint.boundingBox()
    expect(box!.y+box!.height).toBeLessThanOrEqual(height)
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    if(width>=1280) {
      const title = await page.locator('.composer-title').boundingBox()
      const examples = await page.locator('.composer-topline .examples').boundingBox()
      expect(Math.abs((title!.y+title!.height/2)-(examples!.y+examples!.height/2))).toBeLessThan(2)
      expect(examples!.x).toBeGreaterThan(title!.x+title!.width)
    }
    await page.screenshot({path:`../artifacts/first-fold-${width}x${height}.png`})
  }
  let aiCalls=0
  page.on('request',request=>{if(request.url().endsWith('/api/interpret')) aiCalls++})
  await page.getByRole('button',{name:/只看低估值/}).click()
  await expect(page.getByLabel('描述你的选股需求')).toHaveValue('我想找市场估值偏低的股票')
  expect(aiCalls).toBe(0)
})
