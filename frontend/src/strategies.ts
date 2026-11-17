import { validateMetric } from './validation.ts'
import type { MetricKey } from './validation.ts'

export const metricKeys: MetricKey[] = ['pe_max', 'profit_min', 'vol_max', 'pb_max', 'roe_min', 'revenue_min']
export type StrategyParams = Record<MetricKey, number | null> & { industry: string | null }
export const rules = Object.fromEntries(metricKeys.map(key => [key, {
  operator: key === 'pe_max' || key === 'pb_max' ? 'positive_le' : key.endsWith('_min') ? 'ge' : 'le',
  unit: key === 'pe_max' || key === 'pb_max' ? '倍' : '%',
}])) as Record<MetricKey, { operator: string; unit: string }>
export interface StrategySnapshot {
  universeId: 'CSI300'
  conditionLogic: 'AND'
  conditions: { metricId: MetricKey; enabled: boolean; operator: string; value: number | null; unit: string }[]
  industry: string | null
}
export function snapshotParams(snapshot: StrategySnapshot): StrategyParams {
  return { ...Object.fromEntries(snapshot.conditions.map(c => [c.metricId, c.enabled ? c.value : null])), industry: snapshot.industry } as StrategyParams
}
export function snapshotFingerprint(snapshot: StrategySnapshot): string {
  return JSON.stringify([snapshot.universeId, snapshot.conditionLogic, snapshot.industry, metricKeys.map(key => { const c = snapshot.conditions.find(c => c.metricId === key); return c && [c.metricId, c.enabled, c.operator, c.value, c.unit] })])
}
export function makeSnapshot(draft: Record<MetricKey, string>, enabled: MetricKey[], industry: string | null): StrategySnapshot {
  return { universeId: 'CSI300', conditionLogic: 'AND', industry, conditions: metricKeys.map(metricId => ({ metricId, enabled: enabled.includes(metricId), ...rules[metricId], value: draft[metricId].trim() ? Number(draft[metricId]) : null })) }
}
export function validateSnapshot(snapshot: StrategySnapshot) {
  if (!snapshot || snapshot.universeId !== 'CSI300' || snapshot.conditionLogic !== 'AND' || !Array.isArray(snapshot.conditions) || snapshot.conditions.length !== metricKeys.length) throw new Error('策略股票池、组合关系或指标版本不兼容')
  const seen = new Set<string>()
  for (const c of snapshot.conditions) {
    if (!c || !metricKeys.includes(c.metricId) || seen.has(c.metricId) || typeof c.enabled !== 'boolean' || c.operator !== rules[c.metricId].operator || c.unit !== rules[c.metricId].unit) throw new Error('策略指标或运算符不兼容')
    seen.add(c.metricId)
    if ((c.enabled && c.value === null) || (c.value !== null && (typeof c.value !== 'number' || validateMetric(c.metricId, String(c.value), 'user', true, true)))) throw new Error('策略存在无效阈值，请修正后保存')
  }
  if (snapshot.industry !== null && (typeof snapshot.industry !== 'string' || !/^\d{6}\.TI$/.test(snapshot.industry))) throw new Error('策略行业代码无效')
  if (!snapshot.industry && !snapshot.conditions.some(c => c.enabled)) throw new Error('策略没有启用条件')
}
export interface SavedStrategy {
  id: string
  name: string
  query: string
  provider: 'openai' | 'deepseek'
  params: StrategyParams
  savedAt: string
  schemaVersion: 2
  createdAt: string
  updatedAt: string
  snapshot: StrategySnapshot
}
export const storageKey = 'stocklens.strategies.v1'
export function draftFingerprint(query: string, provider: string, snapshot: StrategySnapshot): string {
  return JSON.stringify([query, provider, snapshotFingerprint(snapshot)])
}
export function saveStrategy(items: SavedStrategy[], item: SavedStrategy, update: boolean): SavedStrategy[] {
  const existing = items.find(old => old.id === item.id)
  if (update && !existing) throw new Error('原策略已被删除，请另存为新策略。')
  if (!update && existing) throw new Error('策略 ID 重复')
  if (!update && items.length >= 30) throw new Error('最多保存 30 条策略。')
  const next = update ? items.map(old => old.id === item.id ? { ...item, createdAt: old.createdAt } : old) : [...items, item]
  return decodeStrategies(encodeStrategies(next))
}
export function writeStrategies(storage: Pick<Storage, 'getItem' | 'setItem'>, before: SavedStrategy[], next: SavedStrategy[]) {
  const current = decodeStrategies(storage.getItem(storageKey))
  if (encodeStrategies(current) !== encodeStrategies(before)) throw new Error('策略库已在其他页面更新，请重新打开“我的策略”后重试。')
  const encoded = encodeStrategies(next)
  storage.setItem(storageKey, encoded)
  return decodeStrategies(encoded)
}

