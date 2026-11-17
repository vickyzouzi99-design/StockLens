import { test, expect } from '@playwright/test'

test('centered login promotion yields to footer in short windows',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'})
  await page.goto('/')
  await expect(page.getByRole('button',{name:'账号登录',exact:true})).toBeVisible()
  for(const [width,height] of [[1440,900],[1280,600],[1280,500],[768,650],[390,740]]) {
    await page.setViewportSize({width,height})
    for(const register of [false,true]) {
      await page.getByRole('button',{name:register?'使用邀请码注册':'账号登录',exact:true}).click()
      await page.evaluate(()=>window.scrollTo({top:document.body.scrollHeight,behavior:'instant'}))
      await expect.poll(async()=>{
        const story=await page.locator('.auth-story').boundingBox()
        const footer=await page.locator('.site-footer').boundingBox()
        return footer!.y-story!.y-story!.height
      }).toBeGreaterThanOrEqual(20)
      expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
      await page.screenshot({path:`../artifacts/login-footer-${width}x${height}-${register?'register':'login'}.png`})
    }
  }
})
