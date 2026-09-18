import React, { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { gsap } from 'gsap'

// ─── Types ───

interface Account {
  uid: string; name: string; user_type: string; security_oauth_token: string
  refresh_token: string; machine_id: string; enabled: boolean; last_status: string
  last_error: string | null; quota: number; is_quota_exceeded: boolean
  plan: string | null; user_tag: string | null; next_reset_at: number | null
}
interface AccountsConfig { accounts: Account[]; active_uid: string | null }
interface UIStatus { ready: boolean; mode: string; username: string | null; uid: string | null; user_type: string | null; error: string | null; accounts_count: number }
interface APIConfig { auth_required: boolean; allowed_keys: string[] }
interface Message { role: 'user' | 'assistant'; content: string }
type ChatApiMessage = { role: 'system' | 'user' | 'assistant'; content: string }
type TabId = 'dashboard' | 'accounts' | 'playground' | 'api-keys' | 'logs' | 'register'
type AppTabId = TabId
type Lang = 'en' | 'zh'
type ToastType = 'SUCCESS' | 'ERROR' | 'INFO'
interface ToastItem { id: number; type: ToastType; title: string; message: string }

interface RegTask {
  stage: string
  logs: string[]
  result: { email: string; password: string; name: string; device: { token: string; refresh_token: string; user_id: string; expires_at: string } } | null
  error: string | null
  started_at: number
}
interface RegStatus {
  running: boolean
  stop_requested: boolean
  parents: number
  started_at: number | null
  verification: string | null
  stats: { success: number; failed: number; total: number }
  active: Record<string, RegTask>
  recent: Record<string, RegTask>
}

const NAV_ITEMS: { id: AppTabId; icon: string; label: string }[] = [
  { id: 'dashboard', icon: 'dashboard', label: 'Dashboard' },
  { id: 'accounts', icon: 'account_balance_wallet', label: 'Account Pool' },
  { id: 'playground', icon: 'smart_toy', label: 'AI Playground' },
  { id: 'api-keys', icon: 'vpn_key', label: 'API Key Management' },
  { id: 'register', icon: 'person_add', label: 'Auto Registrar' },
  { id: 'logs', icon: 'list_alt', label: 'Logs' },
]

const UI_TEXT = {
  en: {
    nav: {
      dashboard: 'Dashboard', accounts: 'Account Pool', playground: 'AI Playground', apiKeys: 'API Key Management', logs: 'Logs', register: 'Auto Registrar',
    },
    breadcrumb: {
      dashboard: 'Control Panel / Overview', accounts: 'Console / Management', playground: 'Playground / Experiment', apiKeys: 'Administration / Security', logs: 'System / Observability', docs: 'Developer Platform / Wiki', register: 'Automation / Registrar',
    },
    title: {
      dashboard: 'System Overview', accounts: 'Account Pool', playground: 'AI Playground', apiKeys: 'API Management', logs: 'Service Logs', docs: 'Documentation', register: 'Auto Registrar',
    },
    common: { docs: 'Docs', support: 'Support', healthy: 'Healthy', offline: 'Offline', checking: 'Checking...', signOut: 'Sign Out', refresh: 'Refresh', add: 'Add', delete: 'Delete', copy: 'Copy' },
    dashboard: {
      serviceStatus: 'Service Status', allGatewaysActive: 'All gateways active', noActiveSession: 'No active session', accountPool: 'Account Pool', activeSessions: 'Active Qoder accounts', apiAuth: 'API Auth', openAccess: 'Open access', activeUser: 'Active User', systemBriefing: 'System Briefing', readyBrief: 'Gateway is running. {count} account(s) are available for routing.', notReadyBrief: 'No active session is available. Import an account or add a PAT first.', recentNotifications: 'Recent Notifications', authImportError: 'Auth Import Error', sessionActive: 'Session Active', credentialConfig: 'Credential Configuration', credentialDesc: 'Add a Qoder PAT or import the current local Qoder auth session.', patPlaceholder: 'Enter Qoder PAT...', addPat: 'Add PAT', saving: 'Saving...', autoImport: 'Auto Import',
    },
    accounts: { desc: 'Manage Qoder accounts used by the gateway for request routing and failover.', refreshStatus: 'Refresh Status', importAccounts: 'Import Accounts', search: 'Search accounts...', empty: 'No accounts imported. Click Import Accounts or add a PAT from Dashboard.', showing: 'Showing {count} account(s)' },
    playground: { modelConfig: 'Model Configuration', streamResponse: 'Stream Response', systemPrompt: 'System Prompt', systemPromptPlaceholder: "Define the AI's persona...", ask: 'Ask anything...', send: 'Send', waiting: 'Waiting for response...' },
    api: { generate: 'Generate New Key', desc: 'Manage authentication keys and gateway access permissions for client requests.', gatewayAuth: 'Gateway Authentication', gatewayAuthDesc: 'Toggle API key validation for incoming /v1 requests.', systemStatus: 'System Status', activeKeys: 'Active Keys', configured: 'configured', activeAccessKeys: 'Active Access Keys', keyPlaceholder: 'Enter or paste a key...', noKeys: 'No API keys configured. Generate one above.', bestPractices: 'Security Best Practices', bestPracticesDesc: 'Do not expose API keys in client-side code. Rotate keys when they appear in logs, screenshots, or shared scripts.' },
    logs: { account: 'Account', status: 'Status', range: 'Range', allAccounts: 'All Accounts', allStatuses: 'All Statuses', allTime: 'All time', lastHour: 'Last hour', noLogs: 'No logs available', noMatch: 'No logs match current filters', timestamp: 'Timestamp', level: 'Level', message: 'Message' },
    register: {
      desc: 'Register multiple Qoder accounts in parallel, pull device credentials and auto-save them into the pool. Browsers stay hidden in the background; each task pops to top once for human verification, then hides again — finish one, next takes its turn.',
      start: 'Start Registration',
      starting: 'Starting...',
      running: 'Tasks running',
      idle: 'Idle',
      stageLabel: 'Stage',
      statusLabel: 'Status',
      logs: 'Live Logs',
      result: 'Registration Result (auto-imported)',
      noResult: 'No task has run yet',
      countLabel: 'Parent Threads',
      staggerHint: 'Each parent loops forever: 3 child tasks per batch, next batch starts automatically until you click stop',
      stop: 'Stop Registration',
      stopping: 'Stopping (after current batch)...',
      stopHint: 'Stops after the current batch finishes and reports this run\'s stats',
      verifyHint: 'Complete the human verification in the topmost browser window (slide the slider); next task takes over automatically',
      waiting: 'Waiting for human verification',
      task: 'Task',
      statsLabel: 'This Run Stats',
      success: 'Success',
      failed: 'Failed',
      total: 'Total',
      activeTasks: 'Running',
      recentTasks: 'Recent Done',
      stage: {
        idle: 'Idle', registering: 'Registering', waiting_slider: 'Waiting for human verification (topmost)', waiting_otp: 'Waiting for email code', device_auth: 'Device authorization', saving: 'Saving to DB', success: 'Success', failed: 'Failed',
      },
    },
  },
  zh: {
    nav: {
      dashboard: '控制台', accounts: '账号池', playground: '调试对话', apiKeys: 'API Key 管理', logs: '服务日志', register: '自动注册机',
    },
    breadcrumb: {
      dashboard: '控制台 / 概览', accounts: '控制台 / 账号管理', playground: '调试 / 对话测试', apiKeys: '管理 / 安全', logs: '系统 / 日志', docs: '开发者平台 / 文档', register: '自动化 / 注册机',
    },
    title: {
      dashboard: '系统概览', accounts: '账号池', playground: '调试对话', apiKeys: 'API 管理', logs: '服务日志', docs: '文档', register: '自动注册机',
    },
    common: { docs: '文档', support: '支持', healthy: '正常', offline: '未就绪', checking: '检查中...', signOut: '退出', refresh: '刷新', add: '添加', delete: '删除', copy: '复制' },
    dashboard: {
      serviceStatus: '服务状态', allGatewaysActive: '网关可用', noActiveSession: '没有可用账号', accountPool: '账号池', activeSessions: '可参与路由的 Qoder 账号', apiAuth: 'API 鉴权', openAccess: '未开启鉴权', activeUser: '当前账号', systemBriefing: '运行状态', readyBrief: '网关正在运行，当前有 {count} 个账号可用于请求路由。', notReadyBrief: '当前没有可用会话，请先导入账号或添加 PAT。', recentNotifications: '最近状态', authImportError: '本地登录导入失败', sessionActive: '账号已连接', credentialConfig: '凭据配置', credentialDesc: '添加 Qoder PAT，或导入本机已有的 Qoder 登录会话。', patPlaceholder: '输入 Qoder PAT...', addPat: '添加 PAT', saving: '保存中...', autoImport: '自动导入',
    },
    accounts: { desc: '管理网关用于请求路由和失败切换的 Qoder 账号。', refreshStatus: '刷新状态', importAccounts: '导入账号', search: '搜索账号...', empty: '还没有导入账号。点击导入账号，或在控制台添加 PAT。', showing: '共 {count} 个账号' },
    playground: { modelConfig: '模型配置', streamResponse: '流式响应', systemPrompt: '系统提示词', systemPromptPlaceholder: '定义模型的角色或行为...', ask: '输入要发送的内容...', send: '发送', waiting: '正在等待响应...' },
    api: { generate: '生成新 Key', desc: '管理客户端请求网关时使用的 API Key 和访问权限。', gatewayAuth: '网关 API 鉴权', gatewayAuthDesc: '控制 /v1 请求是否必须携带 API Key。', systemStatus: '系统状态', activeKeys: '可用 Key', configured: '已配置', activeAccessKeys: '已启用的 API Key', keyPlaceholder: '输入或粘贴 API Key...', noKeys: '还没有配置 API Key。请先生成并添加。', bestPractices: '安全建议', bestPracticesDesc: '不要把 API Key 写在前端代码里。如果 Key 出现在日志、截图或共享脚本中，请及时删除并重新生成。' },
    logs: { account: '账号', status: '级别', range: '时间范围', allAccounts: '全部账号', allStatuses: '全部级别', allTime: '全部时间', lastHour: '最近 1 小时', noLogs: '暂无日志', noMatch: '没有匹配当前筛选条件的日志', timestamp: '时间', level: '级别', message: '内容' },
    register: {
      desc: '并行注册多个 Qoder 账号并拉取 Device 凭据，成功后自动入库。浏览器平时隐藏后台，人机验证时置顶显示，划完一个自动轮到下一个。',
      start: '开始注册',
      starting: '启动中...',
      running: '任务运行中',
      idle: '空闲',
      stageLabel: '阶段',
      statusLabel: '状态',
      logs: '实时日志',
      result: '注册结果（已自动入库）',
      noResult: '尚未运行注册任务',
      countLabel: '母线程数',
      staggerHint: '每个母线程无限循环：每批 3 个子任务并发，注册完一批自动开下一批，直到点击停止',
      stop: '停止注册',
      stopping: '停止中（当前批完成后停）...',
      stopHint: '当前批次完成后停止，统计本次注册数',
      verifyHint: '请在置顶的浏览器窗口中完成人机验证（滑动滑块），划完自动轮到下一个',
      waiting: '等待人工验证',
      task: '任务',
      statsLabel: '本次注册统计',
      success: '成功',
      failed: '失败',
      total: '总计',
      activeTasks: '运行中任务',
      recentTasks: '最近完成',
      stage: {
        idle: '空闲', registering: '正在注册', waiting_slider: '等待人机验证（已置顶）', waiting_otp: '等待邮箱验证码', device_auth: 'Device 授权中', saving: '入库中', success: '注册成功', failed: '失败',
      },
    },
  },
} as const

const TOAST_STYLES: Record<ToastType, { bg: string; border: string; icon: string; iconFill: string }> = {
  SUCCESS: { bg: 'bg-white', border: 'border-l-[3px] border-l-toast-success', icon: 'check_circle', iconFill: 'text-toast-success' },
  ERROR: { bg: 'bg-white', border: 'border-l-[3px] border-l-toast-error', icon: 'error', iconFill: 'text-toast-error' },
  INFO: { bg: 'bg-white', border: 'border-l-[3px] border-l-toast-info', icon: 'info', iconFill: 'text-toast-info' },
}

// 剪贴板帮助函数：优先 async Clipboard API，非安全上下文（如通过 LAN IP + http 访问时 navigator.clipboard 缺失）回退 execCommand
async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (window.isSecureContext && navigator.clipboard) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* 回退到 execCommand */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  } catch {
    return false
  }
}

