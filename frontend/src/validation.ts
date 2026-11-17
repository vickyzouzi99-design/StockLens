export type MetricKey = 'pe_max' | 'profit_min' | 'vol_max' | 'pb_max' | 'roe_min' | 'revenue_min'
export type Source = 'user' | 'suggested' | 'missing'

/** Shared by inline feedback and the submit guard so they cannot disagree. */
export function validateMetric(key: MetricKey, raw: string,
  source: Source | undefined, modified: boolean, accepted: boolean): string {
  if (!raw.trim()) return '请填写筛选阈值。'
  const value = Number(raw)
  if (!Number.isFinite(value)) return '请输入有效数字。'
  if (key === 'pe_max' && (value <= 0 || value > 100000)) {
    return '市盈率上限必须大于 0，且不超过 100000 倍。'
  }
  if (key === 'profit_min' && (value < -10000 || value > 10000)) {
    return '利润增长率应在 -10000% 至 10000% 之间。'
  }
  if (key === 'vol_max' && (value < 0 || value > 1000)) {
    return '波动率上限应在 0% 至 1000% 之间。'
  }
  if (key === 'pb_max' && (value <= 0 || value > 100000)) return '市净率上限必须大于 0，且不超过 100000 倍。'
  if (['roe_min', 'revenue_min'].includes(key) && (value < -10000 || value > 10000)) return '指标应在 -10000% 至 10000% 之间。'
  if (source === 'suggested' && !modified && !accepted) {
    return '请确认采用 AI 建议值，或自行修改。'
  }
  return ''
}
