import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ModelVersion } from '../api'
import { fmtInt, get } from '../api'
import { ErrorBox, Loading, Section } from '../components/ui'
import { useFetch } from '../hooks'

const KEY_METRICS = ['pr_auc', 'roc_auc', 'precision', 'recall', 'f1', 'threshold', 'pr_auc_vs_sar_labels', 'roc_auc_vs_sar_labels',
  'precision_at_top_0.5%', 'recall_at_top_0.5%', 'precision_at_top_1.0%', 'recall_at_top_1.0%', 'base_rate']

export default function Models() {
  const { data, error } = useFetch(() => get<ModelVersion[]>('/api/v1/models'), [])
  const [sel, setSel] = useState<number | null>(null)
  if (error) return <ErrorBox error={error} />
  if (!data) return <Loading />
  const latest = data.filter(m => m.version === data[0]?.version)
  const m = data.find(x => x.id === sel) ?? latest.find(x => x.model_name === 'fraud_xgboost') ?? data[0]
  if (!m) return <p className="text-slate-500">No models registered yet. Run the training pipeline.</p>
  const cm = m.metrics.confusion_matrix as { tn: number; fp: number; fn: number; tp: number } | undefined
  const imp = Object.entries(m.feature_importance).slice(0, 15).map(([feature, v]) => ({ feature, v }))
  const td = m.training_data as Record<string, { rows: number; positives: number; from: string; to: string } | string | number>

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Model registry & evaluation</h1>
      <section className="card overflow-x-auto p-2">
        <table className="tbl w-full">
          <thead><tr><th>ID</th><th>Model</th><th>Algorithm</th><th>Version</th><th>Type</th><th className="text-right!">PR-AUC</th><th className="text-right!">ROC-AUC</th><th>Status</th></tr></thead>
          <tbody>{data.map(x => {
            const pr = (x.metrics.pr_auc ?? x.metrics.pr_auc_vs_sar_labels) as number
            const roc = (x.metrics.roc_auc ?? x.metrics.roc_auc_vs_sar_labels) as number
            return (
              <tr key={x.id} onClick={() => setSel(x.id)} className={`cursor-pointer ${x.id === m.id ? 'bg-blue-50!' : ''}`}>
                <td>{x.id}</td><td className="font-medium">{x.model_name}</td><td>{x.algorithm}</td><td className="text-slate-500">{x.version}</td><td>{x.model_type}</td>
                <td className="text-right tabular-nums">{pr?.toFixed(4)}</td><td className="text-right tabular-nums">{roc?.toFixed(4)}</td>
                <td>{x.is_active ? <span className="text-emerald-700">active</span> : <span className="text-slate-400">benchmark / inactive</span>}</td>
              </tr>)
          })}</tbody>
        </table>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Section title={`Test-set metrics · ${m.model_name}`}>
          <dl className="space-y-1 text-sm">
            {KEY_METRICS.filter(k => k in m.metrics).map(k => (
              <div key={k} className="flex justify-between"><dt className="text-slate-500">{k.replaceAll('_', ' ')}</dt><dd className="tabular-nums">{Number(m.metrics[k]).toFixed(4)}</dd></div>
            ))}
          </dl>
          {typeof m.metrics.note === 'string' && <p className="mt-2 text-xs text-slate-500">{m.metrics.note}</p>}
        </Section>
        <Section title="Confusion matrix (test set, chosen threshold)">
          {cm ? (
            <div className="grid grid-cols-[auto_1fr_1fr] gap-1 text-center text-sm">
              <div /><div className="text-xs text-slate-500">pred. normal</div><div className="text-xs text-slate-500">pred. suspicious</div>
              <div className="pr-2 text-right text-xs text-slate-500">actual normal</div>
              <div className="rounded bg-emerald-50 py-3 tabular-nums">{fmtInt(cm.tn)}</div><div className="rounded bg-amber-50 py-3 tabular-nums">{fmtInt(cm.fp)}</div>
              <div className="pr-2 text-right text-xs text-slate-500">actual SAR</div>
              <div className="rounded bg-red-50 py-3 tabular-nums">{fmtInt(cm.fn)}</div><div className="rounded bg-emerald-50 py-3 tabular-nums">{fmtInt(cm.tp)}</div>
            </div>
          ) : <p className="text-sm text-slate-500">Unsupervised model - evaluated with ranking metrics only.</p>}
        </Section>
        <Section title="Training data & split">
          <dl className="space-y-1 text-sm">
            {(['train', 'validation', 'test'] as const).map(k => {
              const s = td[k] as { rows: number; positives: number; from: string; to: string }
              return s && <div key={k}><dt className="font-medium capitalize">{k}</dt><dd className="text-xs text-slate-600">{fmtInt(s.rows)} rows · {s.positives} SAR · {s.from.slice(0, 10)} to {s.to.slice(0, 10)}</dd></div>
            })}
            <div className="pt-1 text-xs text-slate-500">{String(td.split)} · snapshot {String(td.feature_snapshot_hash)}</div>
          </dl>
        </Section>
      </div>

      {imp.length > 0 && (
        <Section title={`Feature importance · ${m.model_name}`}>
          <div style={{ height: imp.length * 26 + 30 }}>
            <ResponsiveContainer>
              <BarChart data={imp} layout="vertical" margin={{ left: 80, right: 16 }}>
                <CartesianGrid stroke="#e2e8f0" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} />
                <YAxis type="category" dataKey="feature" tick={{ fontSize: 11, fill: '#334155' }} width={170} />
                <Tooltip />
                <Bar dataKey="v" name="importance" fill="#2563eb" radius={[0, 4, 4, 0]} barSize={14} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Section>
      )}
      <Section title="Hyperparameters">
        <pre className="overflow-x-auto text-xs text-slate-700">{JSON.stringify(m.hyperparameters, null, 2)}</pre>
      </Section>
    </div>
  )
}
