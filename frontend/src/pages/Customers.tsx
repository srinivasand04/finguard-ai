import { Link, useSearchParams } from 'react-router-dom'
import type { CustomerSummary, Page } from '../api'
import { get } from '../api'
import { Badge, ErrorBox, Loading, Pager, Section } from '../components/ui'
import { useFetch } from '../hooks'

export default function Customers() {
  const [sp, setSp] = useSearchParams()
  const page = Number(sp.get('page') ?? 1)
  const key = sp.toString()
  const { data, error, loading } = useFetch(() => get<Page<CustomerSummary>>('/api/v1/customers', {
    q: sp.get('q'), segment: sp.get('segment'), risk_level: sp.get('risk_level'), sort: sp.get('sort') ?? 'risk_desc', page, size: 50,
  }), [key])
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v); else n.delete(k)
    if (k !== 'page') n.delete('page')
    setSp(n)
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Customers</h1>
      <Section title="Search">
        <div className="flex flex-wrap gap-2">
          <input key={sp.get('q') ?? ''} className="input w-64" placeholder="Customer ID or name" defaultValue={sp.get('q') ?? ''}
            onKeyDown={e => { if (e.key === 'Enter') set('q', (e.target as HTMLInputElement).value.trim()) }}
            onBlur={e => set('q', e.target.value.trim())} />
          <select className="input" value={sp.get('segment') ?? ''} onChange={e => set('segment', e.target.value)}>
            <option value="">All segments</option><option value="RETAIL">Retail</option><option value="SME">SME</option><option value="CORPORATE">Corporate</option>
          </select>
          <select className="input" value={sp.get('risk_level') ?? ''} onChange={e => set('risk_level', e.target.value)}>
            <option value="">All risk levels</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option>
          </select>
          <select className="input" value={sp.get('sort') ?? 'risk_desc'} onChange={e => set('sort', e.target.value)}>
            <option value="risk_desc">Highest risk first</option><option value="id_asc">Customer ID</option><option value="name_asc">Name</option>
          </select>
        </div>
      </Section>
      {error && <ErrorBox error={error} />}
      <section className="card p-2">
        {loading && !data ? <Loading /> : data && <>
          <div className="overflow-x-auto">
            <table className="tbl w-full">
              <thead><tr><th>Customer</th><th>Name</th><th>Segment</th><th>Country</th><th>KYC</th><th>PEP</th><th>Onboarded</th><th className="text-right!">Risk score</th><th>Level</th></tr></thead>
              <tbody>
                {data.items.map(c => (
                  <tr key={c.customer_id}>
                    <td><Link className="text-blue-600 hover:underline" to={`/customers/${c.customer_id}`}>{c.customer_id}</Link></td>
                    <td>{c.full_name}</td><td>{c.segment}</td><td>{c.country}</td><td>{c.kyc_level}</td>
                    <td>{c.pep_flag ? <span className="text-amber-700">Yes</span> : <span className="text-slate-400">No</span>}</td>
                    <td className="text-slate-500">{c.onboarding_date}</td>
                    <td className="text-right tabular-nums">{c.risk_score ?? '-'}</td><td><Badge value={c.risk_level} /></td>
                  </tr>
                ))}
                {data.items.length === 0 && <tr><td colSpan={9} className="py-6 text-center text-slate-400">No customers found</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="px-2 pb-1"><Pager page={page} size={data.size} total={data.total} onPage={p => set('page', String(p))} /></div>
        </>}
      </section>
    </div>
  )
}
