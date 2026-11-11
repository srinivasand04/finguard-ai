import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CustomerDetail, Page, Transaction } from '../api'
import { fmtInt, fmtMoney, get, pct } from '../api'
import { Badge, Disclaimer, ErrorBox, Loading, Pager, Section, Stat, TxTable } from '../components/ui'
import { useFetch } from '../hooks'

type Counterparty = { customer_id: string; name: string | null; risk_level: string | null; out_count: number; out_total: number; in_count: number; in_total: number }
type Velocity = {
  as_of: string
  windows: Record<string, { outgoing: { count: number; total: number }; incoming: { count: number; total: number } }>
  daily: { date: string; out_count: number; in_count: number; out_total: number; in_total: number; high_risk: number }[]
}

const PROFILE_LABELS: [string, string, (v: number) => string][] = [
  ['tx_out_count', 'Outgoing transactions', fmtInt],
  ['tx_in_count', 'Incoming transactions', fmtInt],
  ['total_out', 'Total sent', v => fmtMoney(v, 0)],
  ['total_in', 'Total received', v => fmtMoney(v, 0)],
  ['avg_out_amount', 'Average outgoing amount', v => fmtMoney(v)],
  ['distinct_counterparties', 'Distinct counterparties', fmtInt],
  ['new_counterparties_30d', 'New counterparties (30d)', fmtInt],
  ['volume_change_ratio', 'Last 30d vs monthly baseline', v => `${v.toFixed(2)}x`],
  ['pass_through_ratio', 'Sent / received', v => v.toFixed(2)],
  ['cross_border_share', 'Cross-border share', v => pct(v)],
  ['high_risk_country_share', 'Elevated-risk jurisdiction share', v => pct(v)],
  ['night_tx_share', 'Night-time share (00-05h)', v => pct(v)],
  ['near_threshold_count', 'Amounts just below 10k', fmtInt],
  ['high_risk_tx_count', 'High-risk transactions', fmtInt],
  ['max_fraud_probability', 'Peak ML probability', v => v.toFixed(3)],
]

