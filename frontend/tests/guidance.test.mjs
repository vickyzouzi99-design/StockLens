import assert from 'node:assert/strict'
import test from 'node:test'
import { describeRule, directions, needsClarification, referenceConditions } from '../src/guidance.ts'
import { validateMetric } from '../src/validation.ts'

test('潜力股先澄清，用户选择方向后不再阻塞', () => {
  const intent = { active_metrics: [], unsupported: [], clarifications: ['潜力股'] }
  assert.equal(needsClarification(intent, false), true)
  assert.equal(needsClarification(intent, true), false)
})

test('明确数值不多问，纯不支持条件不冒充模糊目标', () => {
  assert.equal(needsClarification({ active_metrics: ['pe_max'], unsupported: [] }, false), false)
  assert.equal(needsClarification({ active_metrics: [], unsupported: ['银行行业'] }, false), false)
  assert.equal(needsClarification({ active_metrics: [], unsupported: [] }, false), true)
})

test('所有引导方向都有合法、可手动选择的参考条件', () => {
  for (const direction of directions) {
    const options = referenceConditions[direction.key]
    assert.ok(options.length > 0)
    for (const option of options) {
      assert.equal(validateMetric(direction.key, String(option.value), 'missing', true, false), '')
    }
  }
})

test('已有条件加模糊目标仍需澄清', () => {
  assert.equal(needsClarification({ active_metrics: ['pe_max'], unsupported: [], clarifications: ['潜力股'] }, false), true)
})

test('执行规则摘要保留负增长、零波动及正PE边界', () => {
  assert.equal(describeRule('pe_max', 20), '0 < PE TTM ≤ 20 倍')
  assert.equal(describeRule('profit_min', -5), '归母净利润同比 ≥ -5%')
  assert.equal(describeRule('vol_max', 0), '近20日波动率 ≤ 0%')
})
