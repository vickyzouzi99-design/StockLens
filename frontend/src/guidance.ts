import type { MetricKey } from './validation.ts'

export const directions: { key: MetricKey; label: string; explanation: string }[] = [
  { key: 'pb_max', label: '关注净资产估值', explanation: '用正市净率衡量股价相对每股净资产的倍数。' },
  { key: 'roe_min', label: '关注资本盈利效率', explanation: '用报告期加权平均 ROE 衡量股东资本的盈利效率，未自行年化。' },
  { key: 'revenue_min', label: '关注营收增长', explanation: '看营业收入相对去年同期的变化；收入增长不等于利润增长。' },
  { key: 'profit_min', label: '关注盈利增长', explanation: '用归母净利润同比增长率，衡量已披露利润相对去年同期的变化。' },
  { key: 'pe_max', label: '关注估值水平', explanation: '用正市盈率（PE TTM）上限表达估值要求；行业差异仍需另行判断。' },
  { key: 'vol_max', label: '关注近期波动', explanation: '用近20日收益率波动率衡量价格起伏；低波动不等于低风险或未来上涨。' },
]

export const referenceConditions: Record<MetricKey, { label: string; value: number }[]> = {
  pb_max: [{ label: '市净率上限 2 倍', value: 2 }, { label: '市净率上限 3 倍', value: 3 }],
  roe_min: [{ label: '报告期 ROE 至少 8%', value: 8 }, { label: '报告期 ROE 至少 12%', value: 12 }],
  revenue_min: [{ label: '营收同比至少增长 5%', value: 5 }, { label: '营收同比至少增长 10%', value: 10 }],
  pe_max: [
    { label: '市盈率上限 20 倍', value: 20 },
    { label: '市盈率上限 30 倍', value: 30 },
  ],
  profit_min: [
    { label: '利润比去年增长至少 5%', value: 5 },
    { label: '利润比去年增长至少 10%', value: 10 },
  ],
  vol_max: [
    { label: '起伏限制较严：波动率 ≤ 2.5%', value: 2.5 },
    { label: '放宽限制：波动率 ≤ 4%', value: 4 },
  ],
}

export function describeRule(key: MetricKey, value: number): string {
  if (key === 'pb_max') return `0 < PB MRQ ≤ ${value} 倍`
  if (key === 'roe_min') return `报告期加权平均 ROE ≥ ${value}%`
  if (key === 'revenue_min') return `营业收入同比 ≥ ${value}%`
  if (key === 'pe_max') return `0 < PE TTM ≤ ${value} 倍`
  if (key === 'profit_min') return `归母净利润同比 ≥ ${value}%`
  return `近20日波动率 ≤ ${value}%`
}

export function needsClarification(intent: { active_metrics: MetricKey[]; unsupported: string[]; clarifications?: string[]; industry?: string | null }, resolved: boolean) {
  return !resolved && (Boolean(intent.clarifications?.length) ||
    (intent.active_metrics.length === 0 && !intent.industry && intent.unsupported.length === 0))
}
