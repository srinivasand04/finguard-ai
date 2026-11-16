import { useState } from 'react'
import { Link } from 'react-router-dom'
import { fmtDate, get } from '../api'
import { ErrorBox, Loading, Pager, Section, Stat } from '../components/ui'
import { useFetch } from '../hooks'

type Metrics = {
  investigations_by_status: Record<string, number>; ai_recommendations: Record<string, number>
  human_decisions: Record<string, number>; override_rate: number | null; decisions_total: number
  narratives_by_llm_share: number | null; tool_calls: Record<string, number>
  active_models: { name: string; version: string; pr_auc: number }[]
  rag_evaluation: { retrieval: Record<string, Record<string, number>>; answers: Record<string, number | string> } | null
  graph_evaluation: { patterns: Record<string, { found: number; precision: number | null }>; networks: Record<string, unknown> } | null
  agent_evaluation: Record<string, unknown> | null; langfuse_enabled: boolean
}
type Runs = { per_agent: { agent: string; steps: number; success_rate: number; avg_ms: number; max_ms: number; retries: number }[]
  recent: { investigation_id: number; run_id: string; agent: string; status: string; duration_ms: number; tools: string[]; error: string | null; started_at: string }[] }
type Approval = { approval_id: number; investigation_id: number; case_ref: string; customer_id: string; recommendation: string | null
  requested_by: string; requested_at: string; decision: string; decided_by: string | null; overrides_ai: boolean | null }
type Audit = { id: number; actor: string; action: string; entity_type: string | null; entity_id: string | null; details: Record<string, unknown>; created_at: string }

const kv = (o: Record<string, number> | undefined) => Object.entries(o ?? {}).map(([k, v]) => `${k.replaceAll('_', ' ').toLowerCase()}: ${v}`).join(' · ') || '-'

