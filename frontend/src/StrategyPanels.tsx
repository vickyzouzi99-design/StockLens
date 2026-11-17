import { useEffect, useRef, useState } from 'react'
import type { SavedStrategy } from './strategies'

export function StrategyDrawer({ items, message, onClose, onLoad, onRename, onCopy, onDelete, account = false, onImport }: {
  onImport?: () => void
  account?: boolean
  items: SavedStrategy[]; message: string; onClose: () => void; onLoad: (item: SavedStrategy) => void
  onRename: (item: SavedStrategy) => void; onCopy: (item: SavedStrategy) => void; onDelete: (item: SavedStrategy) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog ref={dialog} className="strategy-drawer" onCancel={onClose} aria-labelledby="strategy-title">
    <header><h2 id="strategy-title">我的策略</h2><button type="button" onClick={onClose} aria-label="关闭我的策略">×</button></header>
    <p>选股筛选方案 · {account ? '保存在当前账号' : '仅保存在此浏览器'}</p>
    {onImport && <button type="button" onClick={onImport}>将此浏览器的旧策略导入当前账号</button>}
    {message && <p role="status">{message}</p>}
    {!items.length && <p>暂无策略。在确认条件或查看结果时，可以保存你的方案。</p>}
    {[...items].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).map(item => <article key={item.id}>
      <h3>{item.name}</h3><p>沪深300 · {item.snapshot.conditions.filter(c => c.enabled).length + (item.snapshot.industry ? 1 : 0)} 个启用条件</p>
      <small>{new Date(item.updatedAt).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} (GMT+8) 更新</small>
      <button className="strategy-load" type="button" onClick={() => onLoad(item)}>载入并编辑</button>
      <div className="strategy-row-actions"><button type="button" onClick={() => onRename(item)}>重命名</button><button type="button" onClick={() => onCopy(item)}>复制</button><button type="button" onClick={() => onDelete(item)}>删除</button></div>
    </article>)}
  </dialog>
}

export function SaveStrategyDialog({ initialName, title, error, onClose, onSave, account = false }: { account?: boolean; initialName: string; title: string; error: string; onClose: () => void; onSave: (name: string) => void | Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [name, setName] = useState(initialName)
  const [busy, setBusy] = useState(false)
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog ref={dialog} className="strategy-save-dialog" onCancel={event => { if (busy) event.preventDefault(); else onClose() }} aria-labelledby="save-strategy-title"><form onSubmit={async event => { event.preventDefault(); if (name.trim() && !busy) { setBusy(true); try { await onSave(name.trim()) } finally { setBusy(false) } } }}>
    <h2 id="save-strategy-title">{title}</h2><label>策略名称<input autoFocus required maxLength={60} value={name} onChange={event => setName(event.target.value)} /></label>
    <p>{account ? '保存在当前账号' : '仅保存在此浏览器'}，保存条件，不保存股票结果。</p>{error && <p role="alert">{error}</p>}
    <div className="strategy-row-actions"><button type="button" disabled={busy} onClick={onClose}>取消</button><button className="primary-action" type="submit" disabled={busy || !name.trim()}>{busy ? '正在保存…' : '确认保存'}</button></div>
  </form></dialog>
}
