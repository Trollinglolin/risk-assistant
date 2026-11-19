// Typed client for the FastAPI service (src/hkrisk/api/main.py).
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'
// Static build (GitHub Pages): no backend. Every response was pre-computed by
// scripts/export_static.py into public/static-data/<key>.json.
export const STATIC = import.meta.env.VITE_STATIC === '1'
const staticKey = (p: string) => p.replace(/[^A-Za-z0-9._-]/g, '_').replace(/^_+/, '')
const KEY_STORE = 'hkrisk-api-key'

export const PORTFOLIOS = [
  { value: 'core', label: 'Core 9' },
  { value: 'hsi', label: 'HSI 95' },
] as const
export type PortfolioId = (typeof PORTFOLIOS)[number]['value']

export const METHODS = ['historical', 'normal', 't', 'garch', 'evt'] as const
export type Method = (typeof METHODS)[number]

export const METHOD_LABEL: Record<Method, string> = {
  historical: 'Historical',
  normal: 'Normal',
  t: 'Student-t',
  garch: 'GARCH-FHS',
  evt: 'EVT (GPD)',
}

export const NAMES: Record<string, string> = {
  '0700.HK': 'Tencent',
  '3690.HK': 'Meituan',
  '0005.HK': 'HSBC',
  '0939.HK': 'CCB',
  '1299.HK': 'AIA',
  '0388.HK': 'HKEX',
  '0016.HK': 'SHK Properties',
  '0941.HK': 'China Mobile',
  '2800.HK': 'Tracker Fund',
}
const dynamicNames: Record<string, string> = {}
/** Remember display names the API sends (covers the 95 HSI names). */
export function rememberNames(positions: Position[]) {
  for (const p of positions) if (p.name) dynamicNames[p.ticker] = p.name
}
export const nameOf = (t: string) => NAMES[t] ?? dynamicNames[t] ?? t

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function getStoredKey(): string {
  try { return sessionStorage.getItem(KEY_STORE) ?? '' } catch { return '' }
}
export function setStoredKey(k: string) {
  try { sessionStorage.setItem(KEY_STORE, k) } catch { /* private mode */ }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(STATIC ? `${import.meta.env.BASE_URL}static-data/${staticKey(path)}.json` : BASE + path, init)
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch { /* not json */ }
    throw new ApiError(r.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return r.json() as Promise<T>
}

const qs = (o: Record<string, string | number | undefined>) =>
  '?' + Object.entries(o).filter(([, v]) => v !== undefined).map(([k, v]) => `${k}=${v}`).join('&')

export interface Position {
  ticker: string; name?: string; sector?: string | null; shares: number; price: number; value: number; weight: number
  history_proxied_before?: string | null
}
export interface Portfolio {
  portfolio: PortfolioId; label: string; as_of: string; currency: string; total_value: number
  n_positions: number; positions: Position[]
}
export interface Risk {
  method: Method; alpha: number; as_of: string; window: number; currency: string
  portfolio_value: number; var: number; es: number | null; var_pct: number; es_pct: number | null
}
export interface Compare {
  as_of: string; alpha: number; ranked_by_var_desc: { method: Method; var: number; es: number | null }[]
}
export interface Contributions {
  method: string; total: number
  components: { ticker: string; position_value: number; component: number; pct_of_total: number }[]
}
export interface ExplainChange {
  start_date: string; end_date: string; var_start: number; var_end: number; var_change: number
  price_position_effect: number; window_roll_effect: number
  position_deltas: { ticker: string; delta: number }[]
}
export interface Scenario { name: string; start: string; end: string; description: string; hsi_drawdown: number }
export interface StressResult {
  scenario?: string; total_pnl: number; total_pnl_pct: number; hsi_shock: number
  positions: { ticker: string; pnl: number; shock: number; proxied: boolean; beta: number | null }[]
}
export interface BacktestSummary {
  start: string; end: string; days: number; years: number; exceptions: number; expected: number
  kupiec_p: number; kupiec_pass: boolean; christoffersen_ind_p: number; christoffersen_cc_p: number
  christoffersen_cc_pass: boolean
  latest_250d: { zone: 'green' | 'yellow' | 'red'; count: number; multiplier: number }
}
export interface BacktestSeries { dates: string[]; var: number[]; loss: number[]; exception: boolean[] }
export interface ToolCall { name: string; input: Record<string, unknown>; output: unknown; is_error: boolean }
export interface AgentResult {
  question: string; answer: string; tool_calls: ToolCall[]; iterations: number
  input_tokens: number; output_tokens: number; latency_s: number; provider: string; model: string
}

export const examples = () =>
  fetch(`${import.meta.env.BASE_URL}static-data/agent_examples.json`).then((r) => r.json() as Promise<AgentResult[]>)

export const api = {
  portfolio: (pf: PortfolioId) => request<Portfolio>('/portfolio' + qs({ portfolio: pf })),
  risk: (pf: PortfolioId, method: Method, alpha: number) =>
    request<Risk>('/risk/var' + qs({ portfolio: pf, method, alpha })),
  compare: (pf: PortfolioId, alpha: number) => request<Compare>('/risk/compare' + qs({ portfolio: pf, alpha })),
  contributions: (pf: PortfolioId, method: 'historical' | 'normal', alpha: number) =>
    request<Contributions>('/risk/contributions' + qs({ portfolio: pf, method, alpha })),
  explain: (pf: PortfolioId, alpha: number) =>
    request<ExplainChange>('/risk/explain-change' + qs({ portfolio: pf, alpha })),
  scenarios: () => request<{ scenarios: Scenario[] }>('/stress/scenarios'),
  stress: (pf: PortfolioId, name: string) => request<StressResult>('/stress/' + encodeURIComponent(name) + qs({ portfolio: pf })),
  hsiShock: (pf: PortfolioId, shock: number) =>
    request<StressResult>('/stress/hsi-shock' + qs({ portfolio: pf, shock })),
  backtest: (pf: PortfolioId, method: Method, alpha: number) =>
    request<BacktestSummary>('/backtest' + qs({ portfolio: pf, method, alpha })),
  backtestSeries: (pf: PortfolioId, method: Method, alpha: number) =>
    request<BacktestSeries>('/backtest/series' + qs({ portfolio: pf, method, alpha })),
  ask: (question: string, pf: PortfolioId) => {
    const key = getStoredKey()
    return request<AgentResult>('/agent/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(key ? { 'X-API-Key': key } : {}) },
      body: JSON.stringify({ question, portfolio: pf }),
    })
  },
}

// ---------- formatting ----------
const hkd0 = new Intl.NumberFormat('en-HK', { maximumFractionDigits: 0 })
export const fmtHKD = (v: number | null | undefined) => (v == null ? 'n/a' : hkd0.format(Math.round(v)))
export const fmtSigned = (v: number) => (v > 0 ? '+' : v < 0 ? '-' : '') + hkd0.format(Math.abs(Math.round(v)))
export const fmtPct = (v: number | null | undefined, d = 2) => (v == null ? 'n/a' : (v * 100).toFixed(d) + '%')
export const fmtK = (v: number) =>
  Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(2) + 'm' : Math.abs(v) >= 1e3 ? Math.round(v / 1e3) + 'k' : String(Math.round(v))
