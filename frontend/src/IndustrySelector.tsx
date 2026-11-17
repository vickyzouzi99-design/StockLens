import { useEffect, useRef, useState } from 'react'
import type { IndustrySelection } from './industrySelection'
import { industryCodes, normalizeIndustry } from './industrySelection'

export function IndustrySelector({ value, options, disabled, onChange }: { value: IndustrySelection; options: { code: string; name: string; count: number }[]; disabled: boolean; onChange: (value: IndustrySelection) => void }) {
  const [search, setSearch] = useState('')
  const picker = useRef<HTMLDetailsElement>(null)
  const trigger = useRef<HTMLElement>(null)
  const close = () => { if (picker.current) picker.current.open = false }
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (event.target instanceof Node && !picker.current?.contains(event.target)) close() }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && picker.current?.open) { close(); trigger.current?.focus() } }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [])
  const selected = industryCodes(value)
  const catalog = [...options, ...selected.filter(code => !options.some(item => item.code === code)).map(code => ({ code, name: `${code}（当前目录暂不可用）`, count: 0 }))]
  const label = selected.length ? catalog.filter(item => selected.includes(item.code)).map(item => item.name).join('、') : '不限行业'
  const summaryLabel = selected.length > 2 ? `${catalog.filter(item => selected.includes(item.code)).slice(0, 2).map(item => item.name).join('、')} 等${selected.length}个行业` : label
  return <div className="industry-condition"><div className="industry-heading"><strong>限定行业</strong><span>可多选 · 选中行业满足任一项</span></div><details ref={picker} className="industry-picker"><summary ref={trigger} aria-label="选择行业" aria-disabled={disabled} title={label} onClick={event => { if (disabled) event.preventDefault() }}>{summaryLabel}<span aria-hidden="true">⌄</span></summary><div className="industry-options"><label className="visually-hidden" htmlFor="industry-search">搜索行业</label><input id="industry-search" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索行业" disabled={disabled}/><fieldset disabled={disabled}><legend className="visually-hidden">选择同花顺行业</legend>{catalog.filter(item => item.name.includes(search.trim())).map(item => <label key={item.code}><input type="checkbox" checked={selected.includes(item.code)} onChange={event => onChange(normalizeIndustry(event.target.checked ? [...selected, item.code] : selected.filter(code => code !== item.code)))}/><span>{item.name}</span><small>{item.count}只</small></label>)}</fieldset>{!catalog.length && <p>当前快照暂无行业分类。</p>}<p className="industry-save-hint">选择会应用到当前条件；保存策略后可在下次复用。</p><div className="industry-actions"><button type="button" disabled={disabled || !selected.length} onClick={() => onChange(null)}>清空选择</button><button type="button" className="industry-done" disabled={disabled} onClick={() => { close(); trigger.current?.focus() }}>完成选择</button></div></div></details></div>
}