export default function CustomerPage() {
  const { id } = useParams()
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState('risk_desc')
  const [account, setAccount] = useState<string | null>(null)
  const c = useFetch(() => get<CustomerDetail>(`/api/v1/customers/${id}`), [id])
  const tx = useFetch(() => get<Page<Transaction>>(`/api/v1/customers/${id}/transactions`, { page, size: 15, sort }), [id, page, sort])
  const cps = useFetch(() => get<{ counterparties: Counterparty[] }>(`/api/v1/customers/${id}/counterparties`, { limit: 10 }), [id])
  const acc = account ?? c.data?.accounts[0]?.account_id
  const vel = useFetch(() => acc ? get<Velocity>(`/api/v1/accounts/${acc}/velocity`, { days: 90 }) : Promise.resolve(null), [acc])

  if (c.error) return <ErrorBox error={c.error} />
  if (!c.data) return <Loading />
  const d = c.data
  const r = d.risk

  return (
    <div className="space-y-4">
      <div>
        <Link to="/customers" className="text-sm text-blue-600 hover:underline">← Customers</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900">{d.full_name}</h1>
          <span className="text-sm text-slate-500">{d.customer_id}</span>
          <Badge value={d.risk_level} />
          {d.pep_flag && <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">PEP</span>}
        </div>
        <p className="text-sm text-slate-500">{d.segment} · {d.occupation} · {d.country} · KYC {d.kyc_level} · customer since {d.onboarding_date}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Customer risk score" value={r ? r.risk_score.toFixed(0) : '-'} sub={r ? `${r.indicators.length} indicators · ${r.scoring_version}` : undefined} />
        <Stat label="Accounts" value={d.accounts.length} />
        <Stat label="Alerts" value={<Link className="text-blue-600 hover:underline" to={`/alerts?customer_id=${d.customer_id}`}>{d.alert_count}</Link>} />
        <Stat label="Transactions" value={tx.data ? fmtInt(tx.data.total) : '…'} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Risk indicators (why this score)">
          {r && r.indicators.length > 0 ? (
            <ul className="divide-y divide-slate-100">
              {r.indicators.map(i => (
                <li key={i.code} className="flex items-start justify-between gap-3 py-2 text-sm">
                  <div>
                    <div className="font-medium text-slate-800">{i.label}</div>
                    <div className="text-xs text-slate-500">observed {typeof i.value === 'number' ? +i.value.toFixed(3) : String(i.value)} · threshold {JSON.stringify(i.threshold)}</div>
                  </div>
                  <span className="shrink-0 rounded bg-slate-100 px-2 py-0.5 text-xs tabular-nums text-slate-700">+{i.weight}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-slate-500">No risk indicators triggered.</p>}
        </Section>
        <Section title="Behavioural profile">
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
            {PROFILE_LABELS.map(([k, label, f]) => {
              const v = r?.profile[k]
              return (
                <div key={k} className="flex justify-between gap-2 border-b border-slate-50 py-0.5">
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="tabular-nums">{typeof v === 'number' ? f(v) : '-'}</dd>
                </div>
              )
            })}
          </dl>
        </Section>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Section title="Account velocity (last 90 days)" className="xl:col-span-2"
          right={<select className="input py-1! text-xs" value={acc ?? ''} onChange={e => setAccount(e.target.value)}>
            {d.accounts.map(a => <option key={a.account_id} value={a.account_id}>{a.account_id} · {a.account_type}</option>)}
          </select>}>
          {vel.data && <>
            <div className="mb-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
              {Object.entries(vel.data.windows).map(([w, v]) => (
                <div key={w} className="rounded-md bg-slate-50 px-2 py-1.5">
                  <div className="font-medium text-slate-600">{w}</div>
                  <div className="tabular-nums">out {v.outgoing.count} · {fmtMoney(v.outgoing.total, 0)}</div>
                  <div className="tabular-nums text-emerald-700">in {v.incoming.count} · {fmtMoney(v.incoming.total, 0)}</div>
                </div>
              ))}
            </div>
            <div className="h-48">
              <ResponsiveContainer>
                <BarChart data={vel.data.daily} margin={{ left: -20 }}>
                  <CartesianGrid stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748b' }} minTickGap={30} />
                  <YAxis tick={{ fontSize: 11, fill: '#64748b' }} allowDecimals={false} />
                  <Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="out_count" name="Outgoing" fill="#2563eb" />
                  <Bar dataKey="in_count" name="Incoming" fill="#10b981" />
                  <Bar dataKey="high_risk" name="High risk" fill="#dc2626" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-1 text-xs text-slate-500">Windows anchored at the latest transaction in the dataset ({vel.data.as_of?.slice(0, 10)}).</p>
          </>}
        </Section>
        <Section title="Top counterparties">
          <ul className="divide-y divide-slate-100 text-sm">
            {cps.data?.counterparties.map(cp => (
              <li key={cp.customer_id} className="flex items-center justify-between gap-2 py-1.5">
                <div className="min-w-0">
                  <Link className="text-blue-600 hover:underline" to={`/customers/${cp.customer_id}`}>{cp.customer_id}</Link>
                  <div className="truncate text-xs text-slate-500">{cp.name}</div>
                </div>
                <div className="text-right text-xs tabular-nums">
                  {cp.out_total > 0 && <div>sent {fmtMoney(cp.out_total, 0)}</div>}
                  {cp.in_total > 0 && <div className="text-emerald-700">recv {fmtMoney(cp.in_total, 0)}</div>}
                </div>
                <Badge value={cp.risk_level} />
              </li>
            ))}
          </ul>
        </Section>
      </div>

      <Section title="Transaction history" right={
        <select className="input py-1! text-xs" value={sort} onChange={e => { setSort(e.target.value); setPage(1) }}>
          <option value="risk_desc">Highest risk</option><option value="timestamp_desc">Newest</option><option value="amount_desc">Largest</option>
        </select>}>
        {tx.data ? <>
          <TxTable items={tx.data.items} perspective={d.customer_id} />
          <Pager page={page} size={tx.data.size} total={tx.data.total} onPage={setPage} />
        </> : <Loading />}
      </Section>

      <Section title="Accounts">
        <table className="tbl w-full">
          <thead><tr><th>Account</th><th>Type</th><th>Country</th><th>Bank</th><th>Opened</th><th className="text-right!">Opening balance</th></tr></thead>
          <tbody>{d.accounts.map(a => (
            <tr key={a.account_id}><td>{a.account_id}</td><td>{a.account_type}</td><td>{a.country}</td><td>{a.bank_id}</td><td>{a.opened_date}</td><td className="text-right tabular-nums">{fmtMoney(a.initial_balance)}</td></tr>
          ))}</tbody>
        </table>
      </Section>
      <Disclaimer text={r?.disclaimer} />
    </div>
  )
}
