import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { validateMetric } from './validation'
import type { MetricKey, Source } from './validation'
import { describeRule, directions, needsClarification, referenceConditions } from './guidance'
import { decodeStrategies, storageKey, metricKeys, makeSnapshot, validateSnapshot, snapshotFingerprint, draftFingerprint, saveStrategy, writeStrategies } from './strategies'
import type { SavedStrategy, StrategyParams, StrategySnapshot } from './strategies'
import { StrategyDrawer, SaveStrategyDialog } from './StrategyPanels'
import { accountApi, apiBase } from './accountApi'
import { AccountMenu, AccountSettings } from './AccountMenu'
import { SiteFooter } from './Brand'
import { IndustrySelector } from './IndustrySelector'
import { industryCodes, normalizeIndustry } from './industrySelection'
import type { IndustrySelection } from './industrySelection'
import { DataProvenance } from './DataProvenance'
import type { ProvenanceEntry } from './DataProvenance'
import './App.css'

type Params = StrategyParams
type Draft = Record<MetricKey, string>
type StockStatus = 'SELECTED' | 'EXCLUDED' | 'INSUFFICIENT_DATA'
type CheckStatus = 'PASS' | 'FAIL' | 'UNKNOWN'
type ResultFilter = 'ALL' | StockStatus
type Provider = 'openai' | 'deepseek'

type IconName =
  | 'sparkles' | 'arrow' | 'check' | 'info' | 'close'
  | 'chevron' | 'sliders' | 'search' | 'clock' | 'layers'
  | 'shield' | 'chart' | 'refresh'

interface IntentResponse {
  suggestions?: { metric: MetricKey; reason: string; limitation: string }[]
  industry?: IndustrySelection
  provider: Provider
  status: 'ready' | 'needs_confirmation'
  active_metrics: MetricKey[]
  interpretation: string
  parameters: Record<MetricKey, number | null>
  sources: Record<MetricKey, Source>
  questions: string[]
  unsupported: string[]
  clarifications?: string[]
  conflicts?: string[]
  model: string
}

interface Check {
  actual_text?: string
  field: string
  status: CheckStatus
  actual: number | null
  unit?: string
  reason: string
}

interface StockResult {
  data_provenance?: ProvenanceEntry[]
  industries?: { code: string; name: string }[] | null
  industry_fetched_at?: string
  thscode: string
  name: string
  status: StockStatus
  checks: Check[]
  financial_report: string
  valuation_timestamp: number | null
  kline_timestamp: number | null
  sources: Record<string, string>
  data_errors: string[]
}

interface ScreenResponse {
  snapshot_metadata?: DataStatus['metadata']
  summary: {
    selected: number
    excluded: number
    insufficient_data: number
  }
  results: StockResult[]
}

interface StockBrief {
  thscode: string
  name: string
}

interface CompareResponse {
  changes: {
    newly_selected: StockBrief[]
    no_longer_selected: StockBrief[]
    still_selected: StockBrief[]
  }
}

interface DataStatus {
  industries?: { code: string; name: string; count: number }[]
  stock_count: number
  metadata: {
    universe?: string
    universe_size?: number
    sample_size?: number
    collected_at?: string
    report?: string
    snapshot_id?: string
    last_completed_trade_date?: string
    quality?: { rows_with_warnings: number }
    industry_taxonomy?: string
  }
  refresh?: { state?: string; last_success_at?: string; progress?: string; error?: string }
  scheduler?: { state?: string; last_checked_at?: string; schedule?: string[] }
}

const API_BASE = apiBase

const metricConfig: {
  key: MetricKey
  title: string
  subtitle: string
  prompt: string
  unit: string
  placeholder: string
  details: string
  caution: string
}[] = [
  { key: 'pb_max', title: '净资产估值', subtitle: '市净率 · PB MRQ', prompt: '市净率最高不超过', unit: '倍', placeholder: '请输入上限', details: '股价相对最近报告期每股净资产的倍数。本工具按 0 < PB MRQ ≤ 上限筛选。', caution: '低市净率不代表低估，负净资产及不同行业的资产结构可能使比较失真。' },
  { key: 'roe_min', title: '资本盈利效率', subtitle: '报告期加权平均 ROE', prompt: '加权平均净资产收益率至少达到', unit: '%', placeholder: '请输入下限', details: '报告期利润相对加权平均净资产的比例，使用接口披露值，不自行年化。', caution: '不同报告期不可直接比较；高杠杆或净资产变动也可能推高 ROE。' },
  { key: 'revenue_min', title: '营收增长', subtitle: '营业收入同比增长率', prompt: '营业收入同比增长至少达到', unit: '%', placeholder: '请输入下限', details: '所用财报报告期的营业收入与去年同期相比的变化，单位为百分比。', caution: '营收增长不等于利润增长，也不代表未来增长能够持续。' },
  {
    key: 'pe_max',
    title: '估值水平',
    subtitle: '市盈率 · PE TTM',
    prompt: '市盈率最高不超过',
    unit: '倍',
    placeholder: '请输入上限',
    details: '用当前股价相对过去 12 个月每股盈利的倍数，辅助衡量估值。本工具按 0 < PE TTM ≤ 上限筛选。',
    caution: '低市盈率不一定代表低估；亏损企业通常不适用于这种筛选。',
  },
  {
    key: 'profit_min',
    title: '盈利增长',
    subtitle: '归母净利润同比增长率',
    prompt: '利润同比增长至少达到',
    unit: '%',
    placeholder: '请输入下限',
    details: '将最近选定财报报告期归属于母公司股东的净利润，与去年同期相比，衡量利润的同比变化。',
    caution: '单期增长可能受到低基数或非经常性损益影响，不能直接推断持续成长。',
  },
  {
    key: 'vol_max',
    title: '近期波动',
    subtitle: '近 20 日收益率波动率',
    prompt: '近期日收益波动率不超过',
    unit: '%',
    placeholder: '请输入上限',
    details: '最近 21 个交易日收盘价形成的 20 个日收益率的样本标准差，未年化；数值越低，历史每日收益率变化越集中。',
    caution: '波动率低不等于价格上涨或未来风险低。',
  },
]

metricConfig.sort((a, b) => metricKeys.indexOf(a.key) - metricKeys.indexOf(b.key))

const examples = [
  '我想找市场估值偏低的股票',
  '找市盈率低于20倍的股票',
  '找市盈率低于30倍、利润增长超过10%的股票',
]

const emptyDraft = Object.fromEntries(metricKeys.map(key => [key, ''])) as Draft
const emptyTouched = Object.fromEntries(metricKeys.map(key => [key, false])) as Record<MetricKey, boolean>
const emptyAccepted = { ...emptyTouched }

const stockStatusLabels: Record<StockStatus, string> = {
  SELECTED: '符合条件',
  EXCLUDED: '未符合',
  INSUFFICIENT_DATA: '数据不足',
}
const checkStatusLabels: Record<CheckStatus, string> = {
  PASS: '符合', FAIL: '不符合', UNKNOWN: '无法判断',
}

