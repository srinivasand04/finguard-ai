import { Link, useParams } from 'react-router-dom'
import type { TransactionDetail } from '../api'
import { fmtDate, fmtMoney, get, pct } from '../api'
import { Badge, Disclaimer, ErrorBox, FactorList, Loading, Section, Stat } from '../components/ui'
import { useFetch } from '../hooks'

export default function TransactionPage() {
  const { id } = useParams()
  const { data: t, error } = useFetch(() => get<TransactionDetail>(`/api/v1/transactions/${id}`), [id])
  if (error) return <ErrorBox error={error} />
  if (!t) return <Loading />
  const p = t.prediction
  return (
    <div className="space-y-4">
      <div>
        <Link to="/transactions" className="text-sm text-blue-600 hover:underline">← Transactions</Link>
        <h1 className="mt-1 text-xl font-semibold text-slate-900">Transaction {t.transaction_id}</h1>
        <p className="text-sm text-slate-500">{fmtDate(t.timestamp)} · {t.tx_type} · {t.category.replaceAll('_', ' ').toLowerCase()}{t.is_cross_border && ' · cross-border'}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Amount" value={fmtMoney(t.amount)} sub={t.currency} />
        <Stat label="Risk score" value={p ? p.risk_score.toFixed(1) : '-'} sub={<Badge value={p?.risk_band} />} />
        <Stat label="ML suspicion probability" value={p ? p.fraud_probability.toFixed(3) : '-'} sub="XGBoost (supervised)" />
        <Stat label="Anomaly percentile" value={p?.anomaly_score != null ? pct(p.anomaly_score) : '-'} sub="Isolation Forest (unsupervised)" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Parties">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-slate-500">Sender</dt>
            <dd><Link className="text-blue-600 hover:underline" to={`/customers/${t.sender_customer_id}`}>{t.sender_customer_id}</Link> {t.sender_name} <span className="text-slate-400">({t.sender_account_id})</span></dd>
            <dt className="text-slate-500">Receiver</dt>
            <dd><Link className="text-blue-600 hover:underline" to={`/customers/${t.receiver_customer_id}`}>{t.receiver_customer_id}</Link> {t.receiver_name} <span className="text-slate-400">({t.receiver_account_id})</span></dd>
            <dt className="text-slate-500">Model version</dt><dd>{p ? <Link className="text-blue-600 hover:underline" to="/models">#{p.model_version_id}</Link> : '-'}</dd>
          </dl>
        </Section>
        <Section title="Why the model scored it this way">
          {p ? <FactorList factors={p.top_factors} /> : <p className="text-sm text-slate-500">Not scored yet.</p>}
          <p className="mt-3 text-xs text-slate-500">Per-feature contributions (log-odds) from the XGBoost model. Positive values raise the score.</p>
        </Section>
      </div>
      <Disclaimer text={t.disclaimer} />
    </div>
  )
}
