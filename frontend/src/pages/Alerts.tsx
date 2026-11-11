import { Link, useSearchParams } from 'react-router-dom'
import type { Alert, Page } from '../api'
import { fmtDate, get } from '../api'
import { Badge, Disclaimer, ErrorBox, Loading, Pager, Section } from '../components/ui'
import { useFetch } from '../hooks'

export default function Alerts() {
  const [sp, setSp] = useSearchParams()
  const page = Number(sp.get('page') ?? 1)
  const key = sp.toString()
  const { data, error, loading } = useFetch(() => get<Page<Alert>>('/api/v1/alerts', {
    alert_type: sp.get('type'), severity: sp.get('severity'), customer_id: sp.get('customer_id'), page, size: 25,
  }), [key])
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v); else n.delete(k)
    if (k !== 'page') n.delete('page')
    setSp(n)
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Alerts</h1>
      <Section title="Filters">
        <div className="flex flex-wrap gap-2">
          <select className="input" value={sp.get('type') ?? ''} onChange={e => set('type', e.target.value)}>
            <option value="">All types</option>
            <option value="HIGH_RISK_TRANSACTION">High-risk transaction (ML)</option>
            <option value="ANOMALOUS_TRANSACTION">Anomalous transaction</option>
            <option value="POSSIBLE_STRUCTURING">Possible structuring (rule)</option>
            <option value="HIGH_RISK_CUSTOMER">High-risk customer</option>
            <option value="CIRCULAR_FLOW">Circular flow (graph)</option>
            <option value="LAYERING_CHAIN">Layering chain (graph)</option>
            <option value="SUSPICIOUS_NETWORK">Suspicious network (graph)</option>
          </select>
          <select className="input" value={sp.get('severity') ?? ''} onChange={e => set('severity', e.target.value)}>
            <option value="">All severities</option><option value="CRITICAL">Critical</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option>
          </select>
          {sp.get('customer_id') && <button className="btn-ghost" onClick={() => set('customer_id', '')}>Customer {sp.get('customer_id')} ✕</button>}
        </div>
      </Section>
      {error && <ErrorBox error={error} />}
      {loading && !data ? <Loading /> : data && (
        <div className="space-y-2">
          {data.items.map(a => (
            <article key={a.id} className="card px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge value={a.severity} />
                  <span className="font-medium text-slate-800">{a.alert_type.replaceAll('_', ' ').toLowerCase()}</span>
                  <span className="text-xs text-slate-500">#{a.id} · {a.source} · {a.status}</span>
                </div>
                <span className="text-sm tabular-nums text-slate-600">score {a.score.toFixed(1)}</span>
              </div>
              <div className="mt-1 text-sm">
                <Link className="text-blue-600 hover:underline" to={`/customers/${a.customer_id}`}>{a.customer_id}</Link> <span className="text-slate-500">{a.customer_name}</span>
                {a.account_id && <span className="text-slate-400"> · {a.account_id}</span>}
                {a.transaction_id && <> · <Link className="text-blue-600 hover:underline" to={`/transactions/${a.transaction_id}`}>transaction {a.transaction_id}</Link></>}
                <span className="text-xs text-slate-400"> · raised {fmtDate(a.created_at)}</span>
              </div>
              <ul className="mt-1.5 list-disc pl-5 text-sm text-slate-600">
                {a.reasons.map((r, i) => <li key={i} className="break-words">{r}</li>)}
              </ul>
            </article>
          ))}
          <Pager page={page} size={data.size} total={data.total} onPage={p => set('page', String(p))} />
          <p className="text-xs text-slate-500">Alerts are read-only for now. Case creation, triage and approval workflows arrive in Phase 3.</p>
          <Disclaimer />
        </div>
      )}
    </div>
  )
}
