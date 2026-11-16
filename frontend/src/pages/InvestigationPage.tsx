import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fmtDate, get, post } from '../api'
import { useAuth } from '../auth'
import { Disclaimer, ErrorBox, Loading, Section, Stat } from '../components/ui'
import { recLabel, StatusPill, type Case } from './Investigations'

type Step = { step: number; agent: string; status: string; attempts: number; duration_ms: number; llm_model: string | null
  error: string | null; evidence_refs: string[]; tool_calls: { tool: string; outcome: string; ms: number }[] }
type Ev = { ref: string; type: string; agent: string; title: string; source_table: string | null; source_id: string | null; ai_generated: boolean }
type Approval = { id: number; requested_by: string; request_comment: string | null; requested_at: string; decision: string
  decided_by: string | null; decision_comment: string | null; decided_at: string | null; overrides_ai: boolean | null }
type Detail = Case & { run_id: string | null; steps: Step[]; evidence: Ev[]; approvals: Approval[]
  report: null | { id: number; version: number; narrative_source: string; markdown: string; content: Record<string, any> } }

const AGENTS = ['supervisor', 'transaction', 'fraud_detection', 'customer_risk', 'graph_intelligence', 'compliance', 'investigation', 'reporting']
const AGENT_LABEL: Record<string, string> = { supervisor: 'Supervisor', transaction: 'Transaction', fraud_detection: 'Fraud detection',
  customer_risk: 'Customer risk', graph_intelligence: 'Graph intelligence', compliance: 'Compliance', investigation: 'Investigation', reporting: 'Reporting' }

function Cites({ text, onRef }: { text: string; onRef: (r: string) => void }) {
  return <>{text.split(/(\[E\d+\])/g).map((p, i) => {
    const m = p.match(/^\[(E\d+)\]$/)
    return m ? <button key={i} onClick={() => onRef(m[1])} className="mx-0.5 rounded bg-blue-100 px-1 text-xs font-medium text-blue-700 hover:bg-blue-200">{m[1]}</button> : <span key={i}>{p}</span>
  })}</>
}

