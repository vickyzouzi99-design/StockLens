import test from 'node:test'
import assert from 'node:assert/strict'
import { decodeStrategies, encodeStrategies, makeSnapshot, metricKeys, snapshotFingerprint, snapshotParams } from '../src/strategies.ts'
const item = { id: 'one', name: '盈利观察', query: '利润增长', provider: 'deepseek', params: { pe_max: null, profit_min: 0, vol_max: null }, savedAt: '2026-11-17T00:00:00Z' }
test('strategy round trip preserves zero, provider and disabled metrics', () => {
  const migrated = decodeStrategies(encodeStrategies([item]))[0]
  assert.deepEqual(migrated.params, { ...item.params, pb_max: null, roe_min: null, revenue_min: null, industry: null })
  assert.equal(migrated.createdAt, item.savedAt)
  assert.equal(migrated.schemaVersion, 2)
  assert.equal(migrated.provider, item.provider)
  assert.deepEqual(decodeStrategies(null), [])
})
test('new financial and industry restrictions survive save/restore; empty and invalid fail', () => {
  const newer = { ...item, params: { ...item.params, pb_max: 2.5, roe_min: 0, revenue_min: -5, industry: '881155.TI' } }
  assert.deepEqual(decodeStrategies(encodeStrategies([newer]))[0].params, newer.params)
  assert.throws(() => encodeStrategies([{ ...newer, params: { ...newer.params, industry: 'bank' } }]))
  assert.throws(() => encodeStrategies([{ ...newer, params: { ...newer.params, pb_max: 0 } }]))
  const industryOnly = { ...newer, params: { pe_max: null, profit_min: null, vol_max: null, pb_max: null, roe_min: null, revenue_min: null, industry: '881155.TI' } }
  assert.deepEqual(decodeStrategies(encodeStrategies([industryOnly]))[0].params, industryOnly.params)
  assert.throws(() => encodeStrategies([{ ...industryOnly, params: { ...industryOnly.params, industry: null } }]))
})
test('complete snapshot preserves disabled thresholds without activating them', () => {
  const draft = Object.fromEntries(metricKeys.map(key => [key, '']))
  draft.pe_max = '20'; draft.roe_min = '12'
  const snapshot = makeSnapshot(draft, ['pe_max'], null)
  const base = decodeStrategies(encodeStrategies([item]))[0]
  const saved = decodeStrategies(encodeStrategies([{ ...base, snapshot, apiKey: 'must-not-store' }]))[0]
  assert.equal(saved.snapshot.conditions.find(c => c.metricId === 'roe_min').value, 12)
  assert.equal(saved.params.roe_min, null)
  assert.equal(snapshotFingerprint(saved.snapshot), snapshotFingerprint(snapshot))
  saved.snapshot.conditions.find(c => c.metricId === 'roe_min').enabled = true
  assert.equal(snapshotParams(saved.snapshot).roe_min, 12)
  assert.notEqual(snapshotFingerprint(saved.snapshot), snapshotFingerprint(snapshot))
  assert.equal(encodeStrategies([{ ...base, snapshot, apiKey: 'must-not-store' }]).includes('must-not-store'), false)
  const invalid = structuredClone(saved)
  invalid.snapshot.conditions[0].operator = 'OR'
  assert.throws(() => encodeStrategies([invalid]))
  invalid.snapshot = { ...snapshot, conditionLogic: 'OR' }
  assert.throws(() => encodeStrategies([invalid]))
  invalid.snapshot = { ...snapshot, conditions: snapshot.conditions.slice(1) }
  assert.throws(() => encodeStrategies([invalid]))
})
test('corrupt, unknown and invalid restrictions cannot be silently restored', () => {
  for (const raw of ['{', '{"version":2,"items":[]}', JSON.stringify({ version: 1, items: [{ ...item, params: { ...item.params, pe_max: -1 } }] }), JSON.stringify({ version: 1, items: [{ ...item, params: { ...item.params, secret_metric: 1 } }] })]) assert.throws(() => decodeStrategies(raw))
  assert.throws(() => encodeStrategies([item, item]))
})
