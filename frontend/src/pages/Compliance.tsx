import { Fragment, useState } from 'react'
import { get, post } from '../api'
import { Disclaimer, ErrorBox, Loading, Section } from '../components/ui'
import { useFetch } from '../hooks'

type Source = { id: number; chunk_id: number; document_id: number; title: string; doc_type: string; section: string | null; page: number | null; text: string; scores: Record<string, number> }
type Answer = {
  question: string; answer: string; cited: number[]; sources: Source[]; provider: string; model: string | null
  answer_type: string; grounded: boolean; warnings: string[]; latency_ms: number; disclaimer: string
}
type Status = { documents: number; chunks: number; embedding_model: string; reranker_model: string | null; llm: { resolved: string; ollama: boolean; ollama_model: string; anthropic: boolean; openai: boolean } }
type Doc = { id: number; title: string; doc_type: string; source_path: string; file_format: string; pages: number | null; chunk_count: number; synthetic: boolean }
type Evaluation = { retrieval: Record<string, Record<string, number>>; answers?: Record<string, unknown>; answer_provider: string; evaluated_at: string }

const EXAMPLES = [
  'What transaction pattern should trigger a structuring alert?',
  'How often must a high-risk customer’s KYC file be reviewed?',
  'Who must approve a relationship with a politically exposed person?',
  'How quickly must a SAR be filed after the MLRO decides to report?',
  'What counts as a pass-through indicator?',
]