const metricFields: Record<MetricKey, string> = {
  pb_max: 'pb_mrq', roe_min: 'roe_pct', revenue_min: 'revenue_growth_pct',
  pe_max: 'pe_ttm',
  profit_min: 'parent_net_profit_growth_pct',
  vol_max: 'volatility_20d_pct',
}

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = {
    width: size, height: size, viewBox: '0 0 24 24',
    fill: 'none', stroke: 'currentColor', strokeWidth: 1.8,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
    'aria-hidden': true as const,
  }
  const shapes: Record<IconName, ReactNode> = {
    sparkles: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="m19 17 .75 2.25L22 20l-2.25.75L19 23l-.75-2.25L16 20l2.25-.75L19 17ZM4 2l.6 1.4L6 4l-1.4.6L4 6l-.6-1.4L2 4l1.4-.6L4 2Z"/></>,
    arrow: <><path d="M4 12h16"/><path d="m13 5 7 7-7 7"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></>,
    close: <path d="M18 6 6 18M6 6l12 12"/>,
    chevron: <path d="m8 10 4 4 4-4"/>,
    sliders: <><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2" fill="white"/><circle cx="16" cy="17" r="2" fill="white"/></>,
    search: <><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 5 5"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    layers: <><path d="m3 9 9-5 9 5-9 5-9-5Z"/><path d="m3 13 9 5 9-5M3 17l9 5 9-5"/></>,
    shield: <><path d="m12 3 8 4v5c0 5-3.4 8.5-8 10-4.6-1.5-8-5-8-10V7l8-4Z"/><path d="m9 12 2 2 4-4"/></>,
    chart: <><path d="M4 19V5M4 19h16"/><path d="m7 15 4-4 3 2 5-6"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 9a7 7 0 0 1 12-2l2 5M4 12l2 5a7 7 0 0 0 12-2"/></>,
  }
  return <svg {...common}>{shapes[name]}</svg>
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
  } catch {
    throw new Error('暂时无法连接服务，请稍后重试。')
  }

  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail: unknown }).detail : null
    throw new Error(typeof detail === 'string'
      ? detail : `服务请求失败（HTTP ${response.status}）`)
  }
  return payload as T
}

function formatMetric(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits)
}

function formatDate(value?: string | number | null) {
  if (value == null || value === '') return '未知'
  const milliseconds = typeof value === 'number'
    ? (value < 10_000_000_000 ? value * 1000 : value) : value
  const d = new Date(milliseconds)
  return Number.isNaN(d.getTime()) ? '未知' : d.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }) + ' (GMT+8)'
}

function getCheck(stock: StockResult, key: MetricKey) {
  return stock.checks.find(check => check.field === metricFields[key])
}

function metricTone(key: MetricKey, value: number | null | undefined) {
  if (key !== 'profit_min' || value == null) return ''
  return value > 0 ? 'figure-rise' : value < 0 ? 'figure-fall' : ''
}

