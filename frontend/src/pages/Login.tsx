import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) return setErr('Enter your username and password')
    setBusy(true); setErr(null)
    try {
      await login(username.trim(), password)
      nav(sp.get('next') || '/', { replace: true })
    } catch (x) {
      setErr(x instanceof Error ? x.message : 'Login failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow-lg">
        <div className="flex items-center gap-2">
          <img src="/shield.svg" alt="" className="h-7 w-7" />
          <div>
            <h1 className="text-lg font-semibold text-slate-900">FinGuard AI</h1>
            <p className="text-xs text-slate-500">Financial crime intelligence · synthetic data</p>
          </div>
        </div>
        <label className="block text-sm">Username
          <input className="input mt-1 w-full" autoComplete="username" value={username} onChange={e => { setUsername(e.target.value); setErr(null) }} />
        </label>
        <label className="block text-sm">Password
          <input className="input mt-1 w-full" type="password" autoComplete="current-password" value={password} onChange={e => { setPassword(e.target.value); setErr(null) }} />
        </label>
        {err && <p className="text-sm text-red-600">{err}</p>}
        <button className="btn w-full" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <p className="text-xs text-slate-500">Demo accounts are created with <code>python -m app.cli seed-users</code>; the password is DEMO_USER_PASSWORD in your <code>.env</code>.</p>
      </form>
    </div>
  )
}
