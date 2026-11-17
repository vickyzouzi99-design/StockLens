import { useEffect, useRef, useState } from 'react'
import { accountApi } from './accountApi'

export function AccountMenu({ username, local, onStrategies, onSettings, onLogout }: {
  username?: string; local?: boolean; onStrategies: () => void; onSettings: () => void; onLogout: () => Promise<void>
}) {
  const menu = useRef<HTMLDetailsElement>(null)
  const trigger = useRef<HTMLElement>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (event.target instanceof Node && !menu.current?.contains(event.target) && menu.current) menu.current.open = false }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && menu.current?.open) { menu.current.open = false; trigger.current?.focus() } }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [])
  const choose = (action: () => void) => { if (menu.current) menu.current.open = false; trigger.current?.focus(); action() }
  return <details ref={menu} className="account-menu">
    <summary ref={trigger} className="avatar-trigger" aria-label="打开账号菜单" aria-haspopup="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg></summary>
    <nav className="account-dropdown" aria-label="账号菜单"><div className="account-menu-identity"><strong>{username || '本地工作台'}</strong><span>{local ? '本地开发模式' : '内测用户'}</span></div>
      <button type="button" onClick={() => choose(onStrategies)}>我的策略<span aria-hidden="true">→</span></button>
      <button type="button" onClick={() => choose(onSettings)}>我的账号设置<span aria-hidden="true">→</span></button>
      {!local && <button type="button" className="account-logout" disabled={busy} onClick={async () => { setBusy(true); setError(''); try { await onLogout() } catch { setError('退出失败，请重试。') } finally { setBusy(false) } }}>{busy ? '正在退出…' : '退出登录'}</button>}
      {error && <p className="account-error" role="alert">{error}</p>}
    </nav>
  </details>
}

type AccountDetails = { username?: string; local?: boolean; daily_limit?: number; used_today?: number }
export function AccountSettings({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [account, setAccount] = useState<AccountDetails | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    dialog.current?.showModal()
    let active = true
    void accountApi<AccountDetails>('/api/account/me').then(data => { if (active) setAccount(data) }).catch(() => { if (active) setError('无法读取账号信息，请关闭后重试。') })
    return () => { active = false }
  }, [])
  return <dialog ref={dialog} className="account-settings" onCancel={event => { if (busy) event.preventDefault(); else onClose() }} aria-labelledby="account-settings-title">
    <header><div><span className="auth-eyebrow">ACCOUNT</span><h2 id="account-settings-title">我的账号设置</h2></div><button className="dialog-close" type="button" disabled={busy} onClick={onClose} aria-label="关闭账号设置">×</button></header>
    {account ? <><dl className="account-info"><div><dt>账号</dt><dd>{account.username || '本地开发模式'}</dd></div>{!account.local && <><div><dt>今日 AI 调用</dt><dd>{account.used_today ?? 0} / {account.daily_limit ?? '—'} 次</dd></div><div><dt>策略存储</dt><dd>当前账号独立保存</dd></div></>}</dl>
      {!account.local && <form onSubmit={async event => {
        event.preventDefault(); setError(''); setNotice('')
        const form = event.currentTarget
        const data = new FormData(form)
        if (data.get('new_password') !== data.get('repeat_password')) { setError('两次输入的新密码不一致。'); return }
        setBusy(true)
        try { await accountApi('/api/account/password', { current_password: data.get('current_password'), new_password: data.get('new_password') }); setNotice('密码已更新，其他登录会话已退出。'); form.reset() }
        catch (err) { setError(err instanceof Error ? err.message : '无法连接服务') }
        finally { setBusy(false) }
      }}><h3>修改密码</h3><label>当前密码<input name="current_password" type="password" autoComplete="current-password" required maxLength={128} disabled={busy}/></label><label>新密码<input name="new_password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} disabled={busy}/></label><label>确认新密码<input name="repeat_password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} disabled={busy}/></label><p className="auth-field-hint">至少10个字符。更新后需在其他设备重新登录。</p><button className="primary-action" disabled={busy}>{busy ? '正在保存…' : '更新密码'}</button></form>}
    </> : !error && <p role="status">正在读取账号信息…</p>}
    {error && <p className="account-error" role="alert">{error}</p>}{notice && <p className="account-success" role="status">{notice}</p>}
  </dialog>
}