export default function InvestigationPage() {
  const { id } = useParams()
  const { can, session } = useAuth()
  const [d, setD] = useState<Detail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const [hl, setHl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => get<Detail>(`/api/v1/investigations/${id}`).then(x => { setD(x); setErr(null) }).catch(e => setErr(String(e.message ?? e)))
  useEffect(() => { load() }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                     // poll while the agents are working
    if (!d || !['CREATED', 'RUNNING'].includes(d.status)) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [d?.status]) // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (path: string, body: unknown, ok: string) => {
    setBusy(true); setMsg(null)
    try { await post(path, body); setMsg(ok); setComment(''); await load() }
    catch (x) { setMsg(x instanceof Error ? x.message : String(x)) } finally { setBusy(false) }
  }
  const showRef = (r: string) => { setHl(r); document.getElementById(`ev-${r}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
  const download = () => {
    if (!d?.report) return
    const url = URL.createObjectURL(new Blob([d.report.markdown], { type: 'text/markdown' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `${d.case_ref}-report-v${d.report.version}.md` })
    a.click(); URL.revokeObjectURL(url)
  }

  if (err) return <ErrorBox error={err} />
  if (!d) return <Loading />
  const stepBy = Object.fromEntries(d.steps.map(s => [s.agent, s]))
  const r = d.report?.content
  const pending = d.approvals.find(a => a.decision === 'PENDING')
  const mine = session?.user.username === d.created_by || session?.user.username === pending?.requested_by

  return (
    <div className="space-y-4">
      <div>
        <Link to="/investigations" className="text-sm text-blue-600 hover:underline">← Investigations</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900">{d.case_ref}</h1><StatusPill s={d.status} />
          <Link className="text-sm text-blue-600 hover:underline" to={`/customers/${d.customer_id}`}>{d.customer_id} {d.customer_name}</Link>
        </div>
        <p className="text-sm text-slate-500">“{d.request_text}” · opened by {d.created_by} · {fmtDate(d.created_at)} · run {d.run_count}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Assessment score" value={d.assessment_score != null ? `${d.assessment_score.toFixed(0)}/100` : '…'} sub="rule-based, every signal cites evidence" />
        <Stat label="AI recommendation" value={<span className="text-base">{recLabel(d.recommendation)}</span>} sub="a recommendation, not a decision" />
        <Stat label="Evidence items" value={d.evidence.length} sub={`${d.evidence.filter(e => e.ai_generated).length} AI-generated`} />
        <Stat label="Report" value={d.report ? `v${d.report.version}` : '-'} sub={d.report ? `narrative: ${d.report.narrative_source}` : 'not yet generated'} />
      </div>

      <Section title="Agent workflow" right={d.status === 'RUNNING' || d.status === 'CREATED' ? <span className="text-xs text-blue-700">running… (auto-refresh)</span> : null}>
        <ol className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {AGENTS.map((a, i) => {
            const s = stepBy[a]
            const style = !s ? 'border-slate-200 bg-slate-50 text-slate-400' : s.status === 'SUCCEEDED' ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'
            return (
              <li key={a} className={`rounded-lg border p-2 text-xs ${style}`}>
                <div className="flex justify-between font-medium text-slate-800"><span>{i + 1}. {AGENT_LABEL[a]}</span>
                  <span>{s ? (s.status === 'SUCCEEDED' ? '✓' : '✗') : d.status === 'RUNNING' ? '…' : a === 'graph_intelligence' ? 'skipped' : ''}</span></div>
                {s && <>
                  <div className="text-slate-600">{s.duration_ms} ms{s.attempts > 1 ? ` · ${s.attempts} attempts` : ''}{s.llm_model ? ` · ${s.llm_model}` : ''}</div>
                  <div className="text-slate-500">{s.tool_calls.map(t => t.tool).join(', ') || 'no tool calls'}</div>
                  {s.evidence_refs.length > 0 && <div className="text-slate-500">evidence {s.evidence_refs[0]}{s.evidence_refs.length > 1 ? `–${s.evidence_refs.at(-1)}` : ''}</div>}
                  {s.error && <div className="text-red-700">{s.error}</div>}
                </>}
              </li>)
          })}
        </ol>
        {d.error && <p className="mt-2 text-sm text-red-700">{d.error}</p>}
      </Section>

      {r && (
        <div className="grid gap-4 xl:grid-cols-5">
          <Section title="Investigation summary" className="xl:col-span-3" right={<button className="btn-ghost text-xs" onClick={download}>Download report (.md)</button>}>
            <p className="text-sm leading-relaxed text-slate-800"><Cites text={r['1_summary'].text ?? ''} onRef={showRef} /></p>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">{r['1_summary'].key_findings.map((k: string, i: number) => <li key={i}><Cites text={k} onRef={showRef} /></li>)}</ul>
            {r['1_summary'].limitations.map((l: string) => <p key={l} className="mt-2 text-xs text-amber-700">{l}</p>)}
            <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Assessment signals</h3>
            <table className="tbl mt-1 w-full"><tbody>{r.assessment_signals.map((s: any, i: number) => (
              <tr key={i}><td className="w-12 text-right tabular-nums">+{s.points}</td><td className="whitespace-normal!">{s.signal}</td>
                <td>{s.evidence.map((e: string) => <button key={e} onClick={() => showRef(e)} className="mr-1 rounded bg-blue-100 px-1 text-xs text-blue-700">{e}</button>)}</td></tr>))}
              {r.assessment_signals.length === 0 && <tr><td className="text-slate-400">No risk signals</td></tr>}</tbody></table>
            <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Recommended next steps</h3>
            <ol className="mt-1 list-decimal pl-5 text-sm">{r['8_recommended_next_steps'].map((x: string) => <li key={x}>{x}</li>)}</ol>
          </Section>
          <Section title="Human review" className="xl:col-span-2">
            <div className="space-y-3 text-sm">
              {d.approvals.map(a => (
                <div key={a.id} className="rounded-md border border-slate-200 p-2 text-xs">
                  <div>Submitted by <b>{a.requested_by}</b> · {fmtDate(a.requested_at)}</div>
                  {a.request_comment && <div className="text-slate-600">“{a.request_comment}”</div>}
                  <div className="mt-1">Decision: <b>{a.decision.replaceAll('_', ' ').toLowerCase()}</b>{a.decided_by && ` by ${a.decided_by}`}
                    {a.overrides_ai && <span className="ml-1 rounded bg-amber-100 px-1 text-amber-800">overrides AI</span>}</div>
                  {a.decision_comment && <div className="text-slate-600">“{a.decision_comment}”</div>}
                </div>))}
              {can('submit_for_approval') && ['REPORT_READY', 'MORE_INFO_REQUESTED'].includes(d.status) && (
                <div className="space-y-2">
                  <textarea className="input w-full" rows={2} placeholder="Note for the reviewer (optional)" value={comment} onChange={e => setComment(e.target.value)} />
                  <div className="flex gap-2">
                    <button className="btn" disabled={busy} onClick={() => act(`/api/v1/investigations/${d.id}/submit`, { comment }, 'Submitted for approval')}>Submit for approval</button>
                    <button className="btn-ghost" disabled={busy} onClick={() => act(`/api/v1/investigations/${d.id}/run`, {}, 'Re-run started')}>Re-run agents</button>
                  </div>
                </div>)}
              {can('decide_investigation') && d.status === 'PENDING_APPROVAL' && (mine
                ? <p className="text-xs text-amber-700">Four-eyes rule: you cannot decide on a case you created or submitted.</p>
                : <div className="space-y-2">
                    <textarea className="input w-full" rows={3} placeholder="Decision rationale (required)" value={comment} onChange={e => setComment(e.target.value)} />
                    <div className="flex flex-wrap gap-2">
                      {[['ESCALATE', 'Escalate to MLRO'], ['APPROVE', 'Approve & close'], ['REQUEST_MORE_INFO', 'Request more info'], ['REJECT', 'Reject']].map(([k, l]) => (
                        <button key={k} className={k === 'ESCALATE' ? 'btn' : 'btn-ghost'} disabled={busy || comment.trim().length < 5}
                          onClick={() => act(`/api/v1/investigations/${d.id}/decision`, { decision: k, comment }, `Decision recorded: ${l}`)}>{l}</button>))}
                    </div>
                    <p className="text-xs text-slate-500">AI recommended: {recLabel(d.recommendation)}. A different decision is recorded as a human override.</p>
                  </div>)}
              {msg && <p className="text-xs text-slate-700">{msg}</p>}
            </div>
          </Section>
        </div>
      )}

      <Section title={`Evidence (${d.evidence.length})`}>
        <div className="overflow-x-auto">
          <table className="tbl w-full">
            <thead><tr><th>Ref</th><th>Type</th><th>Agent</th><th>Finding</th><th>Source</th></tr></thead>
            <tbody>{d.evidence.map(e => (
              <tr key={e.ref} id={`ev-${e.ref}`} className={hl === e.ref ? 'bg-blue-50!' : ''}>
                <td className="font-medium">{e.ref}</td><td className="text-xs">{e.type}{e.ai_generated && <span className="ml-1 rounded bg-purple-100 px-1 text-purple-800">AI</span>}</td>
                <td className="text-xs text-slate-500">{e.agent}</td>
                <td className="whitespace-normal! text-sm">{e.source_table === 'transactions' && e.source_id && /^\d+$/.test(e.source_id)
                  ? <Link className="text-blue-600 hover:underline" to={`/transactions/${e.source_id}`}>{e.title}</Link> : e.title}</td>
                <td className="text-xs text-slate-500">{e.source_table ?? '-'}{e.source_id ? `:${e.source_id}` : ''}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Section>
      <Disclaimer text="Agent findings are indicators gathered from synthetic data through audited tools. They are not a determination of wrongdoing; an Investigation Manager decides every case." />
    </div>
  )
}
