import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { fmtDate, fmtInt, fmtMoney, get, pct } from '../api'
import GraphView, { GraphLegend, type GraphData } from '../components/GraphView'
import { Badge, Disclaimer, ErrorBox, Loading, Section, Stat } from '../components/ui'
import { useFetch } from '../hooks'

type Summary = {
  nodes: number; edges: number; communities: number; graph_version: string
  patterns: Record<string, number>; networks: Record<string, number>
  top_pagerank: { account_id: string; customer_id: string; value: number }[]
  top_betweenness: { account_id: string; customer_id: string; value: number }[]
}
type Pattern = {
  id: number; pattern_type: string; account_ids: string[]; customer_ids: string[]; transaction_ids: number[]; hops: number
  start_amount: number; end_amount: number; start_ts: string; end_ts: string; duration_hours: number; score: number; network_id: number | null
}
type Network = {
  id: number; size: number; edge_count: number; total_value: number; high_risk_tx_count: number; cycle_count: number
  chain_count: number; cross_border_share: number; hubs: { account_id: string; role: string; degree: number }[]
  typology_hints: string[]; risk_score: number; risk_level: string; customer_ids: string[]
}
type AccountInfo = {
  metrics: Record<string, number | string | null>
  patterns: Pattern[]; network: Network | null
}
type View = { title: string; subtitle?: string; graph: GraphData; pattern?: Pattern & { transactions: { transaction_id: number; sender_account_id: string; receiver_account_id: string; amount: number; timestamp: string }[] } }