/** Render "[2]" citation markers as clickable chips. */
function WithCitations({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  const parts = text.split(/(\[\d{1,2}\])/g)
  return <>{parts.map((p, i) => {
    const m = p.match(/^\[(\d{1,2})\]$/)
    return m ? <button key={i} onClick={() => onCite(Number(m[1]))} className="mx-0.5 rounded bg-blue-100 px-1 text-xs font-medium text-blue-700 hover:bg-blue-200">{m[1]}</button>
      : <Fragment key={i}>{p}</Fragment>
  })}</>
}

export default function Compliance() {
  const status = useFetch(() => get<Status>('/api/v1/compliance/status'), [])
  const docs = useFetch(() => get<Doc[]>('/api/v1/compliance/documents'), [])
  const evaluation = useFetch(() => get<Evaluation>('/api/v1/compliance/evaluation').catch(() => null), [])
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('hybrid')
  const [rerank, setRerank] = useState(true)
  const [provider, setProvider] = useState('auto')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [ans, setAns] = useState<Answer | null>(null)
  const [active, setActive] = useState<number | null>(null)

  const ask = async (question = q) => {
    if (question.trim().length < 3) return setErr('Enter a question of at least 3 characters')
    setQ(question); setErr(null); setBusy(true); setActive(null)
    try {
      setAns(await post<Answer>('/api/v1/compliance/ask', { question: question.trim(), mode, rerank, provider }))
    } catch (e) { setAns(null); setErr(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Compliance knowledge assistant</h1>
        <p className="text-sm text-slate-500">
          Hybrid retrieval (dense vectors in Qdrant + BM25, fused with RRF{status.data?.reranker_model ? ', cross-encoder reranking' : ''}) over {status.data?.documents ?? '…'} policy documents / {status.data?.chunks ?? '…'} chunks.
          Answers by <b>{status.data?.llm.resolved === 'ollama' ? `local ${status.data.llm.ollama_model} (Ollama)` : status.data?.llm.resolved ?? '…'}</b>, every claim cited.
        </p>
      </div>
      {status.error && <ErrorBox error={status.error} />}

      <Section title="Ask">
        <form onSubmit={e => { e.preventDefault(); ask() }} className="space-y-3">
          <textarea className="input min-h-20 w-full" maxLength={1000} placeholder="e.g. When is enhanced due diligence mandatory?" value={q} onChange={e => setQ(e.target.value)} />
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <select className="input" value={mode} onChange={e => setMode(e.target.value)}>
              <option value="hybrid">Hybrid (dense + BM25)</option><option value="dense">Dense only</option><option value="bm25">BM25 only</option>
            </select>
            <label className="flex items-center gap-1 text-slate-600"><input type="checkbox" checked={rerank} onChange={e => setRerank(e.target.checked)} /> rerank</label>
            <select className="input" value={provider} onChange={e => setProvider(e.target.value)}>
              <option value="auto">LLM: auto</option><option value="ollama">Ollama (local)</option><option value="anthropic">Claude</option>
              <option value="openai">OpenAI</option><option value="extractive">No LLM (quote sources)</option>
            </select>
            <button className="btn" disabled={busy}>{busy ? 'Thinking…' : 'Ask'}</button>
          </div>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map(x => <button type="button" key={x} onClick={() => ask(x)} className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 hover:bg-slate-50">{x}</button>)}
          </div>
        </form>
        {err && <div className="mt-3"><ErrorBox error={err} /></div>}
      </Section>

      {busy && <Loading />}
      {ans && !busy && (
        <div className="grid gap-4 xl:grid-cols-5">
          <Section title="Answer" className="xl:col-span-3" right={<span className="text-xs text-slate-500">{ans.provider}{ans.model ? ` · ${ans.model}` : ''} · {(ans.latency_ms / 1000).toFixed(1)}s</span>}>
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800"><WithCitations text={ans.answer} onCite={setActive} /></div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className={`rounded px-2 py-0.5 ${ans.grounded ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>{ans.grounded ? 'citations verified' : 'no valid citation'}</span>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">{ans.answer_type}</span>
              {ans.warnings.map(w => <span key={w} className="rounded bg-amber-50 px-2 py-0.5 text-amber-800">{w}</span>)}
            </div>
          </Section>
          <Section title="Sources" className="xl:col-span-2">
            <ol className="space-y-2">
              {ans.sources.map(s => (
                <li key={s.id} onClick={() => setActive(s.id)}
                  className={`cursor-pointer rounded-md border p-2 text-xs ${active === s.id ? 'border-blue-400 bg-blue-50' : ans.cited.includes(s.id) ? 'border-slate-300' : 'border-slate-100 opacity-70'}`}>
                  <div className="flex justify-between gap-2">
                    <span className="font-medium text-slate-800">[{s.id}] {s.title}</span>
                    {ans.cited.includes(s.id) && <span className="text-blue-700">cited</span>}
                  </div>
                  <div className="text-slate-500">{s.section ?? '-'}{s.page ? ` · page ${s.page}` : ''} · {Object.entries(s.scores).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>
                  {active === s.id && <p className="mt-1 text-slate-700">{s.text}</p>}
                </li>
              ))}
            </ol>
          </Section>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Section title="Indexed documents">
          <table className="tbl w-full">
            <thead><tr><th>Document</th><th>Type</th><th>Format</th><th className="text-right!">Chunks</th></tr></thead>
            <tbody>{docs.data?.map(d => (
              <tr key={d.id}><td className="whitespace-normal!">{d.title}</td><td className="text-xs">{d.doc_type}</td>
                <td className="uppercase">{d.file_format}{d.pages ? ` · ${d.pages}p` : ''}</td><td className="text-right tabular-nums">{d.chunk_count}</td></tr>
            ))}</tbody>
          </table>
          <p className="mt-2 text-xs text-slate-500">FinGuard Bank policies are fictional; FATF / EU documents are paraphrased study notes, not official texts.</p>
        </Section>
        <Section title="RAG evaluation (labelled question set)">
          {evaluation.data ? (
            <div className="space-y-3 text-sm">
              <table className="tbl w-full">
                <thead><tr><th>Retrieval</th><th className="text-right!">hit@1</th><th className="text-right!">hit@5</th><th className="text-right!">MRR</th><th className="text-right!">ctx prec@5</th></tr></thead>
                <tbody>{Object.entries(evaluation.data.retrieval).map(([k, m]) => (
                  <tr key={k}><td>{k}</td><td className="text-right tabular-nums">{m['hit@1']}</td><td className="text-right tabular-nums">{m['hit@5']}</td>
                    <td className="text-right tabular-nums">{m.mrr}</td><td className="text-right tabular-nums">{m['context_precision@5']}</td></tr>
                ))}</tbody>
              </table>
              {evaluation.data.answers && (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  {['fact_recall', 'citation_validity', 'cited_source_relevance', 'faithfulness_proxy', 'refusal_accuracy', 'median_latency_ms'].map(k => (
                    <div key={k} className="flex justify-between border-b border-slate-50"><dt className="text-slate-500">{k.replaceAll('_', ' ')}</dt><dd className="tabular-nums">{String(evaluation.data!.answers![k])}</dd></div>
                  ))}
                </dl>
              )}
              <p className="text-xs text-slate-500">Answer model: {String(evaluation.data.answers?.model ?? evaluation.data.answer_provider)} · evaluated {evaluation.data.evaluated_at}</p>
            </div>
          ) : <p className="text-sm text-slate-500">No evaluation yet. Run <code>python -m app.cli rag-eval</code>.</p>}
        </Section>
      </div>
      <Disclaimer text={ans?.disclaimer ?? 'Answers come only from the indexed policy documents and must be checked against the cited source. Not legal advice.'} />
    </div>
  )
}
