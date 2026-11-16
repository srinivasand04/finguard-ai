import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { fmtDate, get, post } from '../api'
import { useAuth } from '../auth'
import { ErrorBox, Loading, Pager, Section } from '../components/ui'
import { useFetch } from '../hooks'

export type Case = {
  id: number; case_ref: string; customer_id: string; customer_name: string | null; title: string; request_text: string
  status: string; assessment_score: number | null; recommendation: string | null; created_by: string; run_count: number
  error: string | null; created_at: string; updated_at: string
}

export const STATUS_STYLE: Record<string, string> = {
  CREATED: 'bg-slate-100 text-slate-700', RUNNING: 'bg-blue-100 text-blue-800', REPORT_READY: 'bg-indigo-100 text-indigo-800',
  PENDING_APPROVAL: 'bg-amber-100 text-amber-800', MORE_INFO_REQUESTED: 'bg-amber-50 text-amber-800',
  APPROVED_CLOSED: 'bg-emerald-100 text-emerald-800', ESCALATED: 'bg-red-100 text-red-800', REJECTED: 'bg-slate-200 text-slate-700',
  FAILED: 'bg-red-50 text-red-700',
}
export const StatusPill = ({ s }: { s: string }) =>
  <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[s] ?? 'bg-slate-100'}`}>{s.replaceAll('_', ' ').toLowerCase()}</span>
export const recLabel = (r: string | null) => r ? r.replaceAll('_', ' ').toLowerCase() : '-'

export default function Investigations() {
  const { can } = useAuth()
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const page = Number(sp.get('page') ?? 1)
  const [req, setReq] = useState(sp.get('customer_id') ? `Investigate suspicious transactions involving customer ${sp.get('customer_id')}` : '')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const list = useFetch(() => get<{ items: Case[]; total: number; size: number }>('/api/v1/investigations',
    { status: sp.get('status'), page, size: 20 }), [sp.toString()])

  const start = async (e: React.FormEvent) => {
    e.preventDefault()
    if (req.trim().length < 5) return setErr('Describe the request and name a customer (e.g. CUST10025) or account')
    setBusy(true); setErr(null)
    try {
      const c = await post<Case>('/api/v1/investigations', { request_text: req.trim() })
      nav(`/investigations/${c.id}`)
    } catch (x) { setErr(x instanceof Error ? x.message : String(x)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Investigations</h1>
        <p className="text-sm text-slate-500">Eight LangGraph agents gather evidence through permissioned tools; a human decides every case.</p>
      </div>
      {can('run_investigation') && (
        <Section title="New investigation">
          <form onSubmit={start} className="flex flex-col gap-2 sm:flex-row">
            <input className="input flex-1" placeholder="Investigate suspicious transactions involving customer CUST10025"
              value={req} onChange={e => { setReq(e.target.value); setErr(null) }} />
            <button className="btn" disabled={busy}>{busy ? 'Starting…' : 'Start investigation'}</button>
          </form>
          {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
        </Section>
      )}
      <section className="card p-2">
        <div className="flex flex-wrap gap-2 px-2 py-2">
          {['', 'RUNNING', 'REPORT_READY', 'PENDING_APPROVAL', 'ESCALATED', 'APPROVED_CLOSED', 'FAILED'].map(s => (
            <button key={s} onClick={() => setSp(s ? { status: s } : {})}
              className={`rounded-full border px-3 py-1 text-xs ${(sp.get('status') ?? '') === s ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}>
              {s ? s.replaceAll('_', ' ').toLowerCase() : 'all'}</button>
          ))}
        </div>
        {list.error && <ErrorBox error={list.error} />}
        {!list.data ? <Loading /> : (
          <div className="overflow-x-auto">
            <table className="tbl w-full">
              <thead><tr><th>Case</th><th>Customer</th><th>Status</th><th className="text-right!">Score</th><th>AI recommendation</th><th>Created by</th><th>Created</th></tr></thead>
              <tbody>
                {list.data.items.map(c => (
                  <tr key={c.id}>
                    <td><Link className="text-blue-600 hover:underline" to={`/investigations/${c.id}`}>{c.case_ref}</Link></td>
                    <td><Link className="hover:underline" to={`/customers/${c.customer_id}`}>{c.customer_id}</Link> <span className="text-slate-500">{c.customer_name}</span></td>
                    <td><StatusPill s={c.status} /></td>
                    <td className="text-right tabular-nums">{c.assessment_score?.toFixed(0) ?? '-'}</td>
                    <td>{recLabel(c.recommendation)}</td><td className="text-slate-500">{c.created_by}</td>
                    <td className="text-slate-500">{fmtDate(c.created_at)}</td>
                  </tr>))}
                {list.data.items.length === 0 && <tr><td colSpan={7} className="py-6 text-center text-slate-400">No investigations yet</td></tr>}
              </tbody>
            </table>
            <div className="px-2 pb-1"><Pager page={page} size={list.data.size} total={list.data.total} onPage={p => setSp({ ...Object.fromEntries(sp), page: String(p) })} /></div>
          </div>
        )}
      </section>
    </div>
  )
}
