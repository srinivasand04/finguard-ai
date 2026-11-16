import { useState } from 'react'
import { fmtDate, get, patch, post, type User } from '../api'
import { ROLE_LABEL, useAuth } from '../auth'
import { ErrorBox, Loading, Section } from '../components/ui'
import { useFetch } from '../hooks'

export default function Users() {
  const { session } = useAuth()
  const [tick, setTick] = useState(0)
  const list = useFetch(() => get<{ roles: string[]; items: User[] }>('/api/v1/users'), [tick])
  const [form, setForm] = useState({ username: '', full_name: '', role: 'FRAUD_ANALYST', password: '' })
  const [msg, setMsg] = useState<string | null>(null)

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setMsg(null)
    if (!form.username.trim() || !form.full_name.trim()) return setMsg('Username and full name are required')
    if (form.password.length < 10) return setMsg('Password must be at least 10 characters')
    try {
      await post('/api/v1/users', form)
      setForm({ username: '', full_name: '', role: form.role, password: '' }); setMsg('User created'); setTick(t => t + 1)
    } catch (x) { setMsg(x instanceof Error ? x.message : String(x)) }
  }
  const update = async (u: User, body: Partial<User>) => {
    setMsg(null)
    try { await patch(`/api/v1/users/${u.username}`, body); setTick(t => t + 1) } catch (x) { setMsg(x instanceof Error ? x.message : String(x)) }
  }

  if (list.error) return <ErrorBox error={list.error} />
  if (!list.data) return <Loading />
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">Users & roles</h1>
      <Section title="Create user">
        <form onSubmit={create} className="flex flex-wrap items-end gap-2 text-sm">
          <label className="flex flex-col gap-1">Username<input className="input w-40" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /></label>
          <label className="flex flex-col gap-1">Full name<input className="input w-48" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} /></label>
          <label className="flex flex-col gap-1">Role<select className="input" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
            {list.data.roles.map(r => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}</select></label>
          <label className="flex flex-col gap-1">Initial password<input className="input w-44" type="password" autoComplete="new-password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /></label>
          <button className="btn">Create</button>
        </form>
        <p className="mt-2 text-xs text-slate-500">Passwords: 10+ characters with an upper-case letter and a digit. Stored as salted PBKDF2-SHA256 hashes.</p>
        {msg && <p className="mt-1 text-sm text-slate-700">{msg}</p>}
      </Section>
      <section className="card overflow-x-auto p-2">
        <table className="tbl w-full">
          <thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Status</th><th>Last login</th><th /></tr></thead>
          <tbody>{list.data.items.map(u => {
            const self = u.username === session?.user.username
            return (
              <tr key={u.id}>
                <td className="font-medium">{u.username}</td><td>{u.full_name}</td>
                <td><select className="input py-1! text-xs" value={u.role} disabled={self} onChange={e => update(u, { role: e.target.value })}>
                  {list.data!.roles.map(r => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}</select></td>
                <td>{u.is_active ? <span className="text-emerald-700">active</span> : <span className="text-slate-400">deactivated</span>}</td>
                <td className="text-xs text-slate-500">{u.last_login_at ? fmtDate(u.last_login_at) : 'never'}</td>
                <td>{!self && <button className="btn-ghost text-xs" onClick={() => update(u, { is_active: !u.is_active })}>{u.is_active ? 'Deactivate' : 'Activate'}</button>}</td>
              </tr>)
          })}</tbody>
        </table>
      </section>
    </div>
  )
}
