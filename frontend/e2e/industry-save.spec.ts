import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { makeSnapshot, metricKeys } from '../src/strategies'

const credentials = JSON.parse(readFileSync('../artifacts/ai-review.json', 'utf8'))
test('six industries can be completed, saved, reloaded and edited without AI', async ({page}) => {
  await page.emulateMedia({reducedMotion:'reduce'})
  let calls=0
  page.on('request',request=>{if(request.url().endsWith('/api/interpret')) calls++})
  await page.goto('/')
  await page.getByLabel('用户名',{exact:true}).fill(credentials.username)
  await page.getByLabel('密码',{exact:true}).fill(credentials.password)
  await page.getByRole('button',{name:'登录工作台',exact:true}).click()
  await expect(page.getByLabel('打开账号菜单')).toBeVisible()
  const current = await (await page.request.get('/api/account/strategies')).json()
  const draft=Object.fromEntries(metricKeys.map(key=>[key,key==='pe_max'?'2':key==='vol_max'?'6':''])) as Record<typeof metricKeys[number],string>
  const now=new Date().toISOString()
  const suffix=Date.now()
  const originalName=`六行业保存验收-${suffix}`
  const savedName=`六行业新方案-${suffix}`
  const item={schemaVersion:2,id:'six-industry-'+suffix,name:originalName,query:'估值与波动条件',provider:'deepseek',createdAt:now,updatedAt:now,snapshot:makeSnapshot(draft,['pe_max','vol_max'],null)}
  expect((await page.request.put('/api/account/strategies',{data:{revision:current.revision,items:[...current.items,item]}})).ok()).toBeTruthy()
  await page.getByLabel('打开账号菜单').click()
  await page.getByRole('button',{name:'我的策略',exact:true}).click()
  await page.locator('.strategy-drawer article').filter({has:page.getByRole('heading',{name:originalName,exact:true})}).getByRole('button',{name:'载入并编辑'}).click()
  const names=['养殖业','农产品加工','化学制品','化学原料','医药商业','半导体']
  await page.getByLabel('选择行业',{exact:true}).click()
  for(const name of names) {
    await page.getByLabel('搜索行业',{exact:true}).fill(name)
    await page.getByRole('checkbox',{name:new RegExp('^'+name)}).check()
  }
  await page.getByRole('button',{name:'完成选择',exact:true}).click()
  await expect(page.locator('.industry-picker')).not.toHaveAttribute('open','')
  await expect(page.locator('.industry-picker summary')).toContainText('等6个行业')
  await page.getByLabel('选择行业',{exact:true}).click()
  await page.locator('.screen-overview h3').click()
  await expect(page.locator('.industry-picker')).not.toHaveAttribute('open','')
  await page.getByLabel('选择行业',{exact:true}).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('.industry-picker')).not.toHaveAttribute('open','')
  await expect(page.getByLabel('选择行业',{exact:true})).toBeFocused()
  await page.getByRole('button',{name:'另存为新策略',exact:true}).click()
  const dialog=page.getByRole('dialog')
  await dialog.getByLabel('策略名称').fill(savedName)
  const saved=page.waitForResponse(response=>response.url().endsWith('/api/account/strategies') && response.request().method()==='PUT')
  await dialog.getByRole('button',{name:'确认保存',exact:true}).click()
  expect((await saved).status()).toBe(200)
  await expect(dialog).toHaveCount(0)
  await page.reload()
  await page.getByLabel('打开账号菜单').click()
  await page.getByRole('button',{name:'我的策略',exact:true}).click()
  await page.locator('.strategy-drawer article').filter({has:page.getByRole('heading',{name:savedName,exact:true})}).getByRole('button',{name:'载入并编辑'}).click()
  await page.getByLabel('选择行业',{exact:true}).click()
  await page.getByLabel('搜索行业',{exact:true}).fill('')
  await expect(page.getByRole('checkbox',{checked:true})).toHaveCount(6)
  await page.getByRole('button',{name:'完成选择',exact:true}).click()
  await page.getByRole('button',{name:'保存更改',exact:true}).click()
  await page.getByRole('dialog').getByRole('button',{name:'确认保存',exact:true}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  for(const [width,height] of [[1440,900],[390,844]]) {
    await page.setViewportSize({width,height})
    await page.getByLabel('选择行业',{exact:true}).click()
    const panel=await page.locator('.industry-options').boundingBox()
    expect(panel!.x).toBeGreaterThanOrEqual(0)
    expect(panel!.x+panel!.width).toBeLessThanOrEqual(width)
    await page.screenshot({path:`../artifacts/industry-completion-${width}.png`})
    await page.getByRole('button',{name:'完成选择',exact:true}).click()
  }
  expect(calls).toBe(0)
})
