import { useState } from 'react'
import type { IndustrySelection } from './industrySelection'
import { industryCodes, normalizeIndustry } from './industrySelection'

export function IndustrySelector({ value, options, disabled, onChange }: { value: IndustrySelection; options: { code: string; name: string; count: number }[]; disabled: boolean; onChange: (value: IndustrySelection) => void }) {
  const [search, setSearch] = useState('')
  const selected = industryCodes(value)
  const catalog = [...options, ...selected.filter(code => !options.some(item => item.code === code)).map(code => ({ code, name: `${code}（当前目录暂不可用）`, count: 0 }))]
  const label = selected.length ? catalog.filter(item => selected.includes(item.code)).map(item => item.name).join('、') : '不限行业'
  return <div className="industry-condition"><div className="industry-heading"><strong>限定行业</strong><span>可多选 · 选中行业满足任一项</span></div><details className="industry-picker"><summary aria-label="选择行业">{label}<span aria-hidden="true">⌄</span></summary><div className="industry-options"><label className="visually-hidden" htmlFor="industry-search">搜索行业</label><input id="industry-search" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索行业"/><fieldset disabled={disabled}><legend className="visually-hidden">选择同花顺行业</legend>{catalog.filter(item => item.name.includes(search.trim())).map(item => <label key={item.code}><input type="checkbox" checked={selected.includes(item.code)} onChange={event => onChange(normalizeIndustry(event.target.checked ? [...selected, item.code] : selected.filter(code => code !== item.code)))}/><span>{item.name}</span><small>{item.count}只</small></label>)}</fieldset>{!catalog.length && <p>当前快照暂无行业分类。</p>}<button type="button" disabled={disabled || !selected.length} onClick={() => onChange(null)}>清空选择 · 不限行业</button></div></details></div>
}
