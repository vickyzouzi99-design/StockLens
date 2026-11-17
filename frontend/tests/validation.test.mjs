import assert from 'node:assert/strict'
import test from 'node:test'
import { validateMetric } from '../src/validation.ts'

const check = (key, value) => validateMetric(key, value, 'user', true, false)

test('截图中的负 PE 有明确错误，修正为 20 后恢复有效', () => {
  assert.match(check('pe_max', '-2'), /市盈率.*大于 0/)
  assert.equal(check('pe_max', '20'), '')
})

test('空输入不能被 Number 转换成合法的零阈值', () => {
  for (const key of ['pe_max', 'profit_min', 'vol_max']) {
    for (const value of ['', '   ']) assert.match(check(key, value), /填写/)
  }
})

test('零在 PE 中非法，但利润增长和波动率允许零', () => {
  assert.notEqual(check('pe_max', '0'), '')
  assert.equal(check('profit_min', '0'), '')
  assert.equal(check('vol_max', '0'), '')
})

test('各指标范围和小数边界与后端保持一致', () => {
  for (const [key, good, bad] of [
    ['pe_max', ['0.1', '100000'], ['-1', '100000.1']],
    ['profit_min', ['-10000', '10000'], ['-10000.1', '10000.1']],
    ['vol_max', ['0', '2.5', '1000'], ['-0.1', '1000.1']],
  ]) {
    for (const value of good) assert.equal(check(key, value), '', `${key}=${value}`)
    for (const value of bad) assert.notEqual(check(key, value), '', `${key}=${value}`)
  }
})

test('非数字和无穷值禁止提交', () => {
  for (const value of ['abc', 'NaN', 'Infinity', '1e999']) {
    assert.match(check('pe_max', value), /有效数字/)
  }
})

test('AI 建议只有显式接受或手动修改后才有效', () => {
  assert.match(validateMetric('pe_max', '20', 'suggested', false, false), /确认/)
  assert.equal(validateMetric('pe_max', '20', 'suggested', false, true), '')
  assert.equal(validateMetric('pe_max', '21', 'suggested', true, false), '')
  assert.notEqual(validateMetric('pe_max', '-2', 'suggested', false, true), '')
})