export default function Governance() {
  const m = useFetch(() => get<Metrics>('/api/v1/governance/ai-metrics'), [])
  const runs = useFetch(() => get<Runs>('/api/v1/governance/agent-runs', { limit: 30 }), [])
  const queue = useFetch(() => get<Approval[]>('/api/v1/approvals', { decision: '' }), [])
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const audit = useFetch(() => get<{ items: Audit[]; total: number; size: number }>('/api/v1/audit-logs', { action, page, size: 25 }), [action, page])

  if (m.error) return <ErrorBox error={m.error} />
  if (!m.data) return <Loading />
  const d = m.data
  const ae = d.agent_evaluation as Record<string, number | null> | null

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Audit & AI governance</h1>
        <p className="text-sm text-slate-500">Who did what, how the agents behaved, and how often humans disagreed with the AI.
          Langfuse tracing: {d.langfuse_enabled ? 'enabled' : 'off (set LANGFUSE_* keys)'} · Prometheus metrics at <code>/metrics</code>.</p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Human decisions" value={d.decisions_total} sub={kv(d.human_decisions)} />
        <Stat label="Human override rate" value={d.override_rate != null ? `${(d.override_rate * 100).toFixed(0)}%` : '-'} sub="decision ≠ AI recommendation" />
        <Stat label="LLM-written narratives" value={d.narratives_by_llm_share != null ? `${(d.narratives_by_llm_share * 100).toFixed(0)}%` : '-'} sub="rest use the verified template" />
        <Stat label="Agent workflow eval" value={ae?.completion_rate != null ? `${((ae.completion_rate as number) * 100).toFixed(0)}% complete` : '-'}
          sub={ae ? `attention precision ${ae.needs_attention_precision ?? '-'} · recall ${ae.needs_attention_recall ?? '-'}` : 'run app.cli agent-eval'} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Agents (all runs)">
          <table className="tbl w-full">
            <thead><tr><th>Agent</th><th className="text-right!">Steps</th><th className="text-right!">Success</th><th className="text-right!">Avg ms</th><th className="text-right!">Retries</th></tr></thead>
            <tbody>{runs.data?.per_agent.map(a => (
              <tr key={a.agent}><td>{a.agent}</td><td className="text-right tabular-nums">{a.steps}</td>
                <td className={`text-right tabular-nums ${a.success_rate < 1 ? 'text-amber-700' : ''}`}>{(a.success_rate * 100).toFixed(0)}%</td>
                <td className="text-right tabular-nums">{a.avg_ms}</td><td className="text-right tabular-nums">{a.retries}</td></tr>))}</tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">Investigations: {kv(d.investigations_by_status)}</p>
          <p className="text-xs text-slate-500">AI recommendations: {kv(d.ai_recommendations)}</p>
        </Section>
        <Section title="Model & retrieval quality">
          <dl className="space-y-1 text-sm">
            {d.active_models.map(x => <div key={x.name} className="flex justify-between"><dt>{x.name}</dt><dd className="tabular-nums">PR-AUC {x.pr_auc?.toFixed(3)}</dd></div>)}
            {d.graph_evaluation && Object.entries(d.graph_evaluation.patterns).map(([k, v]) =>
              <div key={k} className="flex justify-between"><dt>graph {k.toLowerCase()}</dt><dd className="tabular-nums">{v.found} found · precision {v.precision ?? '-'}</dd></div>)}
            {d.rag_evaluation && <>
              <div className="flex justify-between"><dt>RAG hybrid+rerank</dt><dd className="tabular-nums">hit@1 {d.rag_evaluation.retrieval['hybrid+rerank']?.['hit@1'] ?? '-'}</dd></div>
              <div className="flex justify-between"><dt>RAG answers ({String(d.rag_evaluation.answers.model ?? '-')})</dt>
                <dd className="tabular-nums">fact recall {String(d.rag_evaluation.answers.fact_recall ?? '-')} · faithfulness {String(d.rag_evaluation.answers.faithfulness_proxy ?? '-')}</dd></div>
            </>}
          </dl>
          <p className="mt-2 text-xs text-slate-500">Tool calls: {kv(d.tool_calls)}</p>
        </Section>
      </div>

      <Section title="Approval queue & decisions">
        <table className="tbl w-full">
          <thead><tr><th>Case</th><th>Customer</th><th>AI recommendation</th><th>Submitted by</th><th>Decision</th><th>Decided by</th></tr></thead>
          <tbody>{queue.data?.map(a => (
            <tr key={a.approval_id}>
              <td><Link className="text-blue-600 hover:underline" to={`/investigations/${a.investigation_id}`}>{a.case_ref}</Link></td>
              <td>{a.customer_id}</td><td>{(a.recommendation ?? '-').replaceAll('_', ' ').toLowerCase()}</td>
              <td>{a.requested_by} <span className="text-xs text-slate-400">{fmtDate(a.requested_at)}</span></td>
              <td>{a.decision.replaceAll('_', ' ').toLowerCase()}{a.overrides_ai && <span className="ml-1 rounded bg-amber-100 px-1 text-xs text-amber-800">override</span>}</td>
              <td>{a.decided_by ?? '-'}</td></tr>))}
            {queue.data?.length === 0 && <tr><td colSpan={6} className="py-4 text-center text-slate-400">Nothing submitted yet</td></tr>}</tbody>
        </table>
      </Section>

      <Section title="Audit trail" right={
        <select className="input py-1! text-xs" value={action} onChange={e => { setAction(e.target.value); setPage(1) }}>
          {['', 'LOGIN_SUCCEEDED', 'LOGIN_FAILED', 'CUSTOMER_PROFILE_VIEWED', 'TOOL_CALL', 'INVESTIGATION_CREATED', 'INVESTIGATION_RUN_FINISHED',
            'SUBMITTED_FOR_APPROVAL', 'INVESTIGATION_ESCALATE', 'INVESTIGATION_APPROVE', 'COMPLIANCE_QUESTION', 'USER_CREATED', 'USER_UPDATED']
            .map(a => <option key={a} value={a}>{a || 'All actions'}</option>)}
        </select>}>
        {audit.data && <>
          <div className="overflow-x-auto">
            <table className="tbl w-full">
              <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
              <tbody>{audit.data.items.map(a => (
                <tr key={a.id}><td className="text-xs text-slate-500">{fmtDate(a.created_at)}</td><td>{a.actor}</td><td className="text-xs">{a.action}</td>
                  <td className="text-xs">{a.entity_type}{a.entity_id ? `:${a.entity_id}` : ''}</td>
                  <td className="max-w-md truncate text-xs text-slate-500" title={JSON.stringify(a.details)}>{JSON.stringify(a.details)}</td></tr>))}</tbody>
            </table>
          </div>
          <Pager page={page} size={audit.data.size} total={audit.data.total} onPage={setPage} />
        </>}
      </Section>
    </div>
  )
}