/** Reject invalid libraries as a whole: never silently drop a saved restriction. */
export function decodeStrategies(raw: string | null): SavedStrategy[] {
  if (raw === null) return []
  const data = JSON.parse(raw)
  if (data?.version !== 1 || !Array.isArray(data.items) || data.items.length > 50) throw new Error('策略库格式不受支持')
  const ids = new Set<string>()
  for (const item of data.items) {
    if (item?.schemaVersion !== undefined) {
      if (item.schemaVersion !== 2) throw new Error('策略版本不兼容')
      validateSnapshot(item.snapshot)
      if (!Number.isFinite(Date.parse(item.createdAt)) || !Number.isFinite(Date.parse(item.updatedAt))) throw new Error('策略时间无效')
      item.params = snapshotParams(item.snapshot)
      item.savedAt = item.updatedAt
    }
    if (!item || typeof item.id !== 'string' || !item.id || ids.has(item.id) ||
      typeof item.name !== 'string' || !item.name.trim() || item.name.length > 60 ||
      typeof item.query !== 'string' || item.query.length > 500 ||
      !['openai', 'deepseek'].includes(item.provider) || !Number.isFinite(Date.parse(item.savedAt)) ||
      !item.params || typeof item.params !== 'object' || Array.isArray(item.params)) throw new Error('策略记录无效')
    ids.add(item.id)
    if (Object.keys(item.params).some(key => key !== 'industry' && !metricKeys.includes(key as MetricKey))) throw new Error('策略包含不支持的条件')
    item.params.industry ??= null
    if (item.params.industry !== null && (typeof item.params.industry !== 'string' || !/^\d{6}\.TI$/.test(item.params.industry))) throw new Error('策略行业代码无效')
    let enabled = item.params.industry !== null
    for (const key of metricKeys) {
      const value = item.params[key]
      if (value === null || value === undefined) { item.params[key] = null; continue }
      if (typeof value !== 'number' || validateMetric(key, String(value), 'user', true, true)) throw new Error('策略阈值无效')
      enabled = true
    }
    if (!enabled) throw new Error('策略没有启用条件')
    if (item.schemaVersion === undefined) {
      item.snapshot = makeSnapshot(Object.fromEntries(metricKeys.map(key => [key, item.params[key]?.toString() ?? ''])) as Record<MetricKey, string>, metricKeys.filter(key => item.params[key] !== null), item.params.industry)
      item.schemaVersion = 2
      item.createdAt = item.savedAt
      item.updatedAt = item.savedAt
    }
  }
  return data.items.map((item: SavedStrategy) => ({ schemaVersion: 2, id: item.id, name: item.name, query: item.query, provider: item.provider, params: item.params, snapshot: { universeId: item.snapshot.universeId, conditionLogic: item.snapshot.conditionLogic, industry: item.snapshot.industry, conditions: item.snapshot.conditions.map(({ metricId, enabled, operator, value, unit }) => ({ metricId, enabled, operator, value, unit })) }, createdAt: item.createdAt, updatedAt: item.updatedAt, savedAt: item.savedAt }))
}

export function encodeStrategies(items: SavedStrategy[]): string {
  for (const item of items) if (item.schemaVersion === 2) validateSnapshot(item.snapshot)
  const normalized = decodeStrategies(JSON.stringify({ version: 1, items }))
  return JSON.stringify({ version: 1, items: normalized.map(({ params: _params, savedAt: _savedAt, ...item }) => { void _params; void _savedAt; return item }) })
}