function App({ accountId, username, local, onLogout }: { accountId?: string; username?: string; local?: boolean; onLogout: () => Promise<void> }) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [aiAddedMetrics, setAIAddedMetrics] = useState<MetricKey[]>([])
  const [library, setLibrary] = useState(() => {
    try { return { items: accountId ? [] : decodeStrategies(localStorage.getItem(storageKey)), error: '' } }
    catch { return { items: [] as SavedStrategy[], error: '无法读取本地策略库。原数据未被覆盖，请检查浏览器存储。' } }
  })
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [saveDialog, setSaveDialog] = useState<{ snapshot: StrategySnapshot; query: string; provider: Provider; target?: SavedStrategy; rename?: boolean } | null>(null)
  const [executedSnapshot, setExecutedSnapshot] = useState<{ snapshot: StrategySnapshot; query: string; provider: Provider } | null>(null)
  const [strategyId, setStrategyId] = useState('')
  const [libraryMessage, setLibraryMessage] = useState('')
  const revision = useRef(0)
  const [libraryReady, setLibraryReady] = useState(!accountId)
  const [query, setQuery] = useState('')
  const [editingIdea, setEditingIdea] = useState(true)
  const [provider, setProvider] = useState<Provider>('openai')
  const [analyzedQuery, setAnalyzedQuery] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [touched, setTouched] = useState(emptyTouched)
  const [activeMetrics, setActiveMetrics] = useState<MetricKey[]>([])
  const [industry, setIndustry] = useState<IndustrySelection>(null)
  const [accepted, setAccepted] = useState(emptyAccepted)
  const [intent, setIntent] = useState<IntentResponse | null>(null)
  const [dataStatus, setDataStatus] = useState<DataStatus | null>(null)
  const [dataError, setDataError] = useState(false)
  const [screen, setScreen] = useState<ScreenResponse | null>(null)
  const [lastParams, setLastParams] = useState<Params | null>(null)
  const [comparison, setComparison] = useState<CompareResponse | null>(null)
  const [selectedCode, setSelectedCode] = useState<string | null>(null)
  const [filter, setFilter] = useState<ResultFilter>('ALL')
  const [stockSearch, setStockSearch] = useState('')
  const [loading, setLoading] = useState<'interpret' | 'screen' | null>(null)
  const [error, setError] = useState('')
  const [errorStage, setErrorStage] = useState<'interpret' | 'screen'>('interpret')
  const [validated, setValidated] = useState(emptyTouched)
  const [notice, setNotice] = useState('')
  const [clarificationResolved, setClarificationResolved] = useState(false)
  const [clarifiedDirection, setClarifiedDirection] = useState('')
  const [followup, setFollowup] = useState('')
  const [referenceChosen, setReferenceChosen] = useState(emptyTouched)
  const conditionsHeading = useRef<HTMLHeadingElement>(null)
  const resultsHeading = useRef<HTMLHeadingElement>(null)
  const metricInputs = useRef<Partial<Record<MetricKey, HTMLInputElement | null>>>({})
  // 指标帮助弹窗始终只有一个打开，不参与卡片的文档流高度计算。
  const [openHelp, setOpenHelp] = useState<MetricKey | null>(null)
  const loadedStrategy = library.items.find(item => item.id === strategyId)
  const currentDraftFingerprint = draftFingerprint(query, provider, makeSnapshot(draft, activeMetrics, industry))
  const unsavedChanges = loadedStrategy ? currentDraftFingerprint !== draftFingerprint(loadedStrategy.query, loadedStrategy.provider, loadedStrategy.snapshot) : Boolean(query.trim() || intent)
  function allowDraftReplacement() {
    return !unsavedChanges || window.confirm('当前有未保存的修改，继续将替换当前草稿，是否继续？')
  }

  async function reloadLibrary() {
    if (accountId) {
      try {
        const data = await accountApi<{ revision: number; items: SavedStrategy[] }>('/api/account/strategies')
        setLibrary({ items: decodeStrategies(JSON.stringify({ version: 1, items: data.items })), error: '' })
        revision.current = data.revision; setLibraryReady(true)
      } catch { setLibrary(previous => ({ ...previous, error: '无法读取账号策略，已阻止覆盖，请重试。' })) }
      return
    }
    try { setLibrary({ items: decodeStrategies(localStorage.getItem(storageKey)), error: '' }) }
    catch { setLibrary({ items: [], error: '本地策略数据损坏或版本不兼容，请处理原存储后重试；未覆盖原数据。' }) }
  }
  useEffect(() => {
    if (accountId) return
    const changed = (event: StorageEvent) => { if (event.key === storageKey || event.key === null) reloadLibrary() }
    window.addEventListener('storage', changed)
    return () => window.removeEventListener('storage', changed)
  }, [accountId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!accountId) return
    let active = true
    void accountApi<{ revision: number; items: SavedStrategy[] }>('/api/account/strategies').then(data => {
      if (!active) return
      const items = decodeStrategies(JSON.stringify({ version: 1, items: data.items }))
      revision.current = data.revision; setLibrary({ items, error: '' }); setLibraryReady(true)
    }).catch(() => { if (active) setLibrary({ items: [], error: '无法读取账号策略，请重试。' }) })
    return () => { active = false }
  }, [accountId])

  useEffect(() => {
    let cancelled = false
    const refreshStatus = () => void api<DataStatus>('/api/data/status')
      .then(status => { if (!cancelled) { setDataStatus(status); setDataError(false) } })
      .catch(() => { if (!cancelled) setDataError(true) })
    refreshStatus()
    const timer = window.setInterval(refreshStatus, 60_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    if (!intent) return
    const frame = requestAnimationFrame(() => {
      conditionsHeading.current?.focus({ preventScroll: true })
      conditionsHeading.current?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
        block: 'start',
      })
    })
    return () => cancelAnimationFrame(frame)
  }, [intent])

  useEffect(() => {
    if (!screen) return
    const frame = requestAnimationFrame(() => {
      resultsHeading.current?.focus({ preventScroll: true })
      resultsHeading.current?.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
        block: 'start',
      })
    })
    return () => cancelAnimationFrame(frame)
  }, [screen])

  const providerChanged = intent !== null && intent.provider !== provider
  const queryChanged = (analyzedQuery !== null && query.trim() !== analyzedQuery) || providerChanged
  const snapshotChanged = screen?.snapshot_metadata?.snapshot_id && dataStatus?.metadata.snapshot_id &&
    screen.snapshot_metadata.snapshot_id !== dataStatus.metadata.snapshot_id &&
    (!screen.snapshot_metadata.collected_at || !dataStatus.metadata.collected_at ||
      Date.parse(dataStatus.metadata.collected_at) > Date.parse(screen.snapshot_metadata.collected_at))
  const hasConflicts = Boolean(intent?.conflicts?.length)
  const showGuidance = intent !== null && !hasConflicts && needsClarification(intent, clarificationResolved)
  const conditionCount = activeMetrics.length + (industry ? 1 : 0)
  const changedParams = lastParams !== null && (queryChanged || (executedSnapshot && snapshotFingerprint(makeSnapshot(draft, activeMetrics, industry)) !== snapshotFingerprint(executedSnapshot.snapshot)) || JSON.stringify(industryCodes(industry)) !== JSON.stringify(industryCodes(lastParams.industry)) || metricConfig.some(item => {
    const now = activeMetrics.includes(item.key) && draft[item.key].trim()
      ? Number(draft[item.key]) : null
    return now !== lastParams[item.key]
  }))
  const executedMetrics = metricConfig.filter(item => lastParams?.[item.key] !== null && lastParams !== null)
  const availableMetrics = metricConfig.filter(item => !activeMetrics.includes(item.key))

  const rows = useMemo(() => {
    const rank: Record<StockStatus, number> = {
      SELECTED: 0, INSUFFICIENT_DATA: 1, EXCLUDED: 2,
    }
    return [...(screen?.results ?? [])]
      .filter(stock => filter === 'ALL' || stock.status === filter)
      .filter(stock => !stockSearch.trim() || `${stock.name} ${stock.thscode}`
        .toLowerCase().includes(stockSearch.trim().toLowerCase()))
      .sort((a, b) => rank[a.status] - rank[b.status])
  }, [screen, filter, stockSearch])

  const selectedStock = screen?.results.find(stock => stock.thscode === selectedCode)

  useEffect(() => {
    if (!selectedCode) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelectedCode(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectedCode])

  // 点击说明层之外的位置、或按 Escape，即可关闭悬浮信息层。
  useEffect(() => {
    if (!openHelp) return
    const onPointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Element) ||
          !event.target.closest('[data-condition-help]')) {
        setOpenHelp(null)
      }
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenHelp(null)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [openHelp])

  function selectExample(example: string, restoring = false) {
    setAIAddedMetrics([])
    if (!restoring && !allowDraftReplacement()) return
    setStrategyId('')
    setExecutedSnapshot(null)
    setEditingIdea(true)
    setQuery(example)
    setAnalyzedQuery(null)
    setIntent(null)
    setClarificationResolved(false)
    setClarifiedDirection('')
    setFollowup('')
    setReferenceChosen(emptyTouched)
    setDraft(emptyDraft)
    setTouched(emptyTouched)
    setValidated(emptyTouched)
    setAccepted(emptyAccepted)
    setActiveMetrics([])
    setIndustry(null)
    setScreen(null)
    setComparison(null)
    setLastParams(null)
    setSelectedCode(null)
    setNotice('')
    setError('')
    setOpenHelp(null)
  }

  async function analyze(supplement?: string) {
    if (intent && !window.confirm('重新解析将替换当前编辑条件。已保存策略保持原样，是否继续？')) return
    setOpenHelp(null)
    setErrorStage('interpret')
    const text = supplement ?? query.trim()
    if (text.length < 2) {
      setError('请先用一句话描述你的选股需求。')
      return
    }
    setError(''); setNotice(''); setLoading('interpret')
    if (supplement !== undefined) setQuery(text)
    try {
      const result = await api<IntentResponse>('/api/interpret', { text, provider })
      setIntent(result)
      setAIAddedMetrics([])
      setIndustry(normalizeIndustry(result.industry ?? null))
      setEditingIdea(false)
      setClarificationResolved(false)
      setClarifiedDirection('')
      setFollowup('')
      setReferenceChosen(emptyTouched)
      setActiveMetrics(metricConfig.map(m => m.key).filter(key => result.active_metrics.includes(key)))
      setAccepted(emptyAccepted)
      setAnalyzedQuery(text)
      setDraft(Object.fromEntries(metricKeys.map(key => [key, result.parameters[key]?.toString() ?? ''])) as Draft)
      setTouched(emptyTouched)
      setValidated(emptyTouched)
      setScreen(null)
      setComparison(null)
      setLastParams(null)
      setSelectedCode(null)
      setFilter('ALL')
      setStockSearch('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 解析失败，请稍后重试。')
    } finally {
      setLoading(null)
    }
  }

  function updateDraft(key: MetricKey, value: string) {
    setDraft(previous => ({ ...previous, [key]: value }))
    setTouched(previous => ({ ...previous, [key]: true }))
    setReferenceChosen(previous => ({ ...previous, [key]: false }))
    setError('')
  }

  function removeMetric(key: MetricKey) {
    setActiveMetrics(previous => previous.filter(item => item !== key))
    setOpenHelp(null)
    setError('')
  }

  function addMetric(key: MetricKey) {
    setActiveMetrics(previous => metricConfig.map(item => item.key)
      .filter(item => previous.includes(item) || item === key))
    setTouched(previous => ({ ...previous, [key]: draft[key].trim() ? previous[key] : true }))
    setValidated(previous => ({ ...previous, [key]: false }))
    setReferenceChosen(previous => ({ ...previous, [key]: false }))
    setError('')
  }

  function chooseDirection(key: MetricKey) {
    if (!activeMetrics.includes(key)) addMetric(key)
    setClarificationResolved(true)
    setClarifiedDirection(directions.find(direction => direction.key === key)?.label ?? '')
    requestAnimationFrame(() => conditionsHeading.current?.focus({ preventScroll: true }))
  }

  function chooseReference(key: MetricKey, value: number) {
    updateDraft(key, String(value))
    setReferenceChosen(previous => ({ ...previous, [key]: true }))
  }

  function acceptSuggestion(key: MetricKey) {
    setAccepted(previous => ({ ...previous, [key]: true }))
    setError('')
  }

  async function runScreen(useLatest = false) {
    setErrorStage('screen')
    if (!intent) {
      setError('请先让 AI 将你的自然语言需求解析为筛选条件。')
      return
    }
    if (queryChanged) {
      setError('描述或 AI 服务已改变，请先重新解析需求。')
      return
    }
    if (showGuidance) {
      setError('请先补充你更看重的方向。')
      return
    }
    if (intent.conflicts?.length) {
      setError('需求中有互相冲突的条件，请修改描述并重新解析。')
      return
    }
    if (intent.unsupported.length > 0) {
      setError('你的需求包含当前版本不支持的条件，请修改描述并重新解析。')
      return
    }
    if (conditionCount === 0) {
      setError('请至少添加一个筛选条件。')
      return
    }
    setError('')
    setValidated(Object.fromEntries(metricKeys.map(key => [key, true])) as Record<MetricKey, boolean>)
    const invalidKey = activeMetrics.find(key => validateMetric(key, draft[key], intent.sources[key], touched[key], accepted[key]))
    if (invalidKey) {
      metricInputs.current[invalidKey]?.focus()
      return
    }
    const nextParams = Object.fromEntries(metricKeys.map(key => [key, null])) as Params
    nextParams.industry = industry
    for (const key of activeMetrics) nextParams[key] = Number(draft[key])
    setError(''); setNotice(''); setLoading('screen')
    try {
      const pinnedSnapshot = useLatest ? undefined : screen?.snapshot_metadata?.snapshot_id
      const next = await api<ScreenResponse>('/api/screen', { ...nextParams, snapshot_id: pinnedSnapshot })
      let diff: CompareResponse | null = null
      if (lastParams && pinnedSnapshot && next.snapshot_metadata?.snapshot_id === pinnedSnapshot &&
          (JSON.stringify(industryCodes(lastParams.industry)) !== JSON.stringify(industryCodes(nextParams.industry)) || metricConfig.some(item => lastParams[item.key] !== nextParams[item.key]))) {
        try {
          diff = await api<CompareResponse>('/api/compare', {
            before: lastParams, after: nextParams, snapshot_id: next.snapshot_metadata?.snapshot_id,
          })
        } catch {
          setNotice('筛选成功，但条件变化对比暂不可用。')
        }
      }
      setScreen(next)
      setComparison(diff)
      setLastParams(nextParams)
      setExecutedSnapshot({ snapshot: makeSnapshot(draft, activeMetrics, industry), query: analyzedQuery || '', provider: intent.provider })
      setSelectedCode(null)
      setFilter('ALL')
      setStockSearch('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '筛选失败，请稍后重试。')
    } finally {
      setLoading(null)
    }
  }

  const currentStage = !intent || editingIdea || queryChanged ? 1 : screen && !changedParams ? 3 : 2
  const counts = screen ? [
    { value: screen.summary.selected, label: '符合条件', sub: 'SELECTED', kind: 'selected' },
    { value: screen.summary.excluded, label: '未符合', sub: 'EXCLUDED', kind: 'excluded' },
    { value: screen.summary.insufficient_data, label: '数据不足', sub: 'UNKNOWN', kind: 'unknown' },
  ] : []

  async function persistStrategies(items: SavedStrategy[]) {
    if (!libraryReady) { setLibraryMessage('策略库尚未加载，请稍后重试。'); return false }
    if (library.error) { setLibraryMessage(library.error); return false }
    try {
      if (accountId) {
        const data = await accountApi<{ revision: number; items: SavedStrategy[] }>('/api/account/strategies', { revision: revision.current, items }, 'PUT')
        revision.current = data.revision
        setLibrary({ items: decodeStrategies(JSON.stringify({ version: 1, items: data.items })), error: '' })
      } else setLibrary({ items: writeStrategies(localStorage, library.items, items), error: '' })
      return true
    } catch (err) { setLibraryMessage(err instanceof Error ? `保存失败：${err.message}` : '保存失败，请检查浏览器存储权限或可用空间。'); return false }
  }

  function saveExecutedStrategy() {
    if (!executedSnapshot) return
    setLibraryMessage('')
    setSaveDialog(executedSnapshot)
  }

  function openCurrentSave(update = false) {
    setErrorStage('screen')
    if (!intent || queryChanged || showGuidance || hasConflicts || intent.unsupported.length) return
    setValidated(Object.fromEntries(metricKeys.map(key => [key, true])) as Record<MetricKey, boolean>)
    const invalid = activeMetrics.find(key => validateMetric(key, draft[key], intent.sources[key], touched[key], accepted[key]))
    if (invalid) { setError(validateMetric(invalid, draft[invalid], intent.sources[invalid], touched[invalid], accepted[invalid])); metricInputs.current[invalid]?.focus(); return }
    const snapshot = makeSnapshot(draft, activeMetrics, industry)
    try { validateSnapshot(snapshot) } catch (err) { setError((err as Error).message); return }
    setLibraryMessage('')
    setSaveDialog({ snapshot, query, provider, target: update ? loadedStrategy : undefined })
  }

  async function confirmSave(name: string) {
    if (!saveDialog) return
    const now = new Date().toISOString()
    const target = saveDialog.target
    if (!target && library.items.length >= 30) { setLibraryMessage('最多保存 30 条策略，请先删除不需要的方案。'); return }
    const item: SavedStrategy = { schemaVersion: 2, id: target?.id || crypto.randomUUID(), name, query: saveDialog.query, provider: saveDialog.provider,
      snapshot: saveDialog.snapshot, params: {} as Params, createdAt: target?.createdAt || now, updatedAt: now, savedAt: now }
    let next: SavedStrategy[]
    try { next = saveStrategy(library.items, item, Boolean(target)) }
    catch (err) { setLibraryMessage((err as Error).message); return }
    if (await persistStrategies(next)) {
      if (!saveDialog.rename && currentDraftFingerprint === draftFingerprint(item.query, item.provider, item.snapshot)) setStrategyId(item.id)
      setSaveDialog(null)
      setNotice('策略已保存，可从顶部“我的策略”载入。')
      setLibraryMessage('策略已保存。')
    }
  }

  function restoreStrategy(item: SavedStrategy) {
    if (loading) return
    if (!allowDraftReplacement()) return
    setDrawerOpen(false)
    selectExample(item.query, true)
    setStrategyId(item.id)
    setProvider(item.provider)
    setIndustry(item.params.industry)
    setAnalyzedQuery(item.query.trim())
    setEditingIdea(false)
    setActiveMetrics(metricKeys.filter(key => item.params[key] !== null))
    setDraft(Object.fromEntries(item.snapshot.conditions.map(c => [c.metricId, c.value?.toString() ?? ''])) as Draft)
    setIntent({ industry: item.params.industry, provider: item.provider, model: '本地保存的条件', status: 'ready', active_metrics: metricKeys.filter(key => item.params[key] !== null), parameters: { ...item.params }, sources: Object.fromEntries(metricKeys.map(key => [key, 'user'])) as Record<MetricKey, Source>, questions: [], unsupported: [], interpretation: '已恢复你保存的执行条件，请核对后使用最新数据筛选。原始描述仅供参考，以已保存条件为准。' })
    setNotice('策略已恢复。确认执行后使用最新数据；没有恢复旧结果。')
    setLibraryMessage('已恢复策略，请核对下方条件。')
  }

  return (
    <div className="site-shell">
      <header className="site-header">
        <div className="header-inner">
          <div className="identity" aria-label="StockLens 首页">
            <span className="identity-mark"><Icon name="chart" size={21} /></span>
            <span className="identity-name">StockLens<span className="identity-period">.</span></span>
            <span className="identity-separator" />
            <span className="identity-caption">投资偏好筛选工作台</span>
          </div>
          <div className="header-meta">
            <span className="header-version">PRODUCT PREVIEW / 0.4</span>
            <div className="header-data-summary">
            <details className="header-collected"><summary><span>数据采集时间</span><time dateTime={dataStatus?.metadata.collected_at}>{dataStatus?.metadata.collected_at ? formatDate(dataStatus.metadata.collected_at) : '暂不可用'}</time></summary><div className="collection-tooltip"><p>计划更新：交易日 (GMT+8) 09:30 / 11:30 / 13:00 / 15:00。</p><p>{dataStatus?.scheduler?.last_checked_at ? `调度最近检查：${formatDate(dataStatus.scheduler.last_checked_at)}` : '自动调度尚未启动，需在常在线服务器运行。'}</p>{dataStatus?.refresh?.state === 'running' && <p>正在更新：{dataStatus.refresh.progress}。校验完成前继续使用原快照。</p>}{dataStatus?.refresh?.state === 'failed' && <p>最近更新失败，已保留上一份可用快照。</p>}</div></details>
            <div className={`data-indicator ${dataError ? 'data-offline' : ''}`}>
              <span className="live-dot" />
              {dataStatus ? `沪深300 · 已加载 ${dataStatus.stock_count} 只`
                : dataError ? '数据连接异常' : '正在连接金融数据'}
            </div>
            </div>
            <AccountMenu username={username} local={local} onStrategies={() => { void reloadLibrary(); setDrawerOpen(true) }} onSettings={() => setSettingsOpen(true)} onLogout={onLogout}/>
          </div>
        </div>
      </header>

      <main className="main-container">
        <div className="progress-strip" aria-label="选股流程进度">
          {[
            { num: 1, name: '描述需求' },
            { num: 2, name: '确认条件' },
            { num: 3, name: '查看结果' },
          ].map((step, i) => (
            <div className={`progress-step ${currentStage === step.num ? 'is-current' : ''} ${currentStage > step.num ? 'is-done' : ''}`} aria-current={currentStage === step.num ? 'step' : undefined} key={step.num}>
              <span className="progress-number">{currentStage > step.num ? <Icon name="check" size={13}/> : `0${step.num}`}</span>
              <span>{step.name}</span>
              {i < 2 && <span className="progress-connector" />}
            </div>
          ))}
        </div>

        {!intent && <section className="hero" aria-labelledby="hero-title">
          <div className="hero-overline"><span className="overline-dash" /> INTELLIGENT STOCK DISCOVERY</div>
          <h1 id="hero-title">你的选股想法，<span>值得有据可循。</span></h1>
          <p className="hero-subtitle">以想法定义方向，以数据检验结果。</p>
        </section>}

        <section className="composer-section" aria-labelledby="intent-title">
          {intent && !editingIdea && <div className="idea-summary"><div><h2 id="intent-title">你的选股想法</h2><p>{analyzedQuery}</p><span>{intent.provider === 'deepseek' ? 'DeepSeek' : 'OpenAI'} · 已解析</span></div><button type="button" className="add-metric-button" disabled={loading !== null} onClick={() => { setEditingIdea(true); requestAnimationFrame(() => document.getElementById('stock-query')?.focus()) }}>修改需求 / AI 服务</button></div>}
          <div hidden={Boolean(intent) && !editingIdea}>
          <h2 className="visually-hidden" id={intent && !editingIdea ? undefined : 'intent-title'}>描述你的投资偏好</h2>

          <div className="composer-card">
            <div className="composer-topline"><div className="composer-title"><Icon name="sparkles" size={17}/><span>自然语言选股</span></div>{!intent && <div className="examples">
            <span className="examples-label">试试这些描述</span>
            <div className="example-buttons">
              {examples.map((sample, i) => <button className="example-chip" key={sample} onClick={() => selectExample(sample)} type="button" disabled={loading !== null}>
                <span>0{i + 1}</span>{i === 0 ? '只看低估值' : i === 1 ? '明确市盈率阈值' : '估值与盈利双条件'}<Icon name="arrow" size={13}/>
              </button>)}
            </div>
          </div>}</div>
            <label htmlFor="stock-query" className="visually-hidden">描述你的选股需求</label>
            <textarea
              id="stock-query"
              className="query-input"
              value={query}
              readOnly={loading === 'interpret'}
              maxLength={500}
              rows={2}
              onChange={event => { setQuery(event.target.value); setError('') }}
              placeholder="例如：我想找盈利在增长、估值不算太高，而且近期价格比较稳定的股票……"
            />
            <div className="composer-actions">
              <div className="composer-model"><label htmlFor="ai-provider">AI 服务</label><div className="provider-select-wrap"><select id="ai-provider" value={provider} disabled={loading !== null} onChange={event => { setProvider(event.target.value as Provider); setError(''); setNotice('') }}><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option></select><Icon name="chevron" size={14}/></div></div>
              <div className="composer-submit"><span className="character-count">{query.length} / 500</span>
                {intent && <button type="button" className="composer-cancel" disabled={loading !== null} onClick={() => { setQuery(analyzedQuery ?? ''); setProvider(intent.provider); setEditingIdea(false); setError(''); setNotice('') }}>取消修改</button>}
                <button className="primary-action" type="button" onClick={() => void analyze()} disabled={loading !== null}>
                  <Icon name="sparkles" size={17}/>
                  {loading === 'interpret' ? '正在理解需求…' : intent ? '重新解析需求' : '解析选股需求'}
                  {loading !== 'interpret' && <Icon name="arrow" size={17}/ >}
                </button>
              </div>
            </div>
          </div>
          <p className="composer-hint">AI 不生成股票数据，不直接给出买卖建议</p>



          {queryChanged && intent && <div className="inline-note tone-warn"><Icon name="info" size={16}/>{providerChanged ? '已切换 AI 服务。请重新解析；下方仍保留切换前的条件与结果。' : '描述已发生变化。请点击「重新解析需求」更新下面的条件。'}</div>}
          </div>
        </section>

        {error && errorStage === 'interpret' && <div className="system-message message-error" role="alert"><Icon name="info" size={18}/><span>{error}</span><button type="button" aria-label="关闭错误提示" onClick={() => setError('')}><Icon name="close" size={17}/></button></div>}

        {intent && <section className="conditions-section" aria-labelledby="conditions-title">
          <div className="section-heading">
            <div className="section-title-group"><span className="section-number">02</span><div><h2 id="conditions-title" ref={conditionsHeading} tabIndex={-1}>{showGuidance ? '明确你的筛选方向' : '确认你的选股条件'}</h2><p className="conditions-intro">{showGuidance ? '这个偏好还需要具体化。选择关注维度，或补充你的判断标准。' : '核对指标含义、阈值和来源，确认后执行。'}</p></div></div>
            {conditionCount > 0 && <div className="section-right-meta"><span className="quiet-pill">{conditionCount} 项条件 · 全部满足</span></div>}
          </div>

          <div className="conditions-workspace"><div className="conditions-editor">
          {loadedStrategy && <div className="inline-note" role="status">{loadedStrategy.name} · {unsavedChanges ? '有未保存的修改' : '已保存'}</div>}
          {Boolean(intent.conflicts?.length) && <div className="unsupported-panel" role="alert"><strong>这些条件无法同时满足</strong><ul>{intent.conflicts!.map((item, i) => <li key={i}>{item}</li>)}</ul><button type="button" className="add-metric-button" onClick={() => { setEditingIdea(true); requestAnimationFrame(() => document.getElementById('stock-query')?.focus()) }}>修改冲突条件</button></div>}
          {intent.unsupported.length > 0 && <div className="unsupported-panel" role="alert"><strong>以下需求暂不支持，不能直接执行：</strong><ul>{intent.unsupported.map((item, i) => <li key={i}>{item}</li>)}</ul><p>请修改上面的描述并重新解析。</p><button type="button" className="add-metric-button" onClick={() => { setEditingIdea(true); requestAnimationFrame(() => document.getElementById('stock-query')?.focus()) }}>修改需求</button></div>}

          {showGuidance && <div className="guidance-panel">
            <p className="guidance-context">{intent.clarifications?.length ? intent.clarifications.join('；') : '先把你的想法具体化，再筛选。'}</p>
            <div className="guidance-choices">{directions.map(direction => <button type="button" key={direction.key} disabled={loading !== null || queryChanged} onClick={() => chooseDirection(direction.key)}><strong>{direction.label}<Icon name="arrow" size={16}/></strong><span>{direction.explanation}</span></button>)}</div>
            <div className="guidance-followup"><label htmlFor="clarification-answer">或者，用你自己的话补充</label><div><input id="clarification-answer" value={followup} maxLength={Math.max(0, 500 - (analyzedQuery?.length ?? 0) - '\n补充说明：'.length)} placeholder="例如：我更关心公司赚的钱有没有增加" onChange={event => setFollowup(event.target.value)} disabled={loading !== null || queryChanged}/><button className="primary-action" type="button" disabled={loading !== null || queryChanged || followup.trim().length < 2} onClick={() => void analyze(`${analyzedQuery}\n补充说明：${followup.trim()}`)}>{loading === 'interpret' ? '正在理解…' : '继续解析'}</button></div></div>
          </div>}

          {!showGuidance && !hasConflicts && !intent.unsupported.length && Boolean(intent.suggestions?.some(item => !activeMetrics.includes(item.metric))) && <details className="ai-suggestions" open><summary>AI 可选补充 · 尚未参与筛选</summary><p className="ai-review-intro">{intent.interpretation}</p>{intent.suggestions?.filter(item => !activeMetrics.includes(item.metric)).map(item => <article key={item.metric}><div><strong>{metricConfig.find(metric => metric.key === item.metric)?.title}</strong><p>{item.reason}</p><small>边界：{item.limitation}</small></div><button className="add-metric-button" type="button" disabled={loading !== null || queryChanged} onClick={() => { addMetric(item.metric); setAIAddedMetrics(previous => [...new Set([...previous, item.metric])]); setNotice('已加入补充指标，请设置并确认阈值后执行。') }}>加入指标</button></article>)}</details>}

          <IndustrySelector value={industry} options={dataStatus?.industries || []} disabled={loading !== null} onChange={value => { setIndustry(value); if (!intent.clarifications?.length) setClarificationResolved(true); setError('') }}/>
          <div className={`condition-grid count-${activeMetrics.length}`}>
            {metricConfig.filter(metric => activeMetrics.includes(metric.key)).map((metric, i) => {
              const source = touched[metric.key] ? 'modified' : intent.sources[metric.key]
              const sourceLabel = referenceChosen[metric.key] ? '参考条件 · 已选择' : aiAddedMetrics.includes(metric.key) ? 'AI 补充 · 由你加入' : source === 'modified' ? '由你设定' : intent.model === '本地保存的条件' ? '来自已保存策略' : source === 'user' ? '来自你的描述' : source === 'suggested' ? (accepted[metric.key] ? '已接受 AI 建议' : 'AI 建议 · 待确认') : '待补充数值'
              const fieldError = validated[metric.key] ? validateMetric(metric.key, draft[metric.key], intent.sources[metric.key], touched[metric.key], accepted[metric.key]) : ''
              return <article className={`condition-card ${openHelp === metric.key ? 'is-help-open' : ''}`} key={metric.key}>
                <div className="condition-topline">
                  <span className="condition-index">0{i + 1} / 0{activeMetrics.length}</span>
                  <span className={`condition-source source-${source}`}>{sourceLabel}</span>
                  <button className="condition-remove" type="button" aria-label={`移除${metric.title}筛选条件`} onClick={() => removeMetric(metric.key)}><Icon name="close" size={15}/></button>
                </div>

                <div className="condition-heading">
                  <div className="condition-title-line">
                    <h3>{metric.title}</h3>
                    <div className="condition-help-anchor" data-condition-help>
                      <button
                        type="button"
                        className="condition-help-trigger"
                        aria-label={`了解${metric.title}指标`}
                        aria-expanded={openHelp === metric.key}
                        aria-controls={`condition-help-${metric.key}`}
                        onClick={() => setOpenHelp(current => current === metric.key ? null : metric.key)}
                      >
                        <Icon name="info" size={17}/>
                      </button>
                      {openHelp === metric.key && <div
                        id={`condition-help-${metric.key}`}
                        className="condition-help-popover"
                        role="dialog"
                        aria-label={`${metric.title}指标说明`}
                      >
                        <div className="condition-help-head">
                          <strong>{metric.subtitle}是什么？</strong>
                          <button type="button" aria-label="关闭指标说明" onClick={() => setOpenHelp(null)}>
                            <Icon name="close" size={15}/>
                          </button>
                        </div>
                        <p>{metric.details}</p>
                        <div className="condition-help-caution"><Icon name="info" size={15}/><span>{metric.caution}</span></div>
                      </div>}
                    </div>
                  </div>
                  <p className="condition-subtitle">{metric.subtitle}</p>
                </div>

                <div className="condition-value-editor">
                <label htmlFor={`metric-${metric.key}`} className="condition-label">{metric.prompt}</label>
                <div className={`metric-input-wrap ${fieldError ? 'has-error' : ''}`}>
                  <input id={`metric-${metric.key}`} ref={element => { metricInputs.current[metric.key] = element }} type="number" step={metric.key === 'vol_max' ? 0.1 : 1} value={draft[metric.key]} placeholder={metric.placeholder} aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? `error-${metric.key}` : undefined} onChange={event => updateDraft(metric.key, event.target.value)} onBlur={() => setValidated(previous => ({ ...previous, [metric.key]: true }))}/>
                  <span>{metric.unit}</span>
                </div>
                {fieldError && <p className="field-error" id={`error-${metric.key}`} role="alert"><Icon name="info" size={14}/><span>{fieldError}</span></p>}
                {(draft[metric.key].trim() === '' || referenceChosen[metric.key]) && <details className="reference-conditions"><summary>查看阈值示例</summary><div>{referenceConditions[metric.key].map(option => <button type="button" key={option.value} aria-pressed={referenceChosen[metric.key] && Number(draft[metric.key]) === option.value} onClick={() => chooseReference(metric.key, option.value)}>{option.label}</button>)}</div><small>示例用于观察条件变化对结果的影响，未经回测验证。点击后填入，执行前仍可修改。</small></details>}
                {source === 'suggested' && !accepted[metric.key] &&
                  <button className="suggestion-accept" type="button" onClick={() => acceptSuggestion(metric.key)}><Icon name="check" size={14}/>确认采用 AI 建议值</button>}
                </div>
              </article>
            })}
          </div>

          {conditionCount === 0 && !showGuidance && intent.unsupported.length === 0 && <div className="no-condition-message">选择一个你关注的方向，即可继续。</div>}
          {!showGuidance && availableMetrics.length > 0 && <div className="add-metric-row"><span>还想关注什么？</span>{availableMetrics.map(item => <button type="button" className="add-metric-button" key={item.key} onClick={() => addMetric(item.key)}>＋ {directions.find(direction => direction.key === item.key)?.label}</button>)}</div>}

          <details className="interpretation-details"><summary>查看需求与规则说明<Icon name="chevron" size={15}/></summary><p>{clarificationResolved ? `你已补充关注方向：${clarifiedDirection}。具体以当前启用的条件为准。` : intent.interpretation}</p><p>解析来源：{intent.provider === 'deepseek' ? 'DeepSeek' : 'OpenAI'} · {intent.model}</p><p>仅按已启用条件筛选，所有条件需同时满足。指标口径可点击卡片标题旁的 ⓘ 查看。</p></details>

          </div><aside className="screen-overview" aria-labelledby="screen-overview-title"><h3 id="screen-overview-title">筛选概览</h3><dl><div><dt>分析范围</dt><dd>{dataStatus?.metadata.universe || '等待数据连接'}</dd></div><div><dt>已加载股票</dt><dd>{dataStatus ? `${dataStatus.stock_count} 只` : '暂不可用'}</dd></div><div><dt>当前条件</dt><dd>{conditionCount} 项 · 全部满足</dd></div><div><dt>数据状态</dt><dd>{dataError ? '状态连接异常' : dataStatus ? '快照已加载' : '正在连接'}</dd></div></dl><p className="overview-hint">{showGuidance ? '先明确关注方向，再确认具体条件。' : queryChanged ? '需求已变化，请先重新解析。' : '核对已启用条件，确认后查看每只股票的筛选依据。'}</p>
          {conditionCount > 0 && <div className="conditions-footer"><div className="screen-primary-actions"><button type="button" className="add-metric-button save-strategy-action" disabled={loading !== null || queryChanged || showGuidance || hasConflicts || intent.unsupported.length > 0} onClick={() => openCurrentSave(Boolean(loadedStrategy))}>{loadedStrategy ? '保存更改' : '保存策略'}</button><button className="primary-action large-action" type="button" disabled={loading !== null || queryChanged || showGuidance || hasConflicts || intent.unsupported.length > 0} onClick={() => void runScreen()}><Icon name="sliders" size={18}/>{loading === 'screen' ? '正在筛选…' : screen ? '按当前条件重新筛选' : '确认并执行筛选'}<Icon name="arrow" size={18}/></button></div>{loadedStrategy && <button type="button" className="save-as-action" disabled={loading !== null || queryChanged || showGuidance || hasConflicts || intent.unsupported.length > 0} onClick={() => openCurrentSave()}>另存为新策略</button>}<p>基于扶摇数据快照筛选，不构成投资建议。</p></div>}
          {error && errorStage === 'screen' && <div className="system-message message-error" role="alert"><Icon name="info" size={18}/><span>{error}</span><button type="button" aria-label="关闭错误提示" onClick={() => setError('')}><Icon name="close" size={17}/></button></div>}
          {notice && !error && <div className="system-message message-info" role="status"><Icon name="info" size={18}/><span>{notice}</span><button type="button" aria-label="关闭通知" onClick={() => setNotice('')}><Icon name="close" size={17}/></button></div>}
          </aside></div>
        </section>}

        {screen && <section className="results-section" aria-labelledby="results-title">
          <div className="section-heading"><div className="section-title-group"><span className="section-number">03</span><div><h2 id="results-title" ref={resultsHeading} tabIndex={-1}>每只股票，都有筛选依据</h2></div></div><span className="section-aside">基于同一份数据快照</span></div>

          <div className="results-surface">
            <div className="applied-rules"><strong>本次执行条件 · 全部满足</strong><button type="button" className="add-metric-button" disabled={loading !== null || Boolean(library.error)} onClick={saveExecutedStrategy}>保存策略参数</button><div>{executedMetrics.map(metric => <span key={metric.key}>{describeRule(metric.key, lastParams![metric.key]!)}</span>)}{lastParams?.industry && <span>行业满足任一项：{industryCodes(lastParams.industry).map(code => screen.results.flatMap(row => row.industries || []).find(item => item.code === code)?.name || code).join('、')}</span>}</div></div>
            {screen.snapshot_metadata?.snapshot_id && <div className="snapshot-choice"><span>{snapshotChanged ? '已有新数据。调整条件仍沿用本次快照，便于比较。' : '调整条件沿用本次快照；也可主动重新获取最新数据。'}</span><button type="button" className="add-metric-button" disabled={loading !== null || queryChanged || showGuidance || hasConflicts || Boolean(intent?.unsupported.length)} onClick={() => void runScreen(true)}>使用最新数据重新筛选</button></div>}
            {changedParams && <div className="stale-warning"><Icon name="info" size={17}/>你已调整筛选条件；下方仍是上次执行的结果。请重新筛选后查看变化。</div>}
            <div className="results-summary">
              <div className="results-summary-lead"><span className="eyebrow-small">SCREENING OVERVIEW</span><strong>本次筛选概览</strong><p>针对已加载的 {screen.results.length} 只股票进行判断</p></div>
              <div className="summary-stats">{counts.map(item => <div className={`summary-stat ${item.kind}`} key={item.kind}><span>{item.label}</span><strong>{item.value}<small>只</small></strong><span className="stat-en">{item.sub}</span></div>)}</div>
            </div>

            <div className="result-toolbar"><div className="filter-group" aria-label="筛选状态">
              {([
                ['ALL', '全部', screen.results.length],
                ['SELECTED', '符合', screen.summary.selected],
                ['EXCLUDED', '未符合', screen.summary.excluded],
                ['INSUFFICIENT_DATA', '数据不足', screen.summary.insufficient_data],
              ] as [ResultFilter, string, number][]).map(([key, label, count]) => <button key={key} type="button" className={`filter-button ${filter === key ? 'active' : ''}`} onClick={() => setFilter(key)}>{label}<span>{count}</span></button>)}
            </div><label className="table-search"><Icon name="search" size={16}/><span className="visually-hidden">搜索股票名称或代码</span><input value={stockSearch} onChange={event => setStockSearch(event.target.value)} placeholder="搜索股票 / 代码" /></label></div>

            <div className="table-scroll" role="region" aria-label="股票筛选结果，可横向滚动" tabIndex={0}><table className="stock-table"><thead><tr><th>股票名称</th>{lastParams?.industry && <th>同花顺行业</th>}{executedMetrics.map(metric => <th key={metric.key} className="numeric-cell">{metric.title}<small>{metric.subtitle}</small></th>)}<th>筛选判断</th><th aria-label="详细信息"/></tr></thead><tbody>
              {rows.map(stock => <tr key={stock.thscode}><td><button type="button" className="stock-name-button" onClick={() => setSelectedCode(stock.thscode)}><strong>{stock.name}</strong><small>{stock.thscode}</small></button></td>
                {lastParams?.industry && <td>{stock.industries?.map(item => item.name).join('、') || '未知'}</td>}{executedMetrics.map(metric => { const key = metric.key; const value = getCheck(stock, key)?.actual; return <td key={key} className="numeric-cell"><span className={metricTone(key, value)}>{formatMetric(value)}{value != null ? metric.unit : ''}</span></td> })}
                <td><span className={`stock-status status-${stock.status.toLowerCase()}`}><span className="status-point"/>{stockStatusLabels[stock.status]}</span></td>
                <td><button type="button" className="row-detail" aria-label={`查看${stock.name}筛选详情`} onClick={() => setSelectedCode(stock.thscode)}><Icon name="arrow" size={17}/></button></td></tr>)}
            </tbody></table>
              {rows.length === 0 && <div className="no-rows">没有符合当前列表过滤条件的股票。可以切换状态或清除搜索。</div>}
            </div>
            <div className="results-footnote"><Icon name="info" size={16}/><span>本次评估快照中的 {screen.results.length} 只股票，不代表全 A 股。快照采集时间：{formatDate(screen.snapshot_metadata?.collected_at)}。完整日K线截至：{screen.snapshot_metadata?.last_completed_trade_date || '见个股详情'}；不是实时行情。</span></div>
          </div>

          {comparison && <div className="comparison-surface"><div className="comparison-header"><div className="comparison-icon"><Icon name="layers" size={21}/></div><div><h3>策略调整后，有哪些变化？</h3><p>将上次与本次条件都应用于本次快照，仅比较条件差异。</p></div></div><div className="comparison-grid"><div><span>新增符合条件</span><strong>+{comparison.changes.newly_selected.length}</strong><p>{comparison.changes.newly_selected.map(x => x.name).join('、') || '无变化'}</p></div><div><span>不再符合条件</span><strong>−{comparison.changes.no_longer_selected.length}</strong><p>{comparison.changes.no_longer_selected.map(x => x.name).join('、') || '无变化'}</p></div><div><span>持续符合条件</span><strong>{comparison.changes.still_selected.length}</strong><p>{comparison.changes.still_selected.map(x => x.name).join('、') || '无'}</p></div></div></div>}
        </section>}

        <div className="data-provenance"><div className="provenance-cell"><Icon name="layers" size={18}/><div><strong>分析范围</strong><span>{dataStatus ? `${dataStatus.metadata.universe || '指定股票池'} · 当前 ${dataStatus.stock_count} 只样本` : '等待数据连接'}</span></div></div><div className="provenance-cell"><Icon name="shield" size={18}/><div><strong>计算与解释边界</strong><span>AI 解析意图，规则引擎决定入选与排除</span></div></div></div>

      </main>

      <SiteFooter/>
      {settingsOpen && <AccountSettings onClose={() => setSettingsOpen(false)}/>}

      {drawerOpen && <StrategyDrawer account={Boolean(accountId)} items={library.items} message={library.error || libraryMessage} onClose={() => setDrawerOpen(false)} onLoad={restoreStrategy}
        onImport={accountId ? async () => {
          if (!window.confirm('将此浏览器的旧策略复制到当前账号？原本地数据会保留。')) return
          try {
            const imported = decodeStrategies(localStorage.getItem(storageKey)).map(item => ({ ...item, id: crypto.randomUUID() }))
            if (library.items.length + imported.length > 30) throw new Error('导入后超过30条，请先整理策略。')
            if (await persistStrategies([...library.items, ...imported])) setLibraryMessage(`已导入 ${imported.length} 条策略，原本地数据保留。`)
          } catch (err) { setLibraryMessage((err as Error).message) }
        } : undefined}
        onRename={item => { setLibraryMessage(''); setSaveDialog({ snapshot: item.snapshot, query: item.query, provider: item.provider, target: item, rename: true }) }}
        onCopy={item => { setLibraryMessage(''); setSaveDialog({ snapshot: item.snapshot, query: item.query, provider: item.provider }) }}
        onDelete={async item => { if (window.confirm(`删除「${item.name}」？此操作不可撤销。`) && await persistStrategies(library.items.filter(old => old.id !== item.id))) { if (strategyId === item.id) setStrategyId(''); setLibraryMessage('策略已删除。') } }} />}
      {saveDialog && <SaveStrategyDialog account={Boolean(accountId)} initialName={saveDialog.target?.name || ''} title={saveDialog.rename ? '重命名策略' : saveDialog.target ? '保存更改' : '保存新策略'} error={libraryMessage} onClose={() => setSaveDialog(null)} onSave={confirmSave} />}
      {selectedStock && <div className="drawer-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setSelectedCode(null) }}>
        <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
          <div className="drawer-header"><div><span className="drawer-overline">STOCK SCREENING TRACE</span><h2 id="drawer-title">{selectedStock.name}</h2><p>{selectedStock.thscode}</p></div><button className="drawer-close" aria-label="关闭股票详情" type="button" onClick={() => setSelectedCode(null)}><Icon name="close" size={21}/></button></div>
          <div className="drawer-scroll"><div className={`drawer-outcome outcome-${selectedStock.status.toLowerCase()}`}><span className="outcome-dot"/><div><span>当前筛选结果</span><strong>{stockStatusLabels[selectedStock.status]}</strong></div></div>
            <h3 className="drawer-section-title">逐项条件核验</h3><p className="drawer-section-desc">每条判断由筛选引擎根据数据字段计算，非 AI 猜测。</p>
            <div className="evidence-list">{lastParams?.industry && selectedStock.checks.filter(check => check.field === 'industries').map(check => <div className="evidence-entry" key={check.field}><div className="evidence-entry-top"><strong>同花顺行业</strong><span className={`evidence-state check-${check.status.toLowerCase()}`}>{checkStatusLabels[check.status]}</span></div><p>{check.reason}</p><small>行业查询时间：{formatDate(selectedStock.industry_fetched_at)}。查询时间不代表分类关系的生效时间。</small></div>)}{executedMetrics.map(metric => {
              const check = getCheck(selectedStock, metric.key)
              return <div className="evidence-entry" key={metric.key}><div className="evidence-entry-top"><div><strong>{metric.title}</strong><span>{metric.subtitle}</span></div><span className={`evidence-state check-${(check?.status || 'UNKNOWN').toLowerCase()}`}>{checkStatusLabels[check?.status || 'UNKNOWN']}</span></div><div className="evidence-value"><span>{formatMetric(check?.actual)}{check?.actual != null ? metric.unit : ''}</span><small>实际指标值</small></div><p>{check?.reason || '缺少对应指标，无法完成判断。'}</p></div>
            })}</div>
            <div className="drawer-divider"/><DataProvenance entries={selectedStock.data_provenance || []} sources={selectedStock.sources || {}} collectedAt={screen?.snapshot_metadata?.collected_at} lastTradeDate={screen?.snapshot_metadata?.last_completed_trade_date} snapshotId={screen?.snapshot_metadata?.snapshot_id} formatDate={formatDate}/>
            {(selectedStock.data_errors ?? []).length > 0 && <div className="drawer-error"><strong>数据异常</strong>{selectedStock.data_errors.map((item, i) => <p key={i}>{item}</p>)}</div>}
            <div className="drawer-disclaimer"><Icon name="info" size={17}/>只核验了本次启用的指标；未启用的指标不影响结论。结果不代表股票值得买入。</div>
          </div>
        </aside>
      </div>}
    </div>
  )
}

export default App
