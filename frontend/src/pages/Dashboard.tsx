import { Link } from 'react-router-dom'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Alert, CustomerSummary, Page, Summary } from '../api'
import { fmtCompact, fmtInt, fmtMoney, get } from '../api'
import { Badge, Disclaimer, ErrorBox, Loading, Section, Stat } from '../components/ui'
import { useFetch } from '../hooks'

type Day = { date: string; count: number; volume: number; high: number; medium: number }
type Bucket = { bucket: string; transactions: number; customers: number }

const axis = { fontSize: 11, fill: '#64748b' }

export default function Dashboard() {
  const s = useFetch(() => get<Summary>('/api/v1/dashboard/summary'), [])
  const ts = useFetch(() => get<Day[]>('/api/v1/dashboard/timeseries'), [])
  const dist = useFetch(() => get<Bucket[]>('/api/v1/dashboard/risk-distribution'), [])
  const top = useFetch(() => get<Page<CustomerSummary>>('/api/v1/customers', { risk_level: 'HIGH', size: 8 }), [])
  const alerts = useFetch(() => get<Page<Alert>>('/api/v1/alerts', { size: 8 }), [])

  if (s.error) return <ErrorBox error={`Could not reach the API: ${s.error}. Is the backend running on port 8000?`} />
  if (!s.data) return <Loading />
  const d = s.data
  const highTx = d.transaction_risk_bands.HIGH ?? 0
  const xgb = d.active_models.find(m => m.name === 'fraud_xgboost')

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Transaction monitoring</h1>
          <p className="text-sm text-slate-500">{d.period.from.slice(0, 10)} to {d.period.to.slice(0, 10)} · synthetic AMLSim-format data</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Transactions" value={fmtCompact(d.transactions)} sub={`${fmtMoney(d.total_volume, 0)} total value`} />
        <Stat label="High-risk transactions" value={fmtInt(highTx)} sub={`${((highTx / d.transactions) * 100).toFixed(2)}% of volume · ${fmtInt(d.transaction_risk_bands.MEDIUM ?? 0)} medium`} />
        <Stat label="Open alerts" value={fmtInt(d.alerts.open)} sub={`${fmtInt(d.alerts.by_severity.CRITICAL ?? 0)} critical`} />
        <Stat label="High-risk customers" value={fmtInt(d.customer_risk_levels.HIGH ?? 0)} sub={`of ${fmtInt(d.customers)} customers · ${fmtInt(d.accounts)} accounts`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Daily transaction count">
          <div className="h-56">
            {ts.data && <ResponsiveContainer>
              <AreaChart data={ts.data} margin={{ left: -10, right: 8 }}>
                <CartesianGrid stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="date" tick={axis} minTickGap={40} />
                <YAxis tick={axis} />
                <Tooltip />
                <Area type="monotone" dataKey="count" name="Transactions" stroke="#2563eb" fill="#2563eb" fillOpacity={0.1} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>}
          </div>
        </Section>
        <Section title="Flagged transactions per day">
          <div className="h-56">
            {ts.data && <ResponsiveContainer>
              <BarChart data={ts.data} margin={{ left: -20, right: 8 }}>
                <CartesianGrid stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="date" tick={axis} minTickGap={40} />
                <YAxis tick={axis} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="high" name="High" stackId="a" fill="#dc2626" />
                <Bar dataKey="medium" name="Medium" stackId="a" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>}
          </div>
        </Section>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Section title="Customer risk score distribution">
          <div className="h-52">
            {dist.data && <ResponsiveContainer>
              <BarChart data={dist.data} margin={{ left: -20 }}>
                <CartesianGrid stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="bucket" tick={axis} interval={1} />
                <YAxis tick={axis} />
                <Tooltip />
                <Bar dataKey="customers" name="Customers" fill="#2563eb" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>}
          </div>
        </Section>
        <Section title="Alerts by type">
          <ul className="space-y-2 text-sm">
            {Object.entries(d.alerts.by_type).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <li key={k}>
                <div className="flex justify-between"><Link to={`/alerts?type=${k}`} className="hover:underline">{k.replaceAll('_', ' ').toLowerCase()}</Link><span className="tabular-nums">{fmtInt(v)}</span></div>
                <div className="mt-1 h-1.5 rounded bg-slate-100"><div className="h-1.5 rounded bg-blue-500" style={{ width: `${(v / d.alerts.total) * 100}%` }} /></div>
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Detection models (active)">
          <ul className="space-y-3 text-sm">
            {d.active_models.map(m => (
              <li key={m.id} className="flex justify-between gap-2">
                <div><div className="font-medium">{m.name}</div><div className="text-xs text-slate-500">{m.version}</div></div>
                <div className="text-right text-xs text-slate-600">PR-AUC <b className="tabular-nums">{m.pr_auc?.toFixed(3)}</b><br />ROC-AUC <b className="tabular-nums">{m.roc_auc?.toFixed(3)}</b></div>
              </li>
            ))}
          </ul>
          {xgb && <Link to="/models" className="mt-3 block text-sm text-blue-600 hover:underline">Model evaluation →</Link>}
        </Section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Highest-risk customers" right={<Link className="text-xs text-blue-600" to="/customers?risk_level=HIGH">View all</Link>}>
          <table className="tbl w-full">
            <thead><tr><th>Customer</th><th>Segment</th><th>Country</th><th className="text-right!">Score</th><th>Level</th></tr></thead>
            <tbody>{top.data?.items.map(c => (
              <tr key={c.customer_id}>
                <td><Link className="text-blue-600 hover:underline" to={`/customers/${c.customer_id}`}>{c.customer_id}</Link> <span className="text-slate-500">{c.full_name}</span></td>
                <td>{c.segment}</td><td>{c.country}</td>
                <td className="text-right tabular-nums">{c.risk_score}</td><td><Badge value={c.risk_level} /></td>
              </tr>))}</tbody>
          </table>
        </Section>
        <Section title="Top alerts" right={<Link className="text-xs text-blue-600" to="/alerts">View all</Link>}>
          <table className="tbl w-full">
            <thead><tr><th>Type</th><th>Customer</th><th className="text-right!">Score</th><th>Severity</th></tr></thead>
            <tbody>{alerts.data?.items.map(a => (
              <tr key={a.id}>
                <td>{a.transaction_id ? <Link className="text-blue-600 hover:underline" to={`/transactions/${a.transaction_id}`}>{a.alert_type.replaceAll('_', ' ').toLowerCase()}</Link> : a.alert_type.replaceAll('_', ' ').toLowerCase()}</td>
                <td><Link className="hover:underline" to={`/customers/${a.customer_id}`}>{a.customer_id}</Link></td>
                <td className="text-right tabular-nums">{a.score.toFixed(1)}</td><td><Badge value={a.severity} /></td>
              </tr>))}</tbody>
          </table>
        </Section>
      </div>

      <Section title="Volume by category">
        <div className="overflow-x-auto">
          <table className="tbl w-full">
            <thead><tr><th>Category</th><th className="text-right!">Transactions</th><th className="text-right!">Value</th></tr></thead>
            <tbody>{d.categories.map(c => (
              <tr key={c.category}><td>{c.category.replaceAll('_', ' ').toLowerCase()}</td><td className="text-right tabular-nums">{fmtInt(c.count)}</td><td className="text-right tabular-nums">{fmtMoney(c.total, 0)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Section>
      <Disclaimer text={d.disclaimer} />
    </div>
  )
}
