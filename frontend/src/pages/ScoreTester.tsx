import { useEffect, useState } from 'react'
import type { Page, ScoreResult, Transaction } from '../api'
import { get, post } from '../api'
import { Badge, Disclaimer, ErrorBox, FactorList, Section, Stat } from '../components/ui'

export default function ScoreTester() {
  const [form, setForm] = useState({ sender_account_id: '', receiver_account_id: '', amount: '9500', tx_type: 'WIRE', timestamp: '2026-06-30T02:15' })
  const [res, setRes] = useState<ScoreResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Prefill with the account pair of the highest-risk stored transaction, so the example is always valid
  useEffect(() => {
    get<Page<Transaction>>('/api/v1/transactions', { sort: 'risk_desc', size: 1 }).then(p => {
      const t = p.items[0]
      if (t) setForm(f => ({ ...f, sender_account_id: t.sender_account_id, receiver_account_id: t.receiver_account_id }))
    }).catch(() => { /* form stays empty; user can type IDs */ })
  }, [])
  const upd = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    if (!form.sender_account_id.trim() || !form.receiver_account_id.trim()) return setErr('Enter both account IDs')
    if (!(Number(form.amount) > 0)) return setErr('Amount must be greater than 0')
    setBusy(true)
    try {
      setRes(await post<ScoreResult>('/api/v1/transactions/score', { ...form, amount: Number(form.amount), timestamp: `${form.timestamp}:00` }))
    } catch (x) {
      setRes(null); setErr(x instanceof Error ? x.message : String(x))
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Near-real-time scoring</h1>
        <p className="text-sm text-slate-500">Scores a hypothetical transaction against the stored history of both accounts, using the same feature pipeline as batch scoring. Nothing is saved except an audit-log entry.</p>
      </div>
      <Section title="Transaction">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">Sender account<input className="input w-36" value={form.sender_account_id} onChange={upd('sender_account_id')} /></label>
          <label className="flex flex-col gap-1">Receiver account<input className="input w-36" value={form.receiver_account_id} onChange={upd('receiver_account_id')} /></label>
          <label className="flex flex-col gap-1">Amount (EUR)<input className="input w-32" type="number" step="0.01" min="0.01" value={form.amount} onChange={upd('amount')} /></label>
          <label className="flex flex-col gap-1">Type
            <select className="input" value={form.tx_type} onChange={upd('tx_type')}><option>TRANSFER</option><option>PAYMENT</option><option>WIRE</option></select>
          </label>
          <label className="flex flex-col gap-1">Timestamp<input className="input" type="datetime-local" value={form.timestamp} onChange={upd('timestamp')} /></label>
          <button className="btn" disabled={busy}>{busy ? 'Scoring…' : 'Score transaction'}</button>
        </form>
        {err && <div className="mt-3"><ErrorBox error={err} /></div>}
      </Section>
      {res && <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="Risk score" value={res.risk_score.toFixed(1)} sub={<Badge value={res.risk_band} />} />
          <Stat label="ML suspicion probability" value={res.fraud_probability.toFixed(3)} sub={`model #${res.model_version_id}`} />
          <Stat label="Anomaly percentile" value={`${(res.anomaly_score * 100).toFixed(1)}%`} />
          <Stat label="Cross-border" value={res.is_cross_border ? 'Yes' : 'No'} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Section title="Top contributing factors"><FactorList factors={res.top_factors} /></Section>
          <Section title="Computed features">
            <dl className="grid grid-cols-1 gap-x-6 text-xs sm:grid-cols-2">
              {Object.entries(res.features).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-slate-50 py-0.5"><dt className="text-slate-500">{k}</dt><dd className="tabular-nums">{v}</dd></div>
              ))}
            </dl>
          </Section>
        </div>
        <Disclaimer text={res.disclaimer} />
      </>}
    </div>
  )
}
