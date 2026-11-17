import { useEffect, useRef, useState } from 'react'
import App from './App'

import { accountApi } from './accountApi'
import { BrandMark, SiteFooter } from './Brand'
import './Account.css'
export default function AccountGate() {
  const [account, setAccount] = useState<{ id?: string; username?: string; local?: boolean } | null>(null)
  const [ready, setReady] = useState(false)
  const [register, setRegister] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const shell = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (account) return
    const host = shell.current
    const story = host?.querySelector<HTMLElement>('.auth-story')
    const footer = host?.querySelector<HTMLElement>('.site-footer')
    const main = host?.querySelector<HTMLElement>('.auth-main')
    if (!story || !footer || !main) return
    let frame: number | null = null
    const update = () => {
      frame = null
      const center = innerHeight / 2 + 32
      const offset = innerWidth > 700 ? Math.max(0, center + story.offsetHeight / 2 + 24 - footer.getBoundingClientRect().top) : 0
      story.style.setProperty('--auth-footer-offset', `${offset}px`)
    }
    const schedule = () => { if (frame === null) frame = requestAnimationFrame(update) }
    const observer = new ResizeObserver(schedule)
    observer.observe(story); observer.observe(footer); observer.observe(main)
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    schedule()
    return () => { observer.disconnect(); window.removeEventListener('scroll', schedule); window.removeEventListener('resize', schedule); if (frame !== null) cancelAnimationFrame(frame) }
  }, [account])
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'instant' }) }, [account?.id, account?.local])
  useEffect(() => { void accountApi<typeof account>('/api/account/me').then(setAccount).catch(() => {}).finally(() => setReady(true)) }, [])
  if (account) return <App key={account.id || 'local'} accountId={account.id} username={account.username} local={account.local} onLogout={async () => { await accountApi('/api/account/logout', {}); setAccount(null); setError(''); setRegister(false) }} />
  return <div ref={shell} className="auth-shell"><header className="site-header auth-header"><div className="header-inner"><div className="identity"><BrandMark/><span className="identity-name">StockLens<span className="identity-period">.</span></span><span className="identity-separator"/><span className="identity-caption">投资偏好筛选工作台</span></div><span className="beta-badge">内测版</span></div></header>
    <main className="auth-main"><section className="auth-story" aria-labelledby="auth-headline"><nav className="auth-flow" aria-label="选股流程"><span><small>01</small>描述需求</span><i aria-hidden="true">→</i><span><small>02</small>确认条件</span><i aria-hidden="true">→</i><span><small>03</small>核验结果</span></nav><div className="auth-eyebrow"><span/>INVESTMENT RESEARCH WORKSPACE</div><h1 id="auth-headline">你的选股想法，<br/><span>值得有据可循。</span></h1><p className="auth-subtitle">以想法定义方向，以数据检验结果。</p><p className="auth-description">将投资偏好整理成清晰的筛选条件，核对真实数据，保存并持续完善你的选股方案。</p></section>
    <section className="auth-card" aria-labelledby="auth-form-title"><div className="auth-card-heading"><span className="auth-eyebrow">WELCOME TO STOCKLENS</span><h2 id="auth-form-title">{register ? '开启你的研究工作台' : '欢迎回到工作台'}</h2><p>{register ? '使用邀请码创建账号，保存你的每一次研究。' : '登录账号，继续你的选股研究。'}</p></div>
      {!ready ? <p className="auth-loading" role="status">正在连接账号服务…</p> : <><div className="auth-mode-switch" aria-label="登录方式"><button type="button" aria-pressed={!register} disabled={busy} onClick={() => { setRegister(false); setError('') }}>账号登录</button><button type="button" aria-label="使用邀请码注册" aria-pressed={register} disabled={busy} onClick={() => { setRegister(true); setError('') }}>邀请码注册</button></div>
      <form className="auth-form" onSubmit={async event => {
    event.preventDefault(); setError(''); setBusy(true)
    const form = new FormData(event.currentTarget)
    try { setAccount(await accountApi('/api/account/' + (register ? 'register' : 'login'), { username: form.get('username'), password: form.get('password'), ...(register ? { invite: form.get('invite') } : {}) })) }
    catch (err) { setError(err instanceof Error ? err.message : '无法连接服务') }
    finally { setBusy(false) }
  }}><label htmlFor="auth-username">用户名<input id="auth-username" name="username" required pattern="[A-Za-z0-9_]{3,32}" maxLength={32} autoComplete="username" placeholder="输入用户名" aria-describedby="auth-username-hint" disabled={busy}/></label><p id="auth-username-hint" className="auth-field-hint">3–32位字母、数字或下划线</p><label htmlFor="auth-password">密码<input id="auth-password" type="password" name="password" required minLength={10} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} placeholder={register ? '设置至少10个字符的密码' : '输入密码'} disabled={busy}/></label>{register && <label htmlFor="auth-invite">邀请码<input id="auth-invite" name="invite" required maxLength={128} autoComplete="off" placeholder="输入你的内测邀请码" disabled={busy}/></label>}{error && <p className="account-error" role="alert">{error}</p>}<button className="primary-action auth-submit" disabled={busy}>{busy ? '正在处理…' : register ? '创建账号' : '登录工作台'}<span aria-hidden="true">→</span></button></form><div className="auth-access-note"><span className="beta-badge">内测版</span><p>{register ? '当前仅开放邀请注册，邀请码由邀请方提供。' : '还没有账号？可通过上方“邀请码注册”加入内测。'}</p></div></>}
      <p className="auth-storage-note">策略随账号保存 · 恢复与修改条件不消耗 AI 调用额度</p>
    </section></main><SiteFooter/></div>
}