// 限额 percentage 透传上游 JSON，可能是 0-1 或 0-100，显示前归一化到 0-1
function normalizeQuotaPct(p: unknown): number {
  const v = typeof p === 'number' && Number.isFinite(p) ? p : 0
  const ratio = v > 1 ? v / 100 : v
  return Math.min(1, Math.max(0, ratio))
}

// API Key 掩码显示：前 8 位（如 qg_live_）+ 掩码 + 末 4 位
function maskApiKey(key: string): string {
  if (key.length <= 12) return '••••••'
  return `${key.slice(0, 8)}••••••${key.slice(-4)}`
}

// ─── Custom UI Components ───

function CustomCheckbox({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 text-sm font-bold text-ink cursor-pointer group select-none"
    >
      <span className={`w-5 h-5 rounded-md border-2 flex items-center justify-center transition-all duration-200 ${
        checked ? 'bg-ink border-ink' : 'bg-white border-hairline-strong group-hover:border-ink/40'
      }`}>
        {checked && <span className="material-symbols-outlined text-white" style={{ fontSize: '14px', fontVariationSettings: "'FILL' 1" }}>check</span>}
      </span>
      {label}
    </button>
  )
}

function CustomSelect({ value, onChange, options, placeholder }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; placeholder?: string }) {
  const [open, setOpen] = useState(false)
  const [highlightIndex, setHighlightIndex] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const selected = options.find(o => o.value === value)

  useEffect(() => {
    const handler = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const openListbox = () => {
    const current = options.findIndex(o => o.value === value)
    setHighlightIndex(current >= 0 ? current : 0)
    setOpen(true)
  }

  const commitHighlight = () => {
    const opt = options[highlightIndex]
    if (opt) { onChange(opt.value); setOpen(false) }
  }

  // 键盘支持：上下移动高亮、Enter 选中、Escape 关闭（触发器上监听；选项上的 Escape 由外层兜底）
  const handleTriggerKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); openListbox() }
      return
    }
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setHighlightIndex(i => Math.min(options.length - 1, i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHighlightIndex(i => Math.max(0, i - 1)) }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); commitHighlight() }
  }

  return (
    <div ref={ref} className={`relative ${open ? 'z-[5000]' : 'z-10'}`} onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}>
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : openListbox())}
        onKeyDown={handleTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="w-full h-11 bg-white border border-hairline-strong rounded-lg px-4 text-sm text-ink font-medium flex items-center justify-between focus:ring-2 focus:ring-ink outline-none cursor-pointer hover:border-ink/30 transition-colors"
      >
        <span className={selected ? 'text-ink' : 'text-body/50'}>{selected?.label || placeholder || 'Select...'}</span>
        <span className={`material-symbols-outlined text-body text-[18px] transition-transform duration-200 ${open ? 'rotate-180' : ''}`}>expand_more</span>
      </button>
      {open && (
        <div role="listbox" className="custom-select-dropdown absolute top-full left-0 right-0 mt-1 bg-white border border-hairline rounded-lg shadow-xl z-[6000] overflow-hidden">
          {options.map((opt, i) => (
            <button
              key={opt.value}
              type="button"
              role="option"
              aria-selected={opt.value === value}
              onMouseEnter={() => setHighlightIndex(i)}
              onClick={() => { onChange(opt.value); setOpen(false) }}
              className={`w-full px-4 py-2.5 text-sm text-left font-medium transition-colors ${
                i === highlightIndex || opt.value === value ? 'bg-canvas-soft text-ink' : 'text-body hover:bg-canvas-soft hover:text-ink'
              } ${opt.value === value ? 'font-bold' : ''}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function CustomInput({ value, onChange, placeholder, type = 'text', className = '', mono = false, id }: {
  value: string; onChange: (v: string) => void; placeholder?: string; type?: string; className?: string; mono?: boolean; id?: string
}) {
  return (
    <input
      id={id}
      type={type}
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full bg-white border border-hairline-strong text-ink text-sm px-4 py-3 rounded-lg outline-none focus:border-ink focus:ring-2 focus:ring-ink/10 transition-all placeholder:text-body/40 ${mono ? 'font-mono' : 'font-medium'} ${className}`}
    />
  )
}

function CustomTextarea({ value, onChange, placeholder, className = '', rows }: {
  value: string; onChange: (v: string) => void; placeholder?: string; className?: string; rows?: number
}) {
  return (
    <textarea
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className={`custom-textarea w-full bg-white border border-hairline-strong text-ink text-sm px-4 py-3 rounded-xl outline-none focus:border-ink focus:ring-2 focus:ring-ink/10 transition-all placeholder:text-body/40 resize-none ${className}`}
    />
  )
}

// ─── Toast Container ───

function ToastContainer({ toasts, dismiss }: { toasts: ToastItem[]; dismiss: (id: number) => void }) {
  const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const timersRef = useRef<Map<number, number>>(new Map())

  const clearAutoDismiss = (id: number) => {
    const timer = timersRef.current.get(id)
    if (timer !== undefined) { window.clearTimeout(timer); timersRef.current.delete(id) }
  }

  const handleDismiss = (id: number) => {
    clearAutoDismiss(id)
    const el = itemRefs.current.get(id)
    if (el) {
      gsap.to(el, {
        opacity: 0, x: 60, scale: 0.92, duration: 0.25, ease: 'power2.in',
        onComplete: () => dismiss(id)
      })
    } else {
      dismiss(id)
    }
  }

  // 自动消失：每个 toast 只挂一个定时器，先动画再 dismiss，不在 setState updater 内做 DOM 副作用
  useEffect(() => {
    toasts.forEach(t => {
      if (timersRef.current.has(t.id)) return
      const timer = window.setTimeout(() => {
        timersRef.current.delete(t.id)
        handleDismiss(t.id)
      }, 4500)
      timersRef.current.set(t.id, timer)
    })
  }, [toasts])

  // 卸载时清理所有未触发的自动消失定时器
  useEffect(() => () => {
    timersRef.current.forEach(timer => window.clearTimeout(timer))
    timersRef.current.clear()
  }, [])

  // 入场动画（每个 toast 只播一次）
  useEffect(() => {
    toasts.forEach(t => {
      const el = itemRefs.current.get(t.id)
      if (!el || el.dataset.animated === '1') return
      el.dataset.animated = '1'
      gsap.fromTo(el,
        { opacity: 0, x: 60, scale: 0.92 },
        { opacity: 1, x: 0, scale: 1, duration: 0.4, ease: 'back.out(1.2)' }
      )
    })
  }, [toasts])

  return (
    <div className="fixed bottom-6 right-6 z-[100] flex flex-col-reverse gap-3 pointer-events-none" style={{ maxWidth: '380px' }}>
      {toasts.map(t => {
        const s = TOAST_STYLES[t.type]
        return (
          <div
            key={t.id}
            data-toast-id={t.id}
            ref={el => { if (el) itemRefs.current.set(t.id, el) }}
            className={`pointer-events-auto ${s.bg} ${s.border} border border-hairline rounded-xl shadow-xl p-4 flex items-start gap-3 min-w-[320px]`}
          >
            <span className={`material-symbols-outlined ${s.iconFill} mt-0.5 shrink-0`} style={{ fontVariationSettings: "'FILL' 1", fontSize: '20px' }}>{s.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-bold text-ink uppercase tracking-wider">{t.title}</div>
              <div className="text-[12px] text-body mt-0.5 leading-relaxed break-words">{t.message}</div>
            </div>
            <button onClick={() => handleDismiss(t.id)} className="text-body/40 hover:text-ink transition-colors shrink-0 mt-0.5">
              <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>close</span>
            </button>
          </div>
        )
      })}
    </div>
  )
}

// ─── Main App ───

export default function App() {
  const [lang, setLang] = useState<Lang>(() => {
    const stored = localStorage.getItem('qodergate_lang')
    if (stored === 'en' || stored === 'zh') return stored
    return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'
  })
  const [token, setToken] = useState<string | null>(localStorage.getItem('gateway_token'))
  const [authError, setAuthError] = useState<string | null>(null)
  const [inputToken, setInputToken] = useState('')
  const [verifying, setVerifying] = useState(false)
  const [loginSuccess, setLoginSuccess] = useState(false)

  const [activeTab, setActiveTab] = useState<AppTabId>('dashboard')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [status, setStatus] = useState<UIStatus>({ ready: false, mode: 'none', username: null, uid: null, user_type: null, error: null, accounts_count: 0 })
  // 首次成功拉取 /ui/status 前为 false，用于首帧显示中性的"检查中"而非红色"未就绪"
  const [statusLoaded, setStatusLoaded] = useState(false)
  const [accountsConfig, setAccountsConfig] = useState<AccountsConfig>({ accounts: [], active_uid: null })
  const [apiConfig, setApiConfig] = useState<APIConfig>({ auth_required: false, allowed_keys: [] })
  const [logs, setLogs] = useState<string[]>([])

  const [chatMessages, setChatMessages] = useState<Message[]>([
    { role: 'assistant', content: 'Hello! I am the QoderGate AI assistant. Ask me anything — I support Markdown and LaTeX math.' }
  ])
  const [chatInput, setChatInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [model, setModel] = useState('lite')
  const [stream, setStream] = useState(true)
  const [generating, setGenerating] = useState(false)

  const [newKey, setNewKey] = useState('')
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  // API Key 表格默认掩码显示，按 key 记录"显示全文"状态
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set())
  const [patToken, setPatToken] = useState('')
  const [submittingPat, setSubmittingPat] = useState(false)
  const [submittingBatch, setSubmittingBatch] = useState(false)
  const [importingAuth, setImportingAuth] = useState(false)
  const [loadingQuota, setLoadingQuota] = useState(false)
  const [searchAccounts, setSearchAccounts] = useState('')
  // Thinking 折叠按消息序号独立记录，避免展开一条历史消息时所有消息一起展开
  const [expandedThinking, setExpandedThinking] = useState<Set<number>>(new Set())

  const [showBatchImport, setShowBatchImport] = useState(false)
  // 设备授权导入：idle | waiting（等待浏览器授权） | success
  const [deviceAuth, setDeviceAuth] = useState<{ state: 'idle' | 'waiting' | 'success'; nonce: string | null; authUrl: string | null }>({ state: 'idle', nonce: null, authUrl: null })
  const deviceAuthTimer = useRef<number | null>(null)
  const [batchJson, setBatchJson] = useState('')
  const [refreshingTokens, setRefreshingTokens] = useState(false)
  const [quotaList, setQuotaList] = useState<{ uid: string; name: string; quota: { userQuota: { total: number; used: number; remaining: number; percentage: number } } }[] | null>(null)

  const [logFilterAccount, setLogFilterAccount] = useState('all')
  const [logFilterStatus, setLogFilterStatus] = useState('all')
  // 日志只记录时刻没有日期，无法支撑 24h/7d 过滤，仅保留全部/最近 1 小时
  const [logFilterRange, setLogFilterRange] = useState('all')

  const [regStatus, setRegStatus] = useState<RegStatus | null>(null)
  const [regStarting, setRegStarting] = useState(false)
  const [regStopping, setRegStopping] = useState(false)
  const [regCount, setRegCount] = useState(2)

  const switchLang = (next: Lang) => {
    setLang(next)
    localStorage.setItem('qodergate_lang', next)
  }
  const t = UI_TEXT[lang]
  const msg = {
    imported: (name: string) => lang === 'zh' ? `已导入账号：${name}` : `Imported account: ${name}`,
    importFailed: lang === 'zh' ? '导入失败' : 'Import Failed',
    patAdded: (name: string) => lang === 'zh' ? `账号“${name}”已加入账号池` : `Account "${name}" added to pool`,
    patFailed: lang === 'zh' ? 'PAT 添加失败' : 'PAT Failed',
    activated: (uid: string) => lang === 'zh' ? `已切换到账号 ${uid.substring(0, 12)}...` : `Switched active account to ${uid.substring(0, 12)}...`,
    activationFailed: lang === 'zh' ? '激活失败' : 'Activation Failed',
    updated: (enabled: boolean) => lang === 'zh' ? `账号已${enabled ? '启用' : '禁用'}` : `Account ${enabled ? 'enabled' : 'disabled'}`,
    toggleFailed: lang === 'zh' ? '更新失败' : 'Toggle Failed',
    deleted: (uid: string) => lang === 'zh' ? `已删除账号 ${uid.substring(0, 12)}...` : `Removed account ${uid.substring(0, 12)}... from pool`,
    deleteFailed: lang === 'zh' ? '删除失败' : 'Delete Failed',
    configFailed: lang === 'zh' ? '配置保存失败' : 'Config Save Failed',
    authToggled: (enabled: boolean) => lang === 'zh' ? `API Key 鉴权已${enabled ? '开启' : '关闭'}` : `API key validation ${enabled ? 'enabled' : 'disabled'}`,
    keyGenerated: lang === 'zh' ? '已生成新的 API Key，点击添加后生效。' : 'A new API key has been generated. Click Add to activate it.',
    duplicateKey: lang === 'zh' ? '这个 API Key 已存在' : 'This API key already exists in the list',
    keyAdded: lang === 'zh' ? 'API Key 已添加' : 'New API key has been added to the gateway',
    keyRemoved: lang === 'zh' ? 'API Key 已删除' : 'API key has been removed from the gateway',
    copied: lang === 'zh' ? '已复制到剪贴板' : 'Copied to clipboard',
    refreshed: lang === 'zh' ? '状态已刷新' : 'Status Refreshed',
    logsRefreshed: lang === 'zh' ? '日志已刷新' : 'Logs Refreshed',
    aiFailed: lang === 'zh' ? 'AI 请求失败' : 'AI Request Failed',
    responseDone: lang === 'zh' ? '响应已完成' : 'Response Complete',
    connectionError: lang === 'zh' ? '连接失败' : 'Connection Error',
  }
  const navLabels: Record<AppTabId, string> = {
    dashboard: t.nav.dashboard,
    accounts: t.nav.accounts,
    playground: t.nav.playground,
    'api-keys': t.nav.apiKeys,
    logs: t.nav.logs,
    register: t.nav.register,
  }
  const pageMeta: Record<AppTabId, { bc: string; title: string }> = {
    dashboard: { bc: t.breadcrumb.dashboard, title: t.title.dashboard },
    accounts: { bc: t.breadcrumb.accounts, title: t.title.accounts },
    playground: { bc: t.breadcrumb.playground, title: t.title.playground },
    'api-keys': { bc: t.breadcrumb.apiKeys, title: t.title.apiKeys },
    logs: { bc: t.breadcrumb.logs, title: t.title.logs },
    register: { bc: t.breadcrumb.register, title: t.title.register },
  }

  // 语言切换时同步 <html lang>，供无障碍工具与翻译扩展识别
  useEffect(() => { document.documentElement.lang = lang === 'zh' ? 'zh' : 'en' }, [lang])

  const loginCardRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const contentBodyRef = useRef<HTMLDivElement>(null)
  const logEndRef = useRef<HTMLDivElement>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const statCardsRef = useRef<HTMLDivElement>(null)
  const notifListRef = useRef<HTMLUListElement>(null)
  const terminalRef = useRef<HTMLDivElement>(null)
  const orbRefs = useRef<(HTMLDivElement | null)[]>([])

  // Toast state
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const toastIdRef = useRef(0)
  // 只负责入队；自动消失的 DOM 动画与移除由 ToastContainer 的定时器回调处理，updater 保持纯函数
  const pushToast = useCallback((type: ToastType, title: string, message: string) => {
    const id = ++toastIdRef.current
    setToasts(prev => [...prev, { id, type, title, message }])
  }, [])
  const dismissToast = useCallback((id: number) => setToasts(prev => prev.filter(t => t.id !== id)), [])

  const authedFetch = useCallback(async (url: string, options: RequestInit = {}) => {
    const headers = { ...(options.headers || {}), 'X-Gateway-Token': token || '' }
    const resp = await fetch(url, { ...options, headers })
    if (resp.status === 401) { localStorage.removeItem('gateway_token'); setToken(null); throw new Error('Unauthorized') }
    return resp
  }, [token])

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/status')
      if (!resp.ok) return
      const data = await resp.json()
      // 形状守卫：异常响应（如 {"detail":...}）不进 state，避免渲染崩溃
      if (data && typeof data === 'object' && typeof data.ready === 'boolean') {
        setStatus(data)
        setStatusLoaded(true)
      }
    } catch { /* */ }
  }, [authedFetch])
  const fetchAccounts = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/accounts')
      if (!resp.ok) return
      const data = await resp.json()
      // 形状守卫：异常响应（如 {"detail":...}）不进 state，避免渲染崩溃
      if (data && Array.isArray(data.accounts)) setAccountsConfig({ accounts: data.accounts, active_uid: data.active_uid ?? null })
    } catch { /* */ }
  }, [authedFetch])
  const fetchApiConfig = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/config')
      if (!resp.ok) return
      const data = await resp.json()
      if (data && typeof data === 'object') setApiConfig({ auth_required: !!data.auth_required, allowed_keys: Array.isArray(data.allowed_keys) ? data.allowed_keys : [] })
    } catch { /* */ }
  }, [authedFetch])
  const stopDeviceAuthPolling = useCallback(() => {
    if (deviceAuthTimer.current !== null) { window.clearInterval(deviceAuthTimer.current); deviceAuthTimer.current = null }
  }, [])

  // 组件卸载时停止设备授权轮询，避免登出后定时器残留、用失效 token 反复空转
  useEffect(() => () => stopDeviceAuthPolling(), [stopDeviceAuthPolling])

  // 轮询设备授权结果；ok → 入库成功刷新列表，expired → 提示重试
  const pollDeviceAuth = useCallback((nonce: string) => {
    stopDeviceAuthPolling()
    deviceAuthTimer.current = window.setInterval(async () => {
      try {
        const resp = await authedFetch('/ui/device-auth/poll', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nonce }) })
        if (!resp.ok) {
          // 后端异常（如保存凭据失败返回 400 {detail}）：停止轮询并提示，避免 data.status undefined 落入 pending 分支永久空转
          stopDeviceAuthPolling()
          setDeviceAuth({ state: 'idle', nonce: null, authUrl: null })
          let detail = ''
          try { const errData = await resp.json(); detail = typeof errData?.detail === 'string' ? errData.detail : '' } catch { /* */ }
          pushToast('ERROR', lang === 'zh' ? '授权轮询失败' : 'Authorization Failed', detail || `HTTP ${resp.status}`)
          return
        }
        const data = await resp.json()
        if (data.status === 'ok') {
          stopDeviceAuthPolling()
          setDeviceAuth({ state: 'success', nonce: null, authUrl: null })
          pushToast('SUCCESS', lang === 'zh' ? '账号导入成功' : 'Account Imported', `${data.account?.name || ''} ${data.account?.uid?.slice(0, 12) || ''}`)
          fetchAccounts(); fetchStatus()
        } else if (data.status === 'expired') {
          stopDeviceAuthPolling()
          setDeviceAuth({ state: 'idle', nonce: null, authUrl: null })
          pushToast('ERROR', lang === 'zh' ? '授权已超时' : 'Authorization Expired', lang === 'zh' ? '请重新点击「设备授权导入」' : 'Click "Device Auth Import" to retry')
        }
        // pending → 继续轮询
      } catch { /* 网络抖动继续轮询 */ }
    }, 2000)
  }, [authedFetch, stopDeviceAuthPolling, pushToast, lang, fetchAccounts, fetchStatus])

  // 发起设备授权：拿授权 URL → 打开浏览器 → 开始轮询
  const startDeviceAuth = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/device-auth/start', { method: 'POST' })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setDeviceAuth({ state: 'waiting', nonce: data.nonce, authUrl: data.auth_url })
      window.open(data.auth_url, '_blank', 'noopener')
      pollDeviceAuth(data.nonce)
    } catch (err: any) {
      pushToast('ERROR', lang === 'zh' ? '设备授权启动失败' : 'Device auth failed to start', err.message)
    }
  }, [authedFetch, pollDeviceAuth, pushToast, lang])

  const doBatchImport = useCallback(async () => {    let records: unknown
    try { records = JSON.parse(batchJson) } catch { pushToast('ERROR', lang === 'zh' ? 'JSON 解析失败' : 'Invalid JSON', ''); return }
    const arr = Array.isArray(records) ? records : (records as { accounts?: unknown[] }).accounts || []
    if (arr.length === 0) { pushToast('ERROR', lang === 'zh' ? '数组为空' : 'Empty array', ''); return }
    setSubmittingBatch(true)
    try {
      const resp = await authedFetch('/ui/accounts/batch-import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accounts: arr }),
      })
      const data = await resp.json()
      if (data.status === 'ok') {
        pushToast('SUCCESS', lang === 'zh' ? `导入 ${data.imported} 个账号` : `Imported ${data.imported}`, lang === 'zh' ? `跳过 ${data.skipped}` : `skipped ${data.skipped}`)
        setBatchJson(''); setShowBatchImport(false); fetchAccounts()
      } else { pushToast('ERROR', lang === 'zh' ? '导入失败' : 'Import failed', data.detail || '') }
    } catch { pushToast('ERROR', lang === 'zh' ? '导入失败' : 'Import failed', '') } finally { setSubmittingBatch(false) }
  }, [authedFetch, batchJson, lang, fetchAccounts, pushToast])

  const doRefreshTokens = useCallback(async () => {
    setRefreshingTokens(true)
    try {
      const resp = await authedFetch('/ui/accounts/refresh-tokens', { method: 'POST' })
      const data = await resp.json()
      if (data.status === 'ok') {
        pushToast('SUCCESS', lang === 'zh' ? `刷新完成 ${data.ok}/${data.total}` : `Refreshed ${data.ok}/${data.total}`, lang === 'zh' ? `失败 ${data.failed}` : `failed ${data.failed}`)
      } else { pushToast('ERROR', lang === 'zh' ? '刷新失败' : 'Refresh failed', data.error || '') }
    } catch { pushToast('ERROR', lang === 'zh' ? '刷新失败' : 'Refresh failed', '') } finally { setRefreshingTokens(false) }
  }, [authedFetch, lang, pushToast])

  const loadQuota = useCallback(async () => {
    setLoadingQuota(true)
    try {
      const resp = await authedFetch('/ui/accounts/quota')
      const data = await resp.json()
      setQuotaList(data.quotas || [])
    } catch { pushToast('ERROR', lang === 'zh' ? '限额查询失败' : 'Quota query failed', '') } finally { setLoadingQuota(false) }
  }, [authedFetch, lang, pushToast])

  const fetchLogs = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/logs')
      if (!resp.ok) return
      const data = await resp.json()
      // 形状守卫：非数组响应（如 {"detail":...}）不进 state，避免渲染时 .filter 崩溃
      if (Array.isArray(data)) setLogs(data)
    } catch { /* */ }
  }, [authedFetch])
  const fetchRegStatus = useCallback(async () => {
    try {
      const resp = await authedFetch('/ui/registrar/status')
      if (!resp.ok) return
      const data = await resp.json()
      if (data && typeof data === 'object' && typeof data.running === 'boolean') setRegStatus(data)
    } catch { /* */ }
  }, [authedFetch])
  const startRegister = useCallback(async () => {
    if (regStatus?.running) return
    setRegStarting(true)
    try {
      const resp = await authedFetch('/ui/registrar/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parents: regCount }),
      })
      const data = await resp.json()
      if (data.ok) {
        pushToast('INFO', lang === 'zh' ? '注册已开始（无限循环）' : 'Registration started (looping)', lang === 'zh' ? `${data.parents} 个母线程，每个 3 子任务并发，请完成置顶的人机验证` : `${data.parents} parent threads x 3 workers, complete the topmost human verification`)
        fetchRegStatus()
      } else {
        pushToast('ERROR', lang === 'zh' ? '启动失败' : 'Start failed', data.error || '')
      }
    } catch { pushToast('ERROR', lang === 'zh' ? '启动失败' : 'Start failed', '') } finally { setRegStarting(false) }
  }, [authedFetch, fetchRegStatus, pushToast, regStatus?.running, lang, regCount])

  const stopRegister = useCallback(async () => {
    if (!regStatus?.running || regStopping) return
    setRegStopping(true)
    try {
      const resp = await authedFetch('/ui/registrar/stop', { method: 'POST' })
      const data = await resp.json()
      if (data.ok) {
        pushToast('INFO', lang === 'zh' ? '停止请求已发送' : 'Stop requested', lang === 'zh' ? '当前批次完成后停止' : 'Stops after the current batch')
      } else {
        pushToast('ERROR', lang === 'zh' ? '取消失败' : 'Stop failed', data.error || '')
      }
    } catch { pushToast('ERROR', lang === 'zh' ? '取消失败' : 'Stop failed', '') } finally { setRegStopping(false) }
  }, [authedFetch, pushToast, regStatus?.running, regStopping, lang])

  useEffect(() => {
    if (!token) return
    fetchStatus(); fetchAccounts(); fetchApiConfig(); fetchLogs(); fetchRegStatus()
    const si = setInterval(fetchStatus, 6000)
    const li = setInterval(() => { if (activeTab === 'logs') fetchLogs() }, 3000)
    const ri = setInterval(() => { if (activeTab === 'register' && regStatus?.running) fetchRegStatus() }, 2000)
    return () => { clearInterval(si); clearInterval(li); clearInterval(ri) }
  }, [token, activeTab, fetchStatus, fetchAccounts, fetchApiConfig, fetchLogs, fetchRegStatus, regStatus?.running])

  useEffect(() => { if (activeTab === 'logs') logEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [activeTab])
  // 日志更新时仅在用户本就接近底部（窗口滚动）时才跟随滚底，避免把正在上翻查看的用户拽回底部
  useEffect(() => {
    if (activeTab !== 'logs') return
    const doc = document.documentElement
    if (window.innerHeight + window.scrollY >= doc.scrollHeight - 50) logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])
  useEffect(() => { if (activeTab === 'playground') chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chatMessages, activeTab])

  // GSAP animations
  useEffect(() => { if (!token && loginCardRef.current) gsap.fromTo(loginCardRef.current, { scale: 0.92, opacity: 0, y: 30 }, { scale: 1, opacity: 1, y: 0, duration: 0.7, ease: 'back.out(1.4)' }) }, [token])
  useEffect(() => { if (token && sidebarRef.current) gsap.fromTo(sidebarRef.current, { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.5, ease: 'power3.out' }) }, [token])
  useEffect(() => { if (token && contentBodyRef.current) gsap.fromTo(contentBodyRef.current, { opacity: 0, y: 20 }, { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out' }) }, [activeTab, token])
  useEffect(() => {
    if (token && activeTab === 'dashboard' && statCardsRef.current) {
      const cards = statCardsRef.current.querySelectorAll('.stat-card')
      gsap.fromTo(cards, { opacity: 0, y: 30, scale: 0.95 }, { opacity: 1, y: 0, scale: 1, duration: 0.5, stagger: 0.1, ease: 'power2.out' })
    }
    // 不依赖 status：/ui/status 每 6s 轮询产生新对象，若入 deps 会让入场动画每 6s 重播闪烁
  }, [activeTab, token])
  useEffect(() => {
    if (token && activeTab === 'dashboard' && notifListRef.current) {
      const items = notifListRef.current.querySelectorAll('li')
      gsap.fromTo(items, { opacity: 0, x: -20 }, { opacity: 1, x: 0, duration: 0.4, stagger: 0.12, ease: 'power2.out' })
    }
  }, [activeTab, token])
  useEffect(() => {
    if (token && activeTab === 'dashboard' && terminalRef.current) {
      const lines = terminalRef.current.querySelectorAll('.term-line')
      gsap.fromTo(lines, { opacity: 0, x: -10 }, { opacity: 1, x: 0, duration: 0.3, stagger: 0.15, ease: 'power1.out' })
    }
  }, [activeTab, token])
  useEffect(() => {
    orbRefs.current.forEach((orb, i) => {
      if (!orb) return
      gsap.to(orb, { x: `+=${10 + i * 5}`, y: `-=${8 + i * 3}`, duration: 6 + i * 2, repeat: -1, yoyo: true, ease: 'sine.inOut' })
    })
  }, [token])

  // ─── Handlers ───

  const handleVerifyToken = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = inputToken.trim()
    if (!trimmed) return
    setVerifying(true); setAuthError(null)
    try {
      const resp = await fetch('/ui/verify', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: trimmed }) })
      if (resp.ok) {
        setLoginSuccess(true)
        if (loginCardRef.current) {
          gsap.to(loginCardRef.current, { scale: 1.02, duration: 0.3, ease: 'power2.out', onComplete: () => { localStorage.setItem('gateway_token', trimmed); setToken(trimmed); setInputToken('') } })
        }
      } else {
        if (loginCardRef.current) gsap.to(loginCardRef.current, { x: 10, duration: 0.04, repeat: 7, yoyo: true, onComplete: () => gsap.set(loginCardRef.current!, { x: 0 }) })
        // 展示后端真实错误（如 429 限速），解析失败再用兜底文案
        let detail = ''
        try { const errData = await resp.json(); detail = typeof errData?.detail === 'string' ? errData.detail : '' } catch { /* */ }
        setAuthError(detail || 'Invalid gateway access token')
      }
    } catch (err: any) { setAuthError(`Connection failed: ${err.message}`) } finally { setVerifying(false) }
  }

  const handleLogout = () => {
    stopDeviceAuthPolling()
    localStorage.removeItem('gateway_token')
    setToken(null)
    setLoginSuccess(false)
    setStatusLoaded(false)
    setDeviceAuth({ state: 'idle', nonce: null, authUrl: null })
    setToasts([])
  }

  const handleImportAuth = async () => {
    if (importingAuth) return
    setImportingAuth(true)
    try {
      const resp = await authedFetch('/ui/accounts/import', { method: 'POST' })
      if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || 'Import failed') }
      const data = await resp.json()
      pushToast('SUCCESS', lang === 'zh' ? '账号已导入' : 'Account Imported', msg.imported(data.account?.name || (lang === 'zh' ? '本地会话' : 'local session')))
      fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) {
      pushToast('ERROR', msg.importFailed, err.message)
    } finally { setImportingAuth(false) }
  }

  const handleSavePat = async () => {
    if (!patToken.trim()) return
    setSubmittingPat(true)
    try {
      const resp = await authedFetch('/ui/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pat: patToken }) })
      if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || 'PAT save failed') }
      const data = await resp.json()
      pushToast('SUCCESS', lang === 'zh' ? 'PAT 已添加' : 'PAT Added', msg.patAdded(data.name || 'PAT Account'))
      setPatToken(''); fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) {
      pushToast('ERROR', msg.patFailed, err.message)
    } finally { setSubmittingPat(false) }
  }

  const handleSelectAccount = async (uid: string) => {
    try {
      const resp = await authedFetch('/ui/accounts/select', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid }) })
      if (!resp.ok) throw new Error('Switch failed')
      pushToast('INFO', lang === 'zh' ? '账号已激活' : 'Account Activated', msg.activated(uid))
      fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) { pushToast('ERROR', msg.activationFailed, err.message) }
  }

  const handleToggleAccount = async (uid: string, enabled: boolean) => {
    try {
      const resp = await authedFetch('/ui/accounts/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, enabled }) })
      if (!resp.ok) throw new Error('Toggle failed')
      pushToast('INFO', lang === 'zh' ? '账号已更新' : 'Account Updated', msg.updated(enabled))
      fetchAccounts(); fetchStatus()
    } catch (err: any) { pushToast('ERROR', msg.toggleFailed, err.message) }
  }

  const handleDeleteAccount = async (uid: string) => {
    if (!confirm('Delete this account from the database?')) return
    try {
      const resp = await authedFetch(`/ui/accounts/${uid}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error('Delete failed')
      pushToast('SUCCESS', lang === 'zh' ? '账号已删除' : 'Account Deleted', msg.deleted(uid))
      fetchAccounts(); fetchStatus(); fetchLogs()
    } catch (err: any) { pushToast('ERROR', msg.deleteFailed, err.message) }
  }

  const handleSaveApiConfig = async (newConfig: APIConfig): Promise<boolean> => {
    try {
      const resp = await authedFetch('/ui/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newConfig) })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setApiConfig(newConfig)
      return true
    } catch { pushToast('ERROR', msg.configFailed, lang === 'zh' ? '无法更新 API 配置' : 'Could not update API configuration'); return false }
  }

  const handleToggleAuth = async () => {
    const updated = { ...apiConfig, auth_required: !apiConfig.auth_required }
    const ok = await handleSaveApiConfig(updated)
    if (ok) pushToast('INFO', lang === 'zh' ? '鉴权状态已更新' : 'Auth Toggled', msg.authToggled(updated.auth_required))
  }

  const handleGenerateKey = () => {
    const random = 'qg_live_' + Array.from(crypto.getRandomValues(new Uint8Array(16))).map(b => b.toString(16).padStart(2, '0')).join('')
    setNewKey(random)
    pushToast('INFO', lang === 'zh' ? 'Key 已生成' : 'Key Generated', msg.keyGenerated)
  }

  const handleAddKey = async () => {
    const trimmed = newKey.trim()
    if (!trimmed) return
    if (apiConfig.allowed_keys.includes(trimmed)) { pushToast('ERROR', lang === 'zh' ? 'Key 已存在' : 'Duplicate Key', msg.duplicateKey); return }
    const ok = await handleSaveApiConfig({ ...apiConfig, allowed_keys: [...apiConfig.allowed_keys, trimmed] })
    if (ok) { pushToast('SUCCESS', lang === 'zh' ? 'Key 已添加' : 'Key Added', msg.keyAdded); setNewKey('') }
  }

  const handleDeleteKey = async (key: string) => {
    const ok = await handleSaveApiConfig({ ...apiConfig, allowed_keys: apiConfig.allowed_keys.filter(k => k !== key) })
    if (ok) pushToast('SUCCESS', lang === 'zh' ? 'Key 已删除' : 'Key Removed', msg.keyRemoved)
  }

  const handleCopyKey = async (key: string) => {
    const ok = await copyTextToClipboard(key)
    if (!ok) {
      pushToast('ERROR', lang === 'zh' ? '复制失败' : 'Copy Failed', lang === 'zh' ? '当前环境不支持自动复制，请手动选择复制' : 'Automatic copy is not available here. Please copy manually.')
      return
    }
    setCopiedKey(key)
    pushToast('INFO', lang === 'zh' ? '已复制' : 'Copied', msg.copied)
    setTimeout(() => setCopiedKey(null), 2000)
  }

  const toggleKeyReveal = (key: string) => setRevealedKeys(prev => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })

  const handleRefreshStatus = () => {
    fetchAccounts(); fetchStatus(); fetchLogs()
    pushToast('INFO', msg.refreshed, lang === 'zh' ? '账号池和系统状态已更新' : 'Account pool and system status updated')
  }

  const handleStopChat = () => { abortRef.current?.abort() }

  const handleSendChat = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = chatInput.trim()
    if (!trimmed || generating) return
    setChatMessages(prev => [...prev, { role: 'user', content: trimmed }])
    setChatInput(''); setGenerating(true)
    setChatMessages(prev => [...prev, { role: 'assistant', content: '' }])

    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (apiConfig.auth_required && apiConfig.allowed_keys.length > 0) headers['Authorization'] = `Bearer ${apiConfig.allowed_keys[0]}`

    // 发送完整对话历史：跳过首条欢迎语和空的占位 assistant，系统提示词置顶
    const apiMessages: ChatApiMessage[] = [
      ...(systemPrompt.trim() ? [{ role: 'system' as const, content: systemPrompt.trim() }] : []),
      ...chatMessages.slice(1).filter(m => !(m.role === 'assistant' && !m.content.trim())),
      { role: 'user', content: trimmed },
    ]

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await fetch('/v1/chat/completions', { method: 'POST', headers, body: JSON.stringify({ model, messages: apiMessages, stream }), signal: controller.signal })
      if (!response.ok) {
        const errData = await response.json()
        const errMsg = errData.detail || errData.error?.message || response.statusText
        setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: `Request failed: ${errMsg}` }; return u })
        pushToast('ERROR', msg.aiFailed, errMsg)
        setGenerating(false); return
      }
      if (stream) {
        const reader = response.body?.getReader()
        if (!reader) throw new Error('No stream reader')
        const decoder = new TextDecoder('utf-8')
        let buffer = ''; let currentResponse = ''
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n'); buffer = lines.pop() || ''
          for (const line of lines) {
            const tl = line.trim()
            if (!tl.startsWith('data:')) continue
            const rawData = tl.slice(5).trim()
            if (rawData === '[DONE]') continue
            try { const parsed = JSON.parse(rawData); const chunk = parsed.choices?.[0]?.delta?.content || ''; currentResponse += chunk; setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: currentResponse }; return u }) } catch { /* */ }
          }
        }
        pushToast('SUCCESS', msg.responseDone, lang === 'zh' ? '流式响应已结束' : 'AI response stream finished successfully')
      } else {
        const data = await response.json()
        const ans = data.choices?.[0]?.message?.content || ''
        setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: ans }; return u })
        pushToast('SUCCESS', msg.responseDone, lang === 'zh' ? '已收到 AI 响应' : 'AI response received successfully')
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        // 用户主动停止：保留已生成内容，仅在还没有任何输出时给出占位说明
        setChatMessages(prev => {
          const u = [...prev]
          const last = u[u.length - 1]
          if (last && last.role === 'assistant' && !last.content.trim()) {
            u[u.length - 1] = { role: 'assistant', content: lang === 'zh' ? '（已停止生成）' : '(Generation stopped)' }
          }
          return u
        })
        pushToast('INFO', lang === 'zh' ? '已停止生成' : 'Generation Stopped', lang === 'zh' ? '已保留已生成的内容' : 'Kept the content generated so far')
      } else {
        setChatMessages(prev => { const u = [...prev]; u[u.length - 1] = { role: 'assistant', content: `Connection error: ${err.message}` }; return u })
        pushToast('ERROR', msg.connectionError, err.message)
      }
    } finally { abortRef.current = null; setGenerating(false) }
  }

  const toggleThinking = (idx: number) => setExpandedThinking(prev => {
    const next = new Set(prev)
    if (next.has(idx)) next.delete(idx); else next.add(idx)
    return next
  })

  const renderMessageContent = (text: string, msgIndex: number) => {
    const thinkingRegex = /<thinking>([\s\S]*?)(?:<\/thinking>|$)/
    const match = text.match(thinkingRegex)
    if (match) {
      const thinking = match[1]; const response = text.replace(thinkingRegex, '').trim()
      const expanded = expandedThinking.has(msgIndex)
      return (
        <div className="space-y-3">
          <div className="bg-canvas-soft border border-hairline rounded-xl overflow-hidden">
            <button onClick={() => toggleThinking(msgIndex)} className="w-full flex items-center gap-2 px-4 py-2.5 text-xs font-bold text-body hover:text-ink transition-colors">
              <span className="material-symbols-outlined text-base">psychology</span>Thinking Process
              <span className={`material-symbols-outlined transition-transform ${expanded ? 'rotate-180' : ''}`}>expand_more</span>
            </button>
            {expanded && <div className="px-4 py-3 text-xs text-body italic leading-relaxed border-t border-hairline opacity-70 whitespace-pre-wrap">{thinking}</div>}
          </div>
          {response && <div className="prose prose-stone max-w-none text-sm leading-relaxed"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{response}</ReactMarkdown></div>}
        </div>
      )
    }
    return <div className="prose prose-stone max-w-none text-sm leading-relaxed"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{text}</ReactMarkdown></div>
  }

  const getLogLevel = (log: string) => (log.match(/\[(INFO|ERROR|WARNING)\]/)?.[1] || 'INFO').toLowerCase()
  const getLogMinutes = (log: string) => {
    const match = log.match(/^\[(\d{2}):(\d{2}):(\d{2})\]/)
    if (!match) return null
    return Number(match[1]) * 60 + Number(match[2])
  }
  const getLogAccount = (log: string) => {
    const routed = log.match(/Request routing via account:\s*(.+?)\s*\(([^)]+)\)/)
    if (routed) return routed[2]
    const failed = log.match(/Request failed on account\s+([^:]+):/)
    if (failed) return failed[1]
    return null
  }
  const accountLogOptions = [
    { value: 'all', label: 'All Accounts' },
    ...Array.from(new Set([
      ...accountsConfig.accounts.map(acc => acc.uid),
      ...logs.map(getLogAccount).filter((uid): uid is string => Boolean(uid))
    ])).map(uid => ({ value: uid, label: accountsConfig.accounts.find(acc => acc.uid === uid)?.name || uid }))
  ]
  const filteredLogs = logs.filter(log => {
    if (logFilterStatus !== 'all' && getLogLevel(log) !== logFilterStatus) return false
    if (logFilterAccount !== 'all' && getLogAccount(log) !== logFilterAccount) return false
    if (logFilterRange === '1h') {
      const minutes = getLogMinutes(log)
      if (minutes === null) return false
      const now = new Date()
      const nowMinutes = now.getHours() * 60 + now.getMinutes()
      const diff = (nowMinutes - minutes + 1440) % 1440
      return diff <= 60
    }
    return true
  })
  // ─── LOGIN PAGE ───
  if (!token) {
    return (
      <div className="bg-surface text-ink min-h-screen flex items-center justify-center p-4 overflow-hidden relative">
        <div ref={el => { orbRefs.current[0] = el }} className="atmospheric-orb absolute top-1/4 left-1/3 w-[400px] h-[400px] bg-lavender rounded-full"></div>
        <div ref={el => { orbRefs.current[1] = el }} className="atmospheric-orb absolute bottom-1/4 right-1/3 w-[500px] h-[500px] bg-sky rounded-full" style={{ animationDelay: '-4s' }}></div>
        <main ref={loginCardRef} className="relative w-full max-w-[440px] z-10">
          <div className="surface-card glass-card rounded-xl p-8 border border-hairline shadow-sm">
            <div className="flex flex-col items-center mb-8">
              <div className="w-10 h-10 bg-ink rounded-lg flex items-center justify-center mb-4">
                <span className="material-symbols-outlined text-white" style={{ fontVariationSettings: "'FILL' 1" }}>gate</span>
              </div>
              <h1 className="font-display-lg text-ink tracking-tight">QoderGate</h1>
              <p className="text-[12px] font-semibold text-on-surface-variant mt-2 uppercase tracking-widest">{lang === 'zh' ? '管理控制台' : 'Management Console'}</p>
            </div>
            <form className="space-y-6" onSubmit={handleVerifyToken}>
              <div className="space-y-2">
                <label htmlFor="gateway-token" className="font-bold text-ink text-[16px]">{lang === 'zh' ? '网关访问密钥' : 'Gateway Access Token'}</label>
                <CustomInput id="gateway-token" type="password" value={inputToken} onChange={setInputToken} placeholder={lang === 'zh' ? '输入你的安全密钥...' : 'Enter your security token...'} />
              </div>
              {authError && (
                <div className="flex items-center gap-2 p-3.5 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs font-semibold">
                  <span className="material-symbols-outlined text-base">warning</span>{authError}
                </div>
              )}
              <button className={`w-full font-bold py-4 rounded-full transition-all flex items-center justify-center group ${loginSuccess ? 'bg-mint text-ink' : 'bg-ink text-white hover:bg-primary'}`} type="submit" disabled={verifying}>
                {verifying ? (
                  <><svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg><span>Authenticating...</span></>
                ) : loginSuccess ? (
                  <><span className="material-symbols-outlined">check_circle</span><span className="ml-2">{lang === 'zh' ? '访问已授权' : 'Access Granted'}</span></>
                ) : (
                  <><span className="text-[15px]">{lang === 'zh' ? '验证密钥' : 'Verify Token'}</span><span className="material-symbols-outlined ml-2 transition-transform group-hover:translate-x-1">arrow_forward</span></>
                )}
              </button>
            </form>
            <button onClick={() => switchLang(lang === 'zh' ? 'en' : 'zh')} className="mt-4 w-full text-xs font-bold text-body hover:text-ink transition-colors">
              {lang === 'zh' ? 'Switch to English' : '切换到中文'}
            </button>
            <div className="mt-8 pt-6 border-t border-hairline flex flex-col items-center gap-4">
              <div className="flex items-center gap-2 text-on-surface-variant"><span className="material-symbols-outlined text-[18px]">verified_user</span><p className="text-[13px]">End-to-end encrypted session</p></div>
              <p className="text-[12px] text-on-surface-variant/70 text-center leading-relaxed">Access is restricted to authorized personnel. All connection attempts are logged and monitored.</p>
            </div>
          </div>
          <div className="mt-4 flex justify-between px-4 opacity-40">
            <span className="text-[10px] tracking-widest text-ink uppercase">v2.4.0 stable</span>
            <span className="text-[10px] tracking-widest text-ink uppercase">Status: Operational</span>
          </div>
        </main>
      </div>
    )
  }

  // ─── MAIN LAYOUT ───
  const { bc, title } = pageMeta[activeTab]

  return (
    <div className="bg-surface min-h-screen relative">
      <div ref={el => { orbRefs.current[2] = el }} className="orb bg-mint w-[500px] h-[500px] -top-24 -right-24"></div>
      <div ref={el => { orbRefs.current[3] = el }} className="orb bg-peach w-[400px] h-[400px] bottom-0 left-[20%]"></div>

      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/30 z-40 lg:hidden" onClick={() => setSidebarOpen(false)} aria-hidden="true"></div>
      )}

      <aside ref={sidebarRef} className={`fixed left-0 top-0 h-screen w-[280px] bg-surface border-r border-hairline flex flex-col p-6 z-50 transition-transform duration-300 lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 bg-ink rounded-lg flex items-center justify-center"><span className="material-symbols-outlined text-white" style={{ fontVariationSettings: "'FILL' 1" }}>gate</span></div>
          <div><h1 className="font-display-sm text-ink leading-none">QoderGate</h1><p className="text-[10px] uppercase tracking-widest text-body opacity-60">{lang === 'zh' ? '管理控制台' : 'Management Console'}</p></div>
        </div>
        <nav className="flex-1 space-y-1">
          {NAV_ITEMS.map((item) => (
            <button key={item.id} onClick={() => { setActiveTab(item.id); setSidebarOpen(false) }} className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors font-medium w-full text-left ${activeTab === item.id ? 'bg-canvas-soft text-ink font-bold' : 'text-body hover:bg-canvas-soft'}`}>
              <span className="material-symbols-outlined" style={{ fontVariationSettings: activeTab === item.id ? "'FILL' 1" : "" }}>{item.icon}</span>{navLabels[item.id]}
            </button>
          ))}
        </nav>
        <div className="pt-8 border-t border-hairline">
          <div className="flex items-center justify-between px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${status.ready ? 'bg-mint animate-pulse' : 'bg-red-400'}`}></span>
              <span className="text-xs font-semibold text-body">{status.ready ? t.common.healthy : t.common.offline}</span>
            </div>
            <button onClick={handleLogout} className="text-xs font-bold text-body hover:text-red-600 transition-colors">{t.common.signOut}</button>
          </div>
        </div>
      </aside>

      <main className="lg:ml-[280px] min-h-screen flex flex-col relative z-10">
        <header className="flex justify-between items-center h-24 px-4 lg:px-8 w-full border-b border-hairline bg-transparent sticky top-0 z-40 backdrop-blur-sm">
          <div className="flex items-center gap-2 min-w-0">
            <button type="button" onClick={() => setSidebarOpen(true)} aria-label={lang === 'zh' ? '打开导航菜单' : 'Open navigation menu'} className="lg:hidden p-2 -ml-2 text-body hover:text-ink transition-colors">
              <span className="material-symbols-outlined">menu</span>
            </button>
            <div className="min-w-0">
              <span className="text-[12px] font-semibold text-body uppercase opacity-60 tracking-[0.96px]">{bc}</span>
              <h2 className="font-display-lg text-ink">{title}</h2>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-8 text-body text-[16px]">
              <a href="/documents" className="hover:text-ink transition-colors cursor-pointer">{t.common.docs}</a>
              <button onClick={() => switchLang(lang === 'zh' ? 'en' : 'zh')} className="hover:text-ink transition-colors cursor-pointer">{lang === 'zh' ? 'English' : '中文'}</button>
              <a href="https://github.com/Arimayuki03/QoderGateway" target="_blank" rel="noreferrer" className="hover:text-ink transition-colors cursor-pointer">{t.common.support}</a>
            </div>
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-full bg-hairline flex items-center justify-center border border-hairline-strong text-xs font-bold text-ink">{status.username ? status.username[0].toUpperCase() : 'Q'}</div>
            </div>
          </div>
        </header>

        <div ref={contentBodyRef} className="flex-1 p-4 lg:p-8 w-full">
          {/* ─── DASHBOARD ─── */}
          {activeTab === 'dashboard' && (
            <div className="space-y-8">
              <section ref={statCardsRef} className="grid grid-cols-1 md:grid-cols-4 gap-6">
                {[
                  { label: t.dashboard.serviceStatus, value: status.ready ? t.common.healthy : (statusLoaded ? t.common.offline : t.common.checking), detail: status.ready ? t.dashboard.allGatewaysActive : (statusLoaded ? t.dashboard.noActiveSession : (lang === 'zh' ? '正在检查网关状态...' : 'Checking gateway status...')), dot: status.ready ? 'bg-mint' : (statusLoaded ? 'bg-red-400' : 'bg-neutral-400') },
                  { label: t.dashboard.accountPool, value: String(status.accounts_count || 0), detail: t.dashboard.activeSessions },
                  { label: t.dashboard.apiAuth, value: apiConfig.auth_required ? (lang === 'zh' ? '已开启' : 'Enabled') : (lang === 'zh' ? '未开启' : 'Disabled'), detail: apiConfig.auth_required ? `${apiConfig.allowed_keys.length} keys active` : t.dashboard.openAccess },
                  { label: t.dashboard.activeUser, value: status.username || (lang === 'zh' ? '无' : 'None'), detail: status.user_type || 'N/A' }
                ].map((stat, i) => (
                  <div key={i} className="stat-card bg-surface-card border border-hairline p-6 rounded-xl hover:shadow-[0_4px_16px_rgba(0,0,0,0.04)] transition-all cursor-default">
                    <div className="text-[12px] font-semibold text-body mb-2 uppercase tracking-widest">{stat.label}</div>
                    <div className="flex items-center gap-2"><span className="font-display-sm text-ink">{stat.value}</span>{stat.dot && <div className={`h-2 w-2 rounded-full ${stat.dot}`}></div>}</div>
                    <div className="text-[12px] text-body mt-2">{stat.detail}</div>
                  </div>
                ))}
              </section>

              <section className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch">
                <div className="lg:col-span-2 glass-card p-8 rounded-2xl flex flex-col">
                  <div className="text-[12px] font-semibold text-body mb-2 uppercase tracking-widest">{t.dashboard.systemBriefing}</div>
                  <div className="font-display-md text-ink mb-4 max-w-lg">{status.ready ? t.dashboard.readyBrief.replace('{count}', String(status.accounts_count)) : (statusLoaded ? t.dashboard.notReadyBrief : (lang === 'zh' ? '正在检查网关状态...' : 'Checking gateway status...'))}</div>
                  <div className="mt-auto bg-ink/5 p-4 rounded-lg border border-hairline-strong" ref={terminalRef}>
                    <code className="text-sm font-mono text-ink">
                      <span className="text-primary font-bold">system@qodergate:~$</span> status --check --all<br />
                      <span className="term-line opacity-70">Checking nodes... [{status.ready ? 'OK' : 'FAIL'}]<br /></span>
                      <span className="term-line opacity-70">Validating certificates... [OK]<br /></span>
                      <span className="term-line opacity-70">Routing traffic to nearest node...</span><span className="cursor-blink">_</span>
                    </code>
                  </div>
                </div>
                <div className="bg-surface-card border border-hairline p-8 rounded-2xl">
                  <div className="text-[12px] font-semibold text-body mb-6 uppercase tracking-widest">{t.dashboard.recentNotifications}</div>
                  <ul ref={notifListRef} className="space-y-4">
                    {status.error ? (
                      <li className="flex items-start gap-4"><span className="material-symbols-outlined text-peach">warning</span><div><div className="font-bold text-[16px]">{t.dashboard.authImportError}</div><div className="text-[12px] text-body break-all">{status.error}</div></div></li>
                    ) : (
                      <>
                        <li className="flex items-start gap-4"><span className="material-symbols-outlined text-sky">info</span><div><div className="font-bold text-[16px]">{t.dashboard.apiAuth}</div><div className="text-[12px] text-body">{apiConfig.auth_required ? (lang === 'zh' ? '外部请求需要 API Key' : 'External requests require API keys') : t.dashboard.openAccess}</div></div></li>
                        <li className="flex items-start gap-4"><span className="material-symbols-outlined text-mint">check_circle</span><div><div className="font-bold text-[16px]">{t.dashboard.sessionActive}</div><div className="text-[12px] text-body">{status.username || (lang === 'zh' ? '暂无账号' : 'No account')}</div></div></li>
                      </>
                    )}
                  </ul>
                </div>
              </section>

              <section className="bg-surface-card border border-hairline p-8 rounded-2xl">
                <div className="text-[12px] font-semibold text-body mb-2 uppercase tracking-widest">{t.dashboard.credentialConfig}</div>
                <p className="text-body text-[16px] mb-6">{t.dashboard.credentialDesc}</p>
                <div className="flex flex-col sm:flex-row gap-4 max-w-2xl">
                  <div className="flex-grow">
                    <CustomInput type="password" value={patToken} onChange={setPatToken} placeholder={t.dashboard.patPlaceholder} />
                  </div>
                  <div className="flex gap-2">
                    <button onClick={handleSavePat} disabled={submittingPat} className="bg-ink text-white font-bold px-5 py-3 rounded-lg text-sm transition-all hover:bg-primary disabled:opacity-50">
                      {submittingPat ? t.dashboard.saving : t.dashboard.addPat}
                    </button>
                    <button onClick={handleImportAuth} disabled={importingAuth} className="flex items-center gap-2 px-4 py-3 text-ink hover:bg-canvas-soft border border-hairline font-semibold rounded-lg text-sm transition-all disabled:opacity-40">
                      <span className="material-symbols-outlined text-[18px]">refresh</span>{t.dashboard.autoImport}
                    </button>
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ─── ACCOUNT POOL ─── */}
          {activeTab === 'accounts' && (
            <div className="space-y-8">
              <section className="flex justify-between items-end flex-wrap gap-4">
                <div className="max-w-xl"><p className="text-body text-[16px]">{t.accounts.desc}</p></div>
                <div className="flex gap-4 flex-wrap">
                  <button onClick={startDeviceAuth} disabled={deviceAuth.state === 'waiting'} className="flex items-center gap-2 px-4 py-2.5 rounded-lg transition-all font-bold text-sm border bg-ink text-white border-ink hover:bg-neutral-800 disabled:opacity-50">
                    <span className="material-symbols-outlined text-[18px]">devices</span>{deviceAuth.state === 'waiting' ? (lang === 'zh' ? '等待授权中...' : 'Waiting for auth...') : (lang === 'zh' ? '设备授权导入' : 'Device Auth Import')}
                  </button>
                  <button onClick={() => { setShowBatchImport(v => !v); setQuotaList(null) }} className={`flex items-center gap-2 px-4 py-2.5 rounded-lg transition-all font-bold text-sm border ${showBatchImport ? 'bg-ink text-white border-ink' : 'text-body hover:text-ink border-hairline'}`}>
                    <span className="material-symbols-outlined text-[18px]">file_upload</span>{lang === 'zh' ? '批量导入' : 'Batch Import'}
                  </button>
                  <button onClick={doRefreshTokens} disabled={refreshingTokens} className="flex items-center gap-2 px-4 py-2.5 text-body hover:text-ink transition-colors font-bold text-sm disabled:opacity-40">
                    <span className="material-symbols-outlined text-[18px]">autorenew</span>{refreshingTokens ? (lang === 'zh' ? '刷新中...' : 'Refreshing...') : (lang === 'zh' ? '刷新 Token' : 'Refresh Tokens')}
                  </button>
                  <button onClick={() => { loadQuota(); setShowBatchImport(false) }} disabled={loadingQuota} className={`flex items-center gap-2 px-4 py-2.5 rounded-lg transition-all font-bold text-sm border disabled:opacity-40 ${quotaList ? 'bg-ink text-white border-ink' : 'text-body hover:text-ink border-hairline'}`}>
                    <span className="material-symbols-outlined text-[18px]">data_usage</span>{loadingQuota ? (lang === 'zh' ? '查询中...' : 'Loading...') : (lang === 'zh' ? '查看限额' : 'Quota')}
                  </button>
                  <button onClick={handleRefreshStatus} className="flex items-center gap-2 px-4 py-2.5 text-body hover:text-ink transition-colors font-bold text-sm">
                    <span className="material-symbols-outlined text-[18px]">refresh</span>{t.accounts.refreshStatus}
                  </button>
                  <button onClick={handleImportAuth} disabled={importingAuth} className="flex items-center gap-2 px-6 py-2.5 bg-ink text-white rounded-lg hover:bg-neutral-800 transition-all font-bold text-sm shadow-md disabled:opacity-50">
                    <span className="material-symbols-outlined text-[18px]">add</span>{t.accounts.importAccounts}
                  </button>
                </div>
              </section>

              {deviceAuth.state === 'waiting' && (
                <section className="bg-surface-card border border-hairline rounded-2xl p-6">
                  <div className="flex items-start gap-3">
                    <span className="material-symbols-outlined text-ink animate-pulse">devices</span>
                    <div className="flex-grow">
                      <p className="font-bold text-ink">{lang === 'zh' ? '等待你在浏览器中完成授权…' : 'Waiting for browser authorization…'}</p>
                      <p className="text-body text-sm mt-1">{lang === 'zh' ? '已打开新标签页，请登录 Qoder 并点击「继 续」。若未自动打开，' : 'A new tab has opened. Sign in to Qoder and click Continue. If it did not open, '}
                        <a href={deviceAuth.authUrl || '#'} target="_blank" rel="noopener" className="text-ink underline font-semibold">{lang === 'zh' ? '点此打开授权页' : 'open the auth page'}</a>
                        {lang === 'zh' ? '。授权完成后本页会自动导入账号。' : '. The account will be imported automatically after authorization.'}
                      </p>
                    </div>
                    <button onClick={() => { stopDeviceAuthPolling(); setDeviceAuth({ state: 'idle', nonce: null, authUrl: null }) }} className="px-3 py-1.5 text-body border border-hairline rounded-lg text-xs font-bold hover:text-ink">{lang === 'zh' ? '取消' : 'Cancel'}</button>
                  </div>
                </section>
              )}

              {showBatchImport && (
                <section className="bg-surface-card border border-hairline rounded-2xl p-6">
                  <label className="text-[12px] font-semibold text-body mb-3 block uppercase tracking-widest">{lang === 'zh' ? '粘贴注册机导出的 JSON（accounts.json）' : 'Paste registrar-exported JSON (accounts.json)'}</label>
                  <textarea
                    value={batchJson}
                    onChange={e => setBatchJson(e.target.value)}
                    rows={6}
                    placeholder='[{ "user_id": "019f...", "name": "...", "email": "...", "token": "dt-...", "refresh_token": "drt-...", "expires_at": "..." }]'
                    className="w-full p-4 rounded-xl border border-hairline bg-white/60 font-mono text-[13px] text-ink outline-none focus:border-ink/30 transition-colors"
                  />
                  <div className="mt-3 flex gap-3">
                    <button onClick={doBatchImport} disabled={submittingBatch} className="bg-ink text-white font-bold px-6 py-2.5 rounded-lg text-sm transition-all hover:bg-neutral-800 disabled:opacity-50">{submittingBatch ? (lang === 'zh' ? '导入中...' : 'Importing...') : (lang === 'zh' ? '导入' : 'Import')}</button>
                    <button onClick={() => { setBatchJson(''); setShowBatchImport(false) }} className="px-4 py-2.5 text-body border border-hairline rounded-lg text-sm font-bold hover:text-ink">{lang === 'zh' ? '取消' : 'Cancel'}</button>
                  </div>
                </section>
              )}

              {quotaList && (
                <section className="bg-surface-card border border-hairline rounded-2xl overflow-hidden">
                  <div className="px-6 py-4 border-b border-hairline flex items-center gap-2">
                    <span className="material-symbols-outlined text-[18px] text-body">data_usage</span>
                    <span className="text-sm font-semibold text-ink">{lang === 'zh' ? '账号限额（credits）' : 'Account Quota (credits)'}</span>
                    <button onClick={loadQuota} disabled={loadingQuota} className="ml-auto text-[12px] text-body hover:text-ink flex items-center gap-1 disabled:opacity-40"><span className="material-symbols-outlined text-[14px]">refresh</span>{lang === 'zh' ? '刷新' : 'Refresh'}</button>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-canvas-soft border-b border-hairline">
                        <tr>{['Account', 'Total', 'Used', 'Remaining', 'Usage %'].map((h, i) => (
                          <th key={i} className="px-6 py-3 text-[10px] font-semibold text-body uppercase tracking-wider">{h}</th>
                        ))}</tr>
                      </thead>
                      <tbody className="divide-y divide-hairline">
                        {quotaList.map((q, i) => {
                          const uq = q.quota?.userQuota || {}
                          // percentage 可能是 0-1 或 0-100（透传上游），统一归一化后再判断阈值/画进度条
                          const pct = normalizeQuotaPct(uq.percentage)
                          return (
                            <tr key={i} className="hover:bg-canvas-soft transition-colors">
                              <td className="px-6 py-4 font-semibold text-ink">{q.name || q.uid.slice(0, 12)}</td>
                              <td className="px-6 py-4 font-mono text-xs text-body">{uq.total ?? '--'}</td>
                              <td className="px-6 py-4 font-mono text-xs text-body">{uq.used ?? '--'}</td>
                              <td className={`px-6 py-4 font-mono text-xs ${pct > 0.8 ? 'text-red-600 font-bold' : 'text-body'}`}>{uq.remaining ?? '--'}</td>
                              <td className="px-6 py-4">
                                <div className="w-24 h-1.5 bg-hairline-strong rounded-full overflow-hidden">
                                  <div className={`h-full ${pct > 0.8 ? 'bg-red-500' : 'bg-mint'}`} style={{ width: `${Math.min(100, pct * 100)}%` }} />
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                        {quotaList.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-xs text-body">{lang === 'zh' ? '暂无账号' : 'No accounts'}</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              <section className="flex items-center gap-6">
                <div className="relative flex-grow max-w-md group">
                  <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-body opacity-50 group-focus-within:opacity-100 transition-opacity">search</span>
                  <CustomInput value={searchAccounts} onChange={setSearchAccounts} placeholder={t.accounts.search} className="!pl-12 !py-3 !rounded-xl !bg-white/50" />
                </div>
              </section>

              <section className="glass-card rounded-2xl overflow-hidden shadow-sm">
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="bg-canvas-soft border-b border-hairline">
                      <tr>{['Account', 'UID', 'Plan / Quota', 'Status', 'Reset', 'Enabled', 'Actions'].map((h, i) => (
                        <th key={i} className={`px-6 py-4 text-[10px] font-semibold text-body uppercase tracking-wider ${i === 5 ? 'text-center' : ''}`}>{h}</th>
                      ))}</tr>
                    </thead>
                    <tbody className="divide-y divide-hairline">
                      {accountsConfig.accounts.length === 0 ? (
                        <tr><td colSpan={7} className="py-8 text-center text-xs text-body font-medium">{t.accounts.empty}</td></tr>
                      ) : accountsConfig.accounts
                        .filter(acc => !searchAccounts || acc.name.toLowerCase().includes(searchAccounts.toLowerCase()) || acc.uid.includes(searchAccounts))
                        .map((acc) => {
                          const isActive = accountsConfig.active_uid === acc.uid
                          return (
                            <tr key={acc.uid} className={`hover:bg-canvas-soft transition-colors group ${isActive ? 'bg-mint/5' : ''}`}>
                              <td className="px-6 py-5 font-bold text-ink"><div className="flex items-center gap-2">{acc.name}{isActive && <span className="text-[9px] bg-mint/20 text-ink px-1.5 py-0.5 rounded font-extrabold uppercase">Active</span>}</div></td>
                              <td className="px-6 py-5 font-mono text-xs text-body select-all">{acc.uid}</td>
                              <td className="px-6 py-5"><div className="flex flex-col"><span className="text-xs font-semibold text-ink">{acc.user_tag || acc.plan || 'Trial'}</span><span className="text-[10px] text-body font-mono">Quota: {acc.quota}</span></div></td>
                              <td className="px-6 py-5">
                                {acc.is_quota_exceeded ? <span className="px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider bg-red-100 text-red-700">Exceeded</span>
                                : acc.last_status === 'ok' ? <span className="px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider bg-mint/20 text-ink">Enabled</span>
                                : <span className="px-3 py-1 text-[10px] font-bold rounded-full uppercase tracking-wider bg-red-100 text-red-700" title={acc.last_error || ''}>Error</span>}
                              </td>
                              <td className="px-6 py-5 text-xs font-mono text-body">{acc.next_reset_at ? new Date(acc.next_reset_at).toLocaleDateString() : '--'}</td>
                              <td className="px-6 py-5 text-center">
                                <button
                                  onClick={() => handleToggleAccount(acc.uid, !acc.enabled)}
                                  role="switch"
                                  aria-checked={acc.enabled}
                                  aria-label={lang === 'zh' ? `${acc.enabled ? '禁用' : '启用'}账号 ${acc.name}` : `${acc.enabled ? 'Disable' : 'Enable'} account ${acc.name}`}
                                  className={`w-11 h-6 rounded-full p-0.5 transition-colors relative ${acc.enabled ? 'bg-ink' : 'bg-hairline-strong'}`}
                                >
                                  <div className={`w-5 h-5 bg-white rounded-full transition-transform duration-200 ${acc.enabled ? 'translate-x-5' : 'translate-x-0'}`}></div>
                                </button>
                              </td>
                              <td className="px-6 py-5 text-right">
                                <div className="flex items-center justify-end gap-4 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                                  <button onClick={() => handleSelectAccount(acc.uid)} disabled={isActive || !acc.enabled} className="text-body hover:text-ink disabled:opacity-30" title="Activate" aria-label={lang === 'zh' ? `激活账号 ${acc.name}` : `Activate account ${acc.name}`}><span className="material-symbols-outlined">play_circle</span></button>
                                  <button onClick={() => handleDeleteAccount(acc.uid)} className="text-body hover:text-red-600" title="Delete" aria-label={lang === 'zh' ? `删除账号 ${acc.name}` : `Delete account ${acc.name}`}><span className="material-symbols-outlined">delete</span></button>
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                    </tbody>
                  </table>
                </div>
                <div className="px-6 py-5 flex items-center justify-between border-t border-hairline bg-canvas-soft/20">
                  <p className="text-[11px] text-body uppercase tracking-wider">{t.accounts.showing.replace('{count}', String(accountsConfig.accounts.length))}</p>
                </div>
              </section>
            </div>
          )}

          {/* ─── AI PLAYGROUND ─── */}
          {activeTab === 'playground' && (
            <div className="flex flex-col lg:flex-row gap-4 lg:gap-8 lg:h-[calc(100vh-14rem)]">
              <section className="w-full lg:w-[320px] shrink-0 flex flex-col gap-6 lg:overflow-y-auto lg:pr-4">
                <div className="space-y-3">
                  <label className="font-bold text-ink">{t.playground.modelConfig}</label>
                  <CustomInput value={model} onChange={setModel} placeholder="e.g. lite, pro" />
                </div>
                <div className="space-y-3">
                  <CustomCheckbox checked={stream} onChange={setStream} label={t.playground.streamResponse} />
                </div>
                <div className="space-y-3 flex-1 flex flex-col">
                  <label className="font-bold text-ink">{t.playground.systemPrompt}</label>
                  <CustomTextarea value={systemPrompt} onChange={setSystemPrompt} placeholder={t.playground.systemPromptPlaceholder} className="flex-1 !min-h-[150px]" />
                </div>
              </section>

              <section className="flex-1 flex flex-col glass-card rounded-2xl overflow-hidden shadow-sm relative">
                <div className="flex-1 overflow-y-auto p-8 space-y-8">
                  {chatMessages.map((msg, idx) => (
                    <div key={idx} className={`flex gap-4 ${msg.role === 'user' ? 'max-w-[80%] ml-auto flex-row-reverse' : ''}`}>
                      <div className={`w-8 h-8 rounded flex-shrink-0 flex items-center justify-center text-[10px] font-bold ${msg.role === 'user' ? 'bg-ink text-white' : 'bg-mint text-ink'}`}>
                        {msg.role === 'user' ? 'U' : <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: "'FILL' 1" }}>bolt</span>}
                      </div>
                      <div className={`flex-1 ${msg.role === 'user' ? '' : 'space-y-4'}`}>
                        {msg.role === 'user' ? (
                          <div className="bg-canvas-soft border border-hairline p-4 rounded-xl rounded-tl-none"><p className="text-ink whitespace-pre-wrap">{msg.content}</p></div>
                        ) : msg.content === '' ? (
                          <div className="flex items-center gap-2 text-body py-1 text-xs font-semibold animate-pulse">
                            <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                            {t.playground.waiting}
                          </div>
                        ) : renderMessageContent(msg.content, idx)}
                      </div>
                    </div>
                  ))}
                  <div ref={chatEndRef} />
                </div>
                <form onSubmit={handleSendChat} className="p-4 lg:p-8 border-t border-hairline bg-white/50">
                  <div className="flex items-center gap-3">
                    <CustomTextarea value={chatInput} onChange={setChatInput} placeholder={t.playground.ask} className="flex-1" />
                    {generating ? (
                      <button type="button" onClick={handleStopChat} className="h-11 px-4 bg-white border border-hairline-strong text-ink rounded-xl flex items-center gap-2 hover:bg-canvas-soft transition-all active:scale-95 shadow-md shrink-0">
                        <span className="material-symbols-outlined text-sm">stop_circle</span><span className="font-bold text-sm">{lang === 'zh' ? '停止生成' : 'Stop'}</span>
                      </button>
                    ) : (
                      <button type="submit" disabled={!chatInput.trim()} className="h-11 px-4 bg-ink text-white rounded-xl flex items-center gap-2 hover:bg-neutral-800 transition-all active:scale-95 shadow-md disabled:opacity-50 shrink-0">
                        <span className="font-bold text-sm">{t.playground.send}</span><span className="material-symbols-outlined text-sm">send</span>
                      </button>
                    )}
                  </div>
                </form>
              </section>
            </div>
          )}

          {/* ─── API KEYS ─── */}
          {activeTab === 'api-keys' && (
            <div className="space-y-8">
              <div className="flex justify-between items-end">
                <p className="text-body font-medium max-w-xl">{t.api.desc}</p>
                <button onClick={handleGenerateKey} className="bg-ink text-white px-6 py-3 rounded-xl flex items-center gap-2 hover:bg-neutral-800 transition-all font-bold shadow-md">
                  <span className="material-symbols-outlined text-[20px]">add</span>{t.api.generate}
                </button>
              </div>

              <div className="grid grid-cols-12 gap-8">
                <div className="col-span-12 lg:col-span-4 flex flex-col gap-6">
                  <div className="glass-card p-8 rounded-2xl flex flex-col justify-between min-h-[220px]">
                    <div><h3 className="font-bold text-ink text-lg mb-2">{t.api.gatewayAuth}</h3><p className="text-body text-sm">{t.api.gatewayAuthDesc}</p></div>
                    <div className="flex items-center justify-between pt-6 border-t border-hairline mt-auto">
                      <span className="text-[10px] font-bold text-body uppercase tracking-widest">{t.api.systemStatus}</span>
                      <button
                        role="switch"
                        aria-checked={apiConfig.auth_required}
                        aria-label={t.api.gatewayAuth}
                        className={`w-11 h-6 rounded-full p-0.5 transition-colors relative ${apiConfig.auth_required ? 'bg-ink' : 'bg-hairline-strong'}`}
                        onClick={handleToggleAuth}
                      >
                        <div className={`w-5 h-5 bg-white rounded-full transition-transform duration-200 ${apiConfig.auth_required ? 'translate-x-5' : 'translate-x-0'}`}></div>
                      </button>
                    </div>
                  </div>
                  <div className="glass-card p-4 rounded-xl">
                    <span className="text-[10px] font-bold text-body uppercase tracking-widest">{t.api.activeKeys}</span>
                    <div className="mt-2 flex items-baseline gap-2"><span className="font-display-sm text-ink">{apiConfig.allowed_keys.length}</span><span className="text-[10px] text-body font-bold">{t.api.configured}</span></div>
                  </div>
                </div>
                <div className="col-span-12 lg:col-span-8 glass-card rounded-2xl overflow-hidden flex flex-col shadow-sm">
                  <div className="p-6 flex items-center justify-between border-b border-hairline">
                    <span className="font-bold">{t.api.activeAccessKeys}</span>
                    <div className="flex gap-2">
                      <CustomInput value={newKey} onChange={setNewKey} placeholder={t.api.keyPlaceholder} className="!w-64 !py-2 !bg-canvas-soft !border-hairline" mono />
                      <button onClick={handleAddKey} disabled={!newKey.trim()} className="bg-ink text-white px-4 py-2 rounded-lg font-bold text-sm hover:bg-neutral-800 transition-all disabled:opacity-50">{t.common.add}</button>
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left">
                      <thead className="bg-canvas-soft/50 border-b border-hairline"><tr>{['Key String', 'Actions'].map(h => (<th key={h} className="px-6 py-4 text-[10px] font-semibold text-body uppercase tracking-widest">{h}</th>))}</tr></thead>
                      <tbody className="divide-y divide-hairline">
                        {apiConfig.allowed_keys.length === 0 ? (
                          <tr><td colSpan={2} className="py-6 text-center text-xs text-body font-medium">{t.api.noKeys}</td></tr>
                        ) : apiConfig.allowed_keys.map((key) => (
                          <tr key={key} className="hover:bg-canvas-soft/30 transition-colors">
                            <td className="px-6 py-5 font-mono text-xs tracking-wider text-body opacity-80 select-all break-all">
                              {/* 默认掩码显示，避免与同页"安全建议"矛盾；眼睛按钮按 key 切换显示全文 */}
                              {revealedKeys.has(key) ? key : maskApiKey(key)}
                            </td>
                            <td className="px-6 py-5 text-right">
                              <div className="flex justify-end gap-2">
                                <button
                                  onClick={() => toggleKeyReveal(key)}
                                  className="p-1.5 text-body hover:text-ink"
                                  title={revealedKeys.has(key) ? 'Hide' : 'Show'}
                                  aria-label={lang === 'zh' ? (revealedKeys.has(key) ? '隐藏 API Key' : '显示 API Key') : (revealedKeys.has(key) ? 'Hide API key' : 'Show API key')}
                                >
                                  <span className="material-symbols-outlined text-[18px]">{revealedKeys.has(key) ? 'visibility_off' : 'visibility'}</span>
                                </button>
                                <button onClick={() => handleCopyKey(key)} className="p-1.5 text-body hover:text-ink" title="Copy" aria-label={lang === 'zh' ? '复制 API Key' : 'Copy API key'}><span className="material-symbols-outlined text-[18px]">{copiedKey === key ? 'check_circle' : 'content_copy'}</span></button>
                                <button onClick={() => handleDeleteKey(key)} className="p-1.5 text-red-400 hover:text-red-600" title="Delete" aria-label={lang === 'zh' ? '删除 API Key' : 'Delete API key'}><span className="material-symbols-outlined text-[18px]">block</span></button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <section className="bg-ink text-white p-8 rounded-2xl flex items-center justify-between relative overflow-hidden shadow-xl">
                <div className="relative z-10 max-w-xl">
                  <h2 className="font-display-sm mb-4">{t.api.bestPractices}</h2>
                  <p className="text-white/70 font-medium leading-relaxed text-sm">{t.api.bestPracticesDesc}</p>
                </div>
                <div className="hidden lg:block opacity-20"><span className="material-symbols-outlined" style={{ fontSize: '120px', fontVariationSettings: "'FILL' 1" }}>shield</span></div>
              </section>
            </div>
          )}

          {/* ─── LOGS ─── */}
          {activeTab === 'logs' && (
            <div className="space-y-8">
              <div className="relative z-[4000] grid grid-cols-1 md:grid-cols-4 gap-4 p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.logs.account}</label>
                  <CustomSelect value={logFilterAccount} onChange={setLogFilterAccount} options={accountLogOptions.map((option, index) => index === 0 ? { ...option, label: t.logs.allAccounts } : option)} placeholder={t.logs.allAccounts} />
                </div>
                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.logs.status}</label>
                  <CustomSelect value={logFilterStatus} onChange={setLogFilterStatus} options={[{ value: 'all', label: t.logs.allStatuses }, { value: 'info', label: 'Info' }, { value: 'error', label: 'Error' }, { value: 'warning', label: 'Warning' }]} placeholder={t.logs.allStatuses} />
                </div>
                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.logs.range}</label>
                  <CustomSelect value={logFilterRange} onChange={setLogFilterRange} options={[{ value: 'all', label: t.logs.allTime }, { value: '1h', label: t.logs.lastHour }]} placeholder={t.logs.allTime} />
                </div>
                <div className="flex items-end">
                  <button onClick={() => { fetchLogs(); pushToast('INFO', 'Logs Refreshed', 'Log entries updated') }} className="w-full h-11 bg-ink text-white rounded-xl flex items-center justify-center gap-2 hover:bg-neutral-800 transition-all shadow-sm">
                    <span className="material-symbols-outlined text-sm">filter_list</span><span className="font-bold text-sm">{t.common.refresh}</span>
                  </button>
                </div>
              </div>

              <div className="relative z-0 bg-white/80 backdrop-blur-xl border border-hairline rounded-2xl overflow-hidden">
                <table className="w-full text-left">
                  <thead><tr className="bg-canvas-soft border-b border-hairline">{[t.logs.timestamp, t.logs.level, t.logs.message].map(h => (<th key={h} className="px-6 py-4 text-[10px] font-semibold text-body uppercase tracking-widest">{h}</th>))}</tr></thead>
                  <tbody className="divide-y divide-hairline">
                    {logs.length === 0 ? (
                      <tr><td colSpan={3} className="py-8 text-center text-xs text-body font-medium">{t.logs.noLogs}</td></tr>
                    ) : filteredLogs.length === 0 ? (
                      <tr><td colSpan={3} className="py-8 text-center text-xs text-body font-medium">{t.logs.noMatch}</td></tr>
                    ) : filteredLogs.map((log, i) => {
                      const isError = log.includes('[ERROR]') || log.includes('[WARNING]')
                      return (
                        <tr key={i} className={`hover:bg-black/5 transition-colors ${isError ? 'bg-red-50' : ''}`}>
                          <td className="px-6 py-4 font-mono text-[13px] text-body whitespace-nowrap">{log.substring(0, 10)}</td>
                          <td className="px-6 py-4">
                            <span className={`px-2 py-1 rounded text-[11px] font-bold uppercase ${log.includes('[ERROR]') ? 'bg-red-50 text-red-700' : log.includes('[WARNING]') ? 'bg-peach/20 text-ink' : 'bg-mint/20 text-ink'}`}>
                              {log.match(/\[(INFO|ERROR|WARNING)\]/)?.[1] || 'INFO'}
                            </span>
                          </td>
                          <td className="px-6 py-4 font-mono text-[13px] text-ink opacity-80 break-all">{log.replace(/^\[[\d:]+\]\s*\[\w+\]\s*/, '')}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <div ref={logEndRef} />
              </div>
            </div>
          )}

          {/* ─── AUTO REGISTRAR ─── */}
          {activeTab === 'register' && (
            <div className="space-y-6">
              <div className="relative z-[4000] flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                <div>
                  <h2 className="text-lg font-semibold text-ink">{t.title.register}</h2>
                  <p className="text-sm text-body mt-1 max-w-2xl">{t.register.desc}</p>
                  <p className="text-xs text-body opacity-70 mt-1">{t.register.staggerHint}</p>
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{t.register.countLabel}</span>
                    <div className="flex bg-white border border-hairline rounded-xl p-1 gap-1">
                      {[1, 2, 3, 4].map(n => (
                        <button
                          key={n}
                          onClick={() => setRegCount(n)}
                          disabled={regStatus?.running}
                          className={`w-9 h-9 rounded-lg text-sm font-bold transition-all ${regCount === n ? 'bg-ink text-white' : 'text-body hover:bg-black/5'}`}
                        >{n}</button>
                      ))}
                    </div>
                  </div>
                  {regStatus?.running ? (
                    <button
                      onClick={stopRegister}
                      disabled={regStopping || regStatus?.stop_requested}
                      className={`h-11 px-6 rounded-xl flex items-center justify-center gap-2 transition-all shadow-sm font-bold text-sm ${regStopping || regStatus?.stop_requested ? 'bg-neutral-300 text-neutral-500 cursor-not-allowed' : 'bg-red-600 text-white hover:bg-red-700'}`}
                    >
                      <span className="material-symbols-outlined text-sm">stop_circle</span>
                      <span>{regStopping ? t.register.stopping : regStatus?.stop_requested ? t.register.stopping : t.register.stop}</span>
                    </button>
                  ) : (
                    <button
                      onClick={startRegister}
                      disabled={regStarting}
                      className={`h-11 px-6 rounded-xl flex items-center justify-center gap-2 transition-all shadow-sm font-bold text-sm ${regStarting ? 'bg-neutral-300 text-neutral-500 cursor-not-allowed' : 'bg-ink text-white hover:bg-neutral-800'}`}
                    >
                      <span className="material-symbols-outlined text-sm">person_add</span>
                      <span>{regStarting ? t.register.starting : t.register.start}</span>
                    </button>
                  )}
                </div>
              </div>

              {regStatus?.verification && regStatus?.running && (
                <div className="p-4 bg-amber-50 border border-amber-200 rounded-2xl text-sm text-amber-800 flex items-center gap-2 animate-pulse">
                  <span className="material-symbols-outlined text-base">touch_app</span>
                  <span>{t.register.verifyHint}（{t.register.task} {regStatus.verification}）</span>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{t.register.statsLabel}</label>
                  <div className="mt-2 text-3xl font-bold text-ink">{regStatus?.stats?.total ?? 0}</div>
                </div>
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-emerald-600 uppercase opacity-80 tracking-wider">{t.register.success}</label>
                  <div className="mt-2 text-3xl font-bold text-emerald-600">{regStatus?.stats?.success ?? 0}</div>
                </div>
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-red-600 uppercase opacity-80 tracking-wider">{t.register.failed}</label>
                  <div className="mt-2 text-3xl font-bold text-red-600">{regStatus?.stats?.failed ?? 0}</div>
                </div>
                <div className="p-6 bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">
                  <label className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{lang === 'zh' ? '启动时间' : 'Started At'}</label>
                  <div className="mt-2 font-mono text-sm text-ink">{regStatus?.started_at ? new Date(regStatus.started_at * 1000).toLocaleTimeString() : '—'}</div>
                </div>
              </div>

              {(() => {
                const allTasks = { ...(regStatus?.active || {}), ...(regStatus?.recent || {}) }
                const entries = Object.entries(allTasks)
                if (entries.length === 0) {
                  return <div className="p-10 text-center text-sm text-body bg-white/60 backdrop-blur-md border border-hairline rounded-2xl">{t.register.noResult}</div>
                }
                return entries.map(([tid, task]) => {
                  const stageText = (t.register.stage as Record<string, string>)[task.stage] || task.stage
                  const isVerify = regStatus?.verification === tid
                  const isActive = !!regStatus?.active?.[tid]
                  return (
                    <div key={tid} className={`relative z-0 bg-white/80 backdrop-blur-xl border rounded-2xl overflow-hidden ${isVerify ? 'border-amber-400 ring-2 ring-amber-200' : 'border-hairline'}`}>
                      <div className="px-6 py-4 border-b border-hairline flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-semibold text-ink">{t.register.task} {tid}</span>
                          <span className={`px-2 py-1 rounded text-[11px] font-bold uppercase ${task.stage === 'success' ? 'bg-emerald-100 text-emerald-700' : task.stage === 'failed' ? 'bg-red-50 text-red-700' : task.stage === 'waiting_slider' ? 'bg-amber-100 text-amber-700' : 'bg-neutral-100 text-neutral-600'}`}>{stageText}</span>
                        </div>
                        <div className="flex items-center gap-2 text-xs text-body font-mono">
                          <span className={`h-2.5 w-2.5 rounded-full inline-block ${isActive ? (task.stage === 'success' ? 'bg-emerald-500' : task.stage === 'failed' ? 'bg-red-500' : 'bg-amber-400 animate-pulse') : 'bg-neutral-300'}`} />
                          <span>{task.started_at ? new Date(task.started_at * 1000).toLocaleTimeString() : ''}</span>
                        </div>
                      </div>
                      <div className="p-6 h-48 overflow-y-auto font-mono text-[13px] leading-relaxed text-ink opacity-80 space-y-1">
                        {task.logs.slice().reverse().map((line, i) => (
                          <div key={i} className={`break-all ${/FAILED|ERROR/i.test(line) ? 'text-red-600' : ''}`}>{line}</div>
                        ))}
                      </div>
                      {task.result && (
                        <div className="px-6 pb-6 pt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm border-t border-hairline">
                          {[
                            { label: lang === 'zh' ? '邮箱' : 'Email', value: task.result.email },
                            { label: lang === 'zh' ? '密码' : 'Password', value: task.result.password },
                            { label: lang === 'zh' ? '姓名' : 'Name', value: task.result.name },
                            { label: 'Token (dt-)', value: task.result.device.token },
                            { label: 'Refresh (drt-)', value: task.result.device.refresh_token },
                            { label: 'UID', value: task.result.device.user_id },
                          ].map((f, i) => (
                            <div key={i}>
                              <div className="text-[11px] font-semibold text-body uppercase opacity-60 tracking-wider">{f.label}</div>
                              <div className="mt-1 font-mono text-ink break-all">{f.value}</div>
                            </div>
                          ))}
                        </div>
                      )}
                      {task.error && (
                        <div className="px-6 pb-6 text-sm text-red-700">{task.error}</div>
                      )}
                    </div>
                  )
                })
              })()}
            </div>
          )}
        </div>
      </main>

      <ToastContainer toasts={toasts} dismiss={dismissToast} />
    </div>
  )
}