export default function Network() {
  const [sp, setSp] = useSearchParams()
  const summary = useFetch(() => get<Summary>('/api/v1/graph/summary'), [])
  const networks = useFetch(() => get<{ items: Network[] }>('/api/v1/graph/networks', { size: 12 }), [])
  const cycles = useFetch(() => get<{ items: Pattern[]; total: number }>('/api/v1/graph/patterns', { pattern_type: 'CYCLE', size: 8 }), [])
  const chains = useFetch(() => get<{ items: Pattern[]; total: number }>('/api/v1/graph/patterns', { pattern_type: 'LAYERING_CHAIN', size: 8 }), [])
  const [view, setView] = useState<View | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [info, setInfo] = useState<AccountInfo | null>(null)
  const [query, setQuery] = useState(sp.get('customer_id') ?? sp.get('account_id') ?? '')
  const [depth, setDepth] = useState(1)
  const [pathFrom, setPathFrom] = useState('')
  const [pathTo, setPathTo] = useState('')

  const load = useCallback(async (fn: () => Promise<View>) => {
    setErr(null)
    try { setView(await fn()) } catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
  }, [])

  const loadEgo = useCallback((id: string, d = depth) => {
    const key = id.toUpperCase().startsWith('CUST') ? 'customer_id' : 'account_id'
    setSp({ [key]: id.toUpperCase() })
    load(async () => {
      const g = await get<GraphData & { centre: string[] }>('/api/v1/graph/ego', { [key]: id.toUpperCase(), depth: d })
      return { title: `Ego network of ${id.toUpperCase()}`, subtitle: `${g.nodes.length} accounts · ${g.edges.length} money-flow edges · depth ${d}`, graph: g }
    })
  }, [depth, load, setSp])

  const loadPattern = (id: number) => load(async () => {
    const p = await get<View['pattern'] & { graph: GraphData }>(`/api/v1/graph/patterns/${id}`)
    return { title: `${p!.pattern_type === 'CYCLE' ? 'Circular flow' : 'Layering chain'} #${id}`, subtitle: `${p!.hops} hops in ${p!.duration_hours.toFixed(0)}h · score ${p!.score}`, graph: p!.graph, pattern: p }
  })
  const loadNetwork = (id: number) => load(async () => {
    const n = await get<Network & { graph: GraphData }>(`/api/v1/graph/networks/${id}`)
    return { title: `Suspicious network #${id}`, subtitle: `${n.size} accounts · ${n.typology_hints.join(', ') || 'no typology hints'}`, graph: n.graph }
  })
  const loadPath = () => load(async () => {
    const p = await get<{ found: boolean; path: string[]; hops: number; graph: GraphData }>('/api/v1/graph/path', { source: pathFrom.trim().toUpperCase(), target: pathTo.trim().toUpperCase(), directed: false })
    if (!p.found) throw new Error('No path between these accounts')
    return { title: `Path ${p.path.join(' → ')}`, subtitle: `${p.hops} hops (undirected)`, graph: p.graph }
  })

  // initial view: URL param, else the highest-risk network
  useEffect(() => {
    const id = sp.get('customer_id') ?? sp.get('account_id')
    if (id) loadEgo(id)
    else if (networks.data?.items[0]) loadNetwork(networks.data.items[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [networks.data])

  useEffect(() => {
    if (!selected) return
    setInfo(null)
    get<AccountInfo>(`/api/v1/graph/accounts/${selected}`).then(setInfo).catch(() => setInfo(null))
  }, [selected])

  const onSelect = useCallback((id: string) => setSelected(id), [])

  if (summary.error) return <ErrorBox error={summary.error} />
  if (!summary.data) return <Loading />
  const s = summary.data

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Network intelligence</h1>
        <p className="text-sm text-slate-500">Money-flow graph of {fmtInt(s.nodes)} accounts · graph version {s.graph_version}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Money-flow edges" value={fmtInt(s.edges)} sub="account → account relationships" />
        <Stat label="Communities" value={fmtInt(s.communities)} sub="Louvain" />
        <Stat label="Circular flows" value={fmtInt(s.patterns.CYCLE ?? 0)} sub="time-ordered cycles" />
        <Stat label="Layering chains" value={fmtInt(s.patterns.LAYERING_CHAIN ?? 0)} sub="≥3 rapid hops" />
        <Stat label="Suspicious networks" value={fmtInt(Object.values(s.networks).reduce((a, b) => a + b, 0))} sub={`${s.networks.HIGH ?? 0} high risk`} />
      </div>

      <Section title="Explore">
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <input className="input w-44" placeholder="Account or customer ID" value={query} onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && query.trim()) loadEgo(query.trim()) }} />
          <select className="input" value={depth} onChange={e => setDepth(Number(e.target.value))}>
            <option value={1}>1 hop</option><option value={2}>2 hops</option>
          </select>
          <button className="btn" disabled={!query.trim()} onClick={() => loadEgo(query.trim(), depth)}>Show ego network</button>
          <span className="mx-2 hidden h-6 w-px bg-slate-200 sm:inline-block" />
          <input className="input w-32" placeholder="From account" value={pathFrom} onChange={e => setPathFrom(e.target.value)} />
          <input className="input w-32" placeholder="To account" value={pathTo} onChange={e => setPathTo(e.target.value)} />
          <button className="btn-ghost" disabled={!pathFrom.trim() || !pathTo.trim()} onClick={loadPath}>Shortest path</button>
        </div>
        {err && <div className="mt-3"><ErrorBox error={err} /></div>}
      </Section>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="card xl:col-span-2">
          <header className="border-b border-slate-100 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-slate-700">{view?.title ?? 'Graph'}</h2>
            {view?.subtitle && <p className="text-xs text-slate-500">{view.subtitle}</p>}
          </header>
          <div className="space-y-2 p-4">
            {view ? <GraphView data={view.graph} onSelect={onSelect} /> : <Loading />}
            <GraphLegend />
            {view?.pattern && (
              <ol className="mt-2 space-y-1 text-sm">
                {view.pattern.transactions.map((t, i) => (
                  <li key={t.transaction_id} className="flex flex-wrap gap-x-2">
                    <span className="w-5 text-slate-400">{i + 1}.</span>
                    <Link className="text-blue-600 hover:underline" to={`/transactions/${t.transaction_id}`}>tx {t.transaction_id}</Link>
                    <span>{t.sender_account_id} → {t.receiver_account_id}</span>
                    <span className="tabular-nums">{fmtMoney(t.amount)}</span>
                    <span className="text-slate-500">{fmtDate(t.timestamp)}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>

        <Section title={selected ? `Account ${selected}` : 'Selected account'}>
          {!selected && <p className="text-sm text-slate-500">Click a node to see its graph metrics.</p>}
          {selected && !info && <Loading />}
          {info && (
            <div className="space-y-3 text-sm">
              <div className="flex gap-2">
                <Link className="text-blue-600 hover:underline" to={`/customers/${info.metrics.customer_id}`}>{String(info.metrics.customer_id)}</Link>
                <button className="text-xs text-blue-600" onClick={() => { setQuery(selected!); loadEgo(selected!) }}>centre graph here</button>
              </div>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                {([['in_degree', 'Senders', fmtInt], ['out_degree', 'Receivers', fmtInt], ['pagerank_percentile', 'PageRank pct.', (v: number) => pct(v)],
                  ['betweenness', 'Betweenness', (v: number) => v.toFixed(4)], ['community_id', 'Community', String], ['community_size', 'Community size', fmtInt],
                  ['cycle_count', 'Circular flows', fmtInt], ['chain_count', 'Layering chains', fmtInt],
                  ['neighbour_high_risk_share', 'Risky neighbours', (v: number) => pct(v)], ['network_id', 'Network', (v: number) => `#${v}`]] as [string, string, (v: number) => string][])
                  .map(([k, l, f]) => (
                    <div key={k} className="flex justify-between border-b border-slate-50 py-0.5">
                      <dt className="text-slate-500">{l}</dt><dd className="tabular-nums">{info.metrics[k] == null ? '-' : f(info.metrics[k] as number)}</dd>
                    </div>))}
              </dl>
              {info.network && (
                <button className="block text-left text-xs text-blue-600 hover:underline" onClick={() => loadNetwork(info.network!.id)}>
                  Open network #{info.network.id} ({info.network.size} accounts, {info.network.risk_level})
                </button>
              )}
              {info.patterns.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium text-slate-600">Patterns involving this account</div>
                  <ul className="space-y-1 text-xs">
                    {info.patterns.slice(0, 6).map(p => (
                      <li key={p.id}><button className="text-blue-600 hover:underline" onClick={() => loadPattern(p.id)}>
                        {p.pattern_type === 'CYCLE' ? 'Cycle' : 'Chain'} #{p.id} · {p.hops} hops · score {p.score}</button></li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </Section>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Section title="Suspicious networks">
          <ul className="divide-y divide-slate-100 text-sm">
            {networks.data?.items.map(n => (
              <li key={n.id} className="py-2">
                <div className="flex items-center justify-between gap-2">
                  <button className="text-blue-600 hover:underline" onClick={() => loadNetwork(n.id)}>Network #{n.id} · {n.size} accounts</button>
                  <Badge value={n.risk_level} />
                </div>
                <div className="text-xs text-slate-500">{fmtMoney(n.total_value, 0)} · {n.high_risk_tx_count} high-risk tx · {n.typology_hints.join(', ') || '-'}</div>
              </li>
            ))}
          </ul>
        </Section>
        {[{ title: `Circular flows (${cycles.data?.total ?? 0})`, d: cycles.data }, { title: `Layering chains (${chains.data?.total ?? 0})`, d: chains.data }].map(({ title, d }) => (
          <Section key={title} title={title}>
            <ul className="divide-y divide-slate-100 text-sm">
              {d?.items.map(p => (
                <li key={p.id} className="py-2">
                  <button className="text-left text-blue-600 hover:underline" onClick={() => loadPattern(p.id)}>{p.account_ids.join(' → ')}</button>
                  <div className="text-xs text-slate-500">{fmtMoney(p.start_amount, 0)} → {fmtMoney(p.end_amount, 0)} · {p.duration_hours.toFixed(0)}h · score {p.score}</div>
                </li>
              ))}
              {d && d.items.length === 0 && <li className="py-2 text-slate-400">None found</li>}
            </ul>
          </Section>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {([['Highest PageRank (where value accumulates)', s.top_pagerank], ['Highest betweenness (brokers between groups)', s.top_betweenness]] as const).map(([t, rows]) => (
          <Section key={t} title={t}>
            <table className="tbl w-full"><tbody>
              {rows.map(r => (
                <tr key={r.account_id}>
                  <td><button className="text-blue-600 hover:underline" onClick={() => { setQuery(r.account_id); loadEgo(r.account_id) }}>{r.account_id}</button></td>
                  <td><Link className="hover:underline" to={`/customers/${r.customer_id}`}>{r.customer_id}</Link></td>
                  <td className="text-right tabular-nums">{r.value.toFixed(5)}</td>
                </tr>))}
            </tbody></table>
          </Section>
        ))}
      </div>
      <Disclaimer />
    </div>
  )
}
