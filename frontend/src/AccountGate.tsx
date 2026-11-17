import { useEffect, useState } from 'react'
import App from './App'

import { accountApi } from './accountApi'
export default function AccountGate() {
  const [account, setAccount] = useState<{ id?: string; username?: string; local?: boolean } | null>(null)
  const [ready, setReady] = useState(false)
  const [register, setRegister] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { void accountApi<typeof account>('/api/account/me').then(setAccount).catch(() => {}).finally(() => setReady(true)) }, [])
  if (!ready) return <main className="account-panel">正在连接账号服务…</main>
  if (account) return <><div className="account-bar">{account.local ? '本地开发模式' : account.username}{!account.local && <button type="button" onClick={async () => { try { await accountApi('/api/account/logout', {}); setAccount(null) } catch { setError('退出失败，请重试。') } }}>退出账号</button>}{error && <span role="alert">{error}</span>}</div><App key={account.id || 'local'} accountId={account.id} /></>
  return <main className="account-panel"><h1>StockLens.</h1><p>你的选股想法，值得有据可循。</p><h2>{register ? '邀请码注册' : '登录工作台'}</h2><form onSubmit={async event => {
    event.preventDefault(); setError(''); setBusy(true)
    const form = new FormData(event.currentTarget)
    try { setAccount(await accountApi('/api/account/' + (register ? 'register' : 'login'), { username: form.get('username'), password: form.get('password'), ...(register ? { invite: form.get('invite') } : {}) })) }
    catch (err) { setError(err instanceof Error ? err.message : '无法连接服务') }
    finally { setBusy(false) }
  }}><label>用户名<input name="username" required pattern="[A-Za-z0-9_]{3,32}" autoComplete="username" placeholder="3–32位字母、数字或下划线" /></label><label>密码<input type="password" name="password" required minLength={10} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} /></label>{register && <label>邀请码<input name="invite" required maxLength={128} autoComplete="off" /></label>}{error && <p role="alert">{error}</p>}<button className="primary-action" disabled={busy}>{busy ? '正在处理…' : register ? '创建账号' : '登录'}</button></form><button type="button" onClick={() => { setRegister(!register); setError('') }}>{register ? '已有账号，去登录' : '使用邀请码注册'}</button><p>策略保存在你的账号中。恢复与修改条件不消耗 AI 调用额度。</p></main>
}
