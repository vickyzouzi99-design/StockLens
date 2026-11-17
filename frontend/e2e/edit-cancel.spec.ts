import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { makeSnapshot, metricKeys } from '../src/strategies'

const credentials=JSON.parse(readFileSync('../artifacts/ai-review.json','utf8'))
test('editing uses initial composer height and cancel restores prompt and provider without AI',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'})
  let calls=0
  page.on('request',request=>{if(request.url().endsWith('/api/interpret'))calls++})
  await page.goto('/')
  await page.getByLabel('用户名',{exact:true}).fill(credentials.username)
  await page.getByLabel('密码',{exact:true}).fill(credentials.password)
  await page.getByRole('button',{name:'登录工作台',exact:true}).click()
  await expect(page.getByLabel('打开账号菜单')).toBeVisible()
  const initial:Record<number,number>={}
  for(const [width,height] of [[1440,900],[768,1024],[390,844]]) {
    await page.setViewportSize({width,height})
    initial[width]=(await page.locator('.composer-card').boundingBox())!.height
  }
  const library=await(await page.request.get('/api/account/strategies')).json()
  const draft=Object.fromEntries(metricKeys.map(key=>[key,key==='pe_max'?'20':''])) as Record<typeof metricKeys[number],string>
  const now=new Date().toISOString()
  const name='取消修改验收_'+Date.now()
  expect((await page.request.put('/api/account/strategies',{data:{revision:library.revision,items:[...library.items,{schemaVersion:2,id:name,name,query:'市盈率不超过20倍',provider:'deepseek',createdAt:now,updatedAt:now,snapshot:makeSnapshot(draft,['pe_max'],null)}]}})).ok()).toBeTruthy()
  await page.getByLabel('打开账号菜单').click()
  await page.getByRole('button',{name:'我的策略',exact:true}).click()
  await page.locator('.strategy-drawer article').filter({has:page.getByRole('heading',{name,exact:true})}).getByRole('button',{name:'载入并编辑'}).click()
  await page.getByRole('button',{name:'修改需求 / AI 服务'}).click()
  for(const [width,height] of [[1440,900],[768,1024],[390,844]]) {
    await page.setViewportSize({width,height})
    expect(Math.abs((await page.locator('.composer-card').boundingBox())!.height-initial[width])).toBeLessThan(2)
    const cancel=await page.getByRole('button',{name:'取消修改'}).boundingBox()
    const parse=await page.getByRole('button',{name:'重新解析需求'}).boundingBox()
    expect(cancel!.x+cancel!.width).toBeLessThanOrEqual(parse!.x)
  }
  await page.getByLabel('描述你的选股需求').fill('改成不一样的需求')
  await page.getByLabel('AI 服务',{exact:true}).selectOption('openai')
  await page.getByRole('button',{name:'取消修改'}).click()
  await expect(page.locator('.idea-summary')).toContainText('市盈率不超过20倍')
  await expect(page.locator('.idea-summary')).toContainText('DeepSeek')
  await expect(page.locator('#metric-pe_max')).toHaveValue('20')
  await expect(page.getByRole('button',{name:'确认并执行筛选',exact:true})).toBeEnabled()
  expect(calls).toBe(0)
})
