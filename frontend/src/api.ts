export type Band = 'LOW' | 'MEDIUM' | 'HIGH'

export interface Page<T> { items: T[]; total: number; page: number; size: number }

export interface Factor { feature: string; value: number; contribution: number; description: string }

export interface Transaction {
  transaction_id: number
  sender_account_id: string
  receiver_account_id: string
  sender_customer_id: string
  receiver_customer_id: string
  tx_type: string
  category: string
  amount: number
  currency: string
  timestamp: string
  is_cross_border: boolean
  risk_score: number | null
  risk_band: Band | null
  fraud_probability: number | null
  anomaly_score: number | null
}

export interface TransactionDetail extends Transaction {
  sender_name: string | null
  receiver_name: string | null
  disclaimer: string
  prediction: {
    fraud_probability: number; anomaly_score: number | null; risk_score: number; risk_band: Band
    top_factors: Factor[]; model_version_id: number
  } | null
}

export interface CustomerSummary {
  customer_id: string; full_name: string; segment: string; country: string; kyc_level: string
  pep_flag: boolean; onboarding_date: string; risk_score: number | null; risk_level: Band | null
}

export interface Indicator { code: string; label: string; metric: string; value: number | boolean | null; threshold: unknown; weight: number }

export interface CustomerRisk {
  customer_id: string; risk_score: number; risk_level: Band; indicators: Indicator[]
  profile: Record<string, number | boolean | null>; scoring_version: string; disclaimer: string
}

export interface Account {
  account_id: string; customer_id: string; account_type: string; country: string; bank_id: string
  initial_balance: number; opened_date: string | null
}

export interface CustomerDetail extends CustomerSummary {
  occupation: string | null; date_of_birth: string | null; accounts: Account[]; risk: CustomerRisk | null; alert_count: number
}

export interface Alert {
  id: number; alert_type: string; source: string; severity: 'MEDIUM' | 'HIGH' | 'CRITICAL'; status: string
  customer_id: string; account_id: string | null; transaction_id: number | null; score: number
  reasons: string[]; created_at: string; customer_name: string | null
}

export interface ModelVersion {
  id: number; model_name: string; version: string; model_type: string; algorithm: string; features: string[]
  hyperparameters: Record<string, unknown>; metrics: Record<string, unknown>; feature_importance: Record<string, number>
  training_data: Record<string, unknown>; is_active: boolean; created_at: string
}

export interface Summary {
  customers: number; accounts: number; transactions: number; total_volume: number
  period: { from: string; to: string }
  transaction_risk_bands: Record<string, number>
  customer_risk_levels: Record<string, number>
  alerts: { total: number; open: number; by_type: Record<string, number>; by_severity: Record<string, number> }
  categories: { category: string; count: number; total: number }[]
  active_models: { id: number; name: string; version: string; pr_auc: number; roc_auc: number }[]
  disclaimer: string
}

export interface ScoreResult {
  fraud_probability: number; anomaly_score: number; risk_score: number; risk_band: Band
  top_factors: Factor[]; features: Record<string, number>; model_version_id: number
  is_cross_border: boolean; disclaimer: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// --- auth token (sessionStorage: cleared when the browser tab closes; dev convenience, see docs/security.md)
const TOKEN_KEY = 'fg_token'
export const getToken = (): string | null => { try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null } }
export const setToken = (t: string | null) => {
  try { if (t) sessionStorage.setItem(TOKEN_KEY, t); else sessionStorage.removeItem(TOKEN_KEY) } catch { /* storage blocked */ }
}

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const t = getToken()
  return t ? { ...extra, Authorization: `Bearer ${t}` } : extra
}

async function handle<T>(r: Response): Promise<T> {
  if (r.status === 401 && getToken()) {          // expired / revoked session -> back to login
    setToken(null)
    if (!location.pathname.startsWith('/login')) location.assign(`/login?next=${encodeURIComponent(location.pathname)}`)
  }
  if (!r.ok) {
    let msg = r.statusText
    try {
      const body = await r.json()
      msg = typeof body.detail === 'string' ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.at(-1)}: ${d.msg}`).join('; ')
        : msg
    } catch { /* non-JSON error */ }
    throw new ApiError(r.status, msg)
  }
  return r.json() as Promise<T>
}

export function get<T>(path: string, params: Record<string, string | number | boolean | undefined | null> = {}): Promise<T> {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') qs.set(k, String(v)) })
  const q = qs.toString()
  return fetch(`${path}${q ? `?${q}` : ''}`, { headers: authHeaders() }).then(r => handle<T>(r))
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return fetch(path, { method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) })
    .then(r => handle<T>(r))
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return fetch(path, { method: 'PATCH', headers: authHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) })
    .then(r => handle<T>(r))
}

export async function login(username: string, password: string): Promise<Session> {
  const r = await fetch('/api/v1/auth/login', { method: 'POST', body: new URLSearchParams({ username, password }),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' } })
  const out = await handle<Session & { access_token: string }>(r)
  setToken(out.access_token)
  return { user: out.user, permissions: out.permissions }
}

export interface User { id: number; username: string; full_name: string; role: string; is_active: boolean; created_at: string; last_login_at: string | null }
export interface Session { user: User; permissions: string[] }

export const fmtMoney = (v: number, digits = 2) =>
  new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v)
export const fmtCompact = (v: number) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
export const fmtInt = (v: number) => new Intl.NumberFormat('en').format(v)
export const fmtDate = (s: string) => new Date(s).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
export const pct = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`
