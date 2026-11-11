import { useSearchParams } from 'react-router-dom'
import type { Page, Transaction } from '../api'
import { get } from '../api'
import { ErrorBox, Loading, Pager, Section, TxTable } from '../components/ui'
import { useFetch } from '../hooks'

const FIELDS = ['customer_id', 'account_id', 'tx_type', 'category', 'risk_band', 'cross_border', 'min_amount', 'max_amount', 'date_from', 'date_to', 'sort'] as const

export default function Transactions() {
  const [sp, setSp] = useSearchParams()
  const page = Number(sp.get('page') ?? 1)
  const params = Object.fromEntries(FIELDS.map(f => [f, sp.get(f) ?? undefined]))
  const key = sp.toString()
  const { data, error, loading } = useFetch(() => get<Page<Transaction>>('/api/v1/transactions', { ...params, page, size: 50 }), [key])

  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v); else n.delete(k)
    if (k !== 'page') n.delete('page')
    setSp(n)
  }
  const sel = (k: string, opts: [string, string][]) => (
    <select className="input" value={sp.get(k) ?? ''} onChange={e => set(k, e.target.value)}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
  const txt = (k: string, ph: string, type = 'text') => (
    <input key={`${k}-${sp.get(k) ?? ''}`} className="input w-36" type={type} placeholder={ph} defaultValue={sp.get(k) ?? ''}
      onBlur={e => set(k, e.target.value.trim())} onKeyDown={e => { if (e.key === 'Enter') set(k, (e.target as HTMLInputElement).value.trim()) }} />
  )

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Transactions</h1>
      <Section title="Filters" right={<button className="text-xs text-blue-600" onClick={() => setSp(new URLSearchParams())}>Reset</button>}>
        <div className="flex flex-wrap gap-2">
          {txt('customer_id', 'Customer ID')}
          {txt('account_id', 'Account ID')}
          {sel('tx_type', [['', 'Any type'], ['TRANSFER', 'Transfer'], ['PAYMENT', 'Payment'], ['WIRE', 'Wire']])}
          {sel('category', [['', 'Any category'], ['MERCHANT_PAYMENT', 'Merchant payment'], ['BUSINESS_TRANSFER', 'Business transfer'],
            ['SALARY_OR_PAYROLL', 'Salary / payroll'], ['BUSINESS_TO_PERSON', 'Business to person'], ['P2P_TRANSFER', 'P2P transfer']])}
          {sel('risk_band', [['', 'Any risk'], ['HIGH', 'High risk'], ['MEDIUM', 'Medium risk'], ['LOW', 'Low risk']])}
          {sel('cross_border', [['', 'Domestic + cross-border'], ['true', 'Cross-border only'], ['false', 'Domestic only']])}
          {txt('min_amount', 'Min amount', 'number')}
          {txt('max_amount', 'Max amount', 'number')}
          {txt('date_from', 'From', 'date')}
          {txt('date_to', 'To', 'date')}
          {sel('sort', [['timestamp_desc', 'Newest first'], ['timestamp_asc', 'Oldest first'], ['risk_desc', 'Highest risk'], ['amount_desc', 'Largest amount']])}
        </div>
      </Section>
      {error && <ErrorBox error={error} />}
      <section className="card p-2">
        {loading && !data ? <Loading /> : data && <>
          <TxTable items={data.items} />
          <div className="px-2 pb-1"><Pager page={page} size={data.size} total={data.total} onPage={p => set('page', String(p))} /></div>
        </>}
      </section>
    </div>
  )
}
