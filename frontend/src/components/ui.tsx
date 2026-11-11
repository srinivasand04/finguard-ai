import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Transaction } from '../api'
import { fmtDate, fmtMoney } from '../api'

const BAND_STYLE: Record<string, string> = {
  LOW: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  MEDIUM: 'bg-amber-50 text-amber-800 ring-amber-600/20',
  HIGH: 'bg-red-50 text-red-700 ring-red-600/20',
  CRITICAL: 'bg-red-600 text-white ring-red-700',
}

export function Badge({ value, title }: { value: string | null | undefined; title?: string }) {
  if (!value) return <span className="text-slate-400">-</span>
  return (
    <span title={title} className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BAND_STYLE[value] ?? 'bg-slate-100 text-slate-700 ring-slate-500/20'}`}>
      {value}
    </span>
  )
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function Section({ title, right, children, className = '' }: { title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-700">{title}</h2>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  )
}

export function Loading() {
  return <div className="p-6 text-sm text-slate-500">Loading…</div>
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
}

export function Disclaimer({ text }: { text?: string }) {
  return (
    <p className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-800">
      {text ?? 'Scores and alerts are investigative indicators on synthetic data - not determinations of fraud. Human review is required.'}
    </p>
  )
}

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className="flex items-center justify-between gap-2 pt-3 text-sm text-slate-600">
      <span>{total.toLocaleString()} results · page {page} of {pages.toLocaleString()}</span>
      <div className="flex gap-2">
        <button className="btn-ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <button className="btn-ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  )
}

export function TxTable({ items, perspective }: { items: Transaction[]; perspective?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="tbl w-full">
        <thead>
          <tr><th>ID</th><th>Time</th><th>From</th><th>To</th><th>Type</th><th>Category</th><th className="text-right!">Amount</th><th>Risk</th><th className="text-right!">ML prob.</th></tr>
        </thead>
        <tbody>
          {items.map(t => {
            const outgoing = perspective && t.sender_customer_id === perspective
            return (
              <tr key={t.transaction_id}>
                <td><Link className="text-blue-600 hover:underline" to={`/transactions/${t.transaction_id}`}>{t.transaction_id}</Link></td>
                <td className="text-slate-500">{fmtDate(t.timestamp)}</td>
                <td><Link className="hover:underline" to={`/customers/${t.sender_customer_id}`}>{t.sender_customer_id}</Link><span className="ml-1 text-xs text-slate-400">{t.sender_account_id}</span></td>
                <td><Link className="hover:underline" to={`/customers/${t.receiver_customer_id}`}>{t.receiver_customer_id}</Link><span className="ml-1 text-xs text-slate-400">{t.receiver_account_id}</span></td>
                <td>{t.tx_type}{t.is_cross_border && <span title="Cross-border" className="ml-1 rounded bg-slate-100 px-1 text-[10px] text-slate-600">XB</span>}</td>
                <td className="text-slate-500">{t.category.replaceAll('_', ' ').toLowerCase()}</td>
                <td className={`text-right tabular-nums ${perspective ? (outgoing ? 'text-slate-900' : 'text-emerald-700') : ''}`}>
                  {perspective && (outgoing ? '−' : '+')}{fmtMoney(t.amount)}
                </td>
                <td><Badge value={t.risk_band} title={t.risk_score != null ? `risk score ${t.risk_score}` : undefined} /></td>
                <td className="text-right tabular-nums text-slate-600">{t.fraud_probability != null ? t.fraud_probability.toFixed(3) : '-'}</td>
              </tr>
            )
          })}
          {items.length === 0 && <tr><td colSpan={9} className="py-6 text-center text-slate-400">No transactions match these filters</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

export function FactorList({ factors }: { factors: { description: string; contribution: number }[] }) {
  const max = Math.max(...factors.map(f => Math.abs(f.contribution)), 1e-6)
  return (
    <ul className="space-y-2">
      {factors.map((f, i) => (
        <li key={i}>
          <div className="flex justify-between gap-3 text-sm"><span>{f.description}</span><span className="tabular-nums text-slate-500">+{f.contribution.toFixed(2)}</span></div>
          <div className="mt-1 h-1.5 rounded bg-slate-100"><div className="h-1.5 rounded bg-red-400" style={{ width: `${(Math.abs(f.contribution) / max) * 100}%` }} /></div>
        </li>
      ))}
      {factors.length === 0 && <li className="text-sm text-slate-500">No factor pushed this score upward.</li>}
    </ul>
  )
}
