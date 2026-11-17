import { useState } from 'react'

export interface ProvenanceEntry {
  key: string; title: string; source: string; basis: string; time_label: string
  timestamp?: string | number | null; availability: 'available' | 'partial' | 'missing'
  report?: string | null; industry_names?: string[]; prices?: { date_ms: number; close_price: number }[]
}
function reportLabel(report: string) {
  const match = /^(\d{4})-([1-4])$/.exec(report)
  return match ? `${match[1]}年${['一季报', '中报', '三季报', '年报'][Number(match[2])-1]}` : report
}
const traceLabels: Record<string, string> = { pool_request_id: '股票池采集', industry_request_id: '行业分类查询', valuation_request_id: '估值快照查询', kline_request_id: '日K线查询', financial_request_id: '财务指标查询' }
export function DataProvenance({ entries, sources, collectedAt, lastTradeDate, snapshotId, formatDate }: {
  entries: ProvenanceEntry[]; sources: Record<string, string>; collectedAt?: string; lastTradeDate?: string; snapshotId?: string
  formatDate: (value?: string | number | null) => string
}) {
  const [copyNotice, setCopyNotice] = useState('')
  return <section className="data-provenance-panel" aria-labelledby="data-provenance-title"><h3 className="drawer-section-title" id="data-provenance-title">数据来源与计算依据</h3><p className="drawer-section-desc">本次判断使用以下数据。查询时间、行情时间和财报报告期分别列明。</p>
    <dl className="provenance-snapshot"><div><dt>本次采用的快照</dt><dd>{formatDate(collectedAt)}</dd></div>{lastTradeDate && <div><dt>完整交易日截至</dt><dd>{lastTradeDate}</dd></div>}</dl>
    {entries.length ? entries.map(entry => <article className="provenance-entry" key={entry.key}><div className="provenance-heading"><h4>{entry.title}</h4><span>{entry.availability === 'available' ? '本项数据可用' : entry.availability === 'partial' ? '部分数据缺失' : '缺少可用数据'}</span></div><p className="provenance-source">{entry.source}</p><p>{entry.basis}</p><dl><div><dt>{entry.time_label}</dt><dd>{formatDate(entry.timestamp)}</dd></div>{entry.key === 'financial' && <div><dt>采用报告期</dt><dd>{entry.report ? reportLabel(entry.report) : '未记录'}</dd></div>}{entry.key === 'industry' && <div><dt>实际行业归属</dt><dd>{entry.industry_names?.join('、') || '未记录'}</dd></div>}</dl>
      {entry.prices?.length ? <details className="calculation-inputs"><summary>查看计算用的21个收盘价</summary><p>日收益率 =（当日收盘价 ÷ 前一日收盘价 − 1）× 100%；对20个收益率计算样本标准差（分母为19），得到未年化波动率。</p><table><caption>本次快照记录的前复权收盘价</caption><thead><tr><th>交易日（GMT+8）</th><th>收盘价（元）</th></tr></thead><tbody>{entry.prices.map(price => <tr key={price.date_ms}><td>{formatDate(price.date_ms).split(' ')[0]}</td><td>{price.close_price.toFixed(4)}</td></tr>)}</tbody></table></details> : entry.key === 'volatility' && <p className="provenance-unavailable">该快照未记录完整的计算用价格窗口，无法在此复算。</p>}
    </article>) : <p className="drawer-section-desc">此旧快照未返回详细来源说明，逐项判断仍以上方实际指标为准。</p>}
    <details className="trace-details"><summary>技术记录 · 数据问题反馈时使用</summary><p>以下编号用于定位上游请求和本次数据版本，不是股票评分，也不代表独立审计认证。</p>{snapshotId && <p><span>本次数据版本</span><code>{snapshotId}</code></p>}{Object.entries(sources).map(([key, value]) => <p key={key}><span>{traceLabels[key] || '其他数据请求'}</span><code>{value || '未记录'}</code></p>)}<button className="add-metric-button" type="button" onClick={async () => { try { await navigator.clipboard.writeText(JSON.stringify({ snapshotId, collectedAt, sources }, null, 2)); setCopyNotice('技术记录已复制') } catch { setCopyNotice('无法访问剪贴板，请手动选择记录复制。') } }}>复制反馈记录</button>{copyNotice && <p role="status">{copyNotice}</p>}</details>
  </section>
}
