import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, ROLE_LABEL, useAuth } from './auth'
import Dashboard from './pages/Dashboard'
import Transactions from './pages/Transactions'
import TransactionPage from './pages/TransactionPage'
import Customers from './pages/Customers'
import CustomerPage from './pages/CustomerPage'
import Alerts from './pages/Alerts'
import Models from './pages/Models'
import ScoreTester from './pages/ScoreTester'
import Network from './pages/Network'
import Compliance from './pages/Compliance'
import Investigations from './pages/Investigations'
import InvestigationPage from './pages/InvestigationPage'
import Governance from './pages/Governance'
import Users from './pages/Users'
import Login from './pages/Login'
import { Loading } from './components/ui'

// each menu entry is shown only to roles holding its permission (the API enforces the same rules)
const NAV = [
  { to: '/', label: 'Dashboard', end: true, perm: 'view_monitoring' },
  { to: '/investigations', label: 'Investigations', perm: 'view_investigations' },
  { to: '/alerts', label: 'Alerts', perm: 'view_customers' },
  { to: '/transactions', label: 'Transactions', perm: 'view_customers' },
  { to: '/customers', label: 'Customers', perm: 'view_customers' },
  { to: '/network', label: 'Network', perm: 'view_customers' },
  { to: '/compliance', label: 'Compliance assistant', perm: 'ask_compliance' },
  { to: '/models', label: 'Models', perm: 'view_monitoring' },
  { to: '/score', label: 'Live scoring', perm: 'score_transaction' },
  { to: '/governance', label: 'Audit & governance', perm: 'view_audit' },
  { to: '/users', label: 'Users & roles', perm: 'manage_users' },
]

function Guard({ perm, children }: { perm: string; children: React.ReactNode }) {
  const { can } = useAuth()
  return can(perm) ? <>{children}</> : <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">Your role does not have access to this page.</p>
}

function Shell() {
  const { session, loading, can, logout } = useAuth()
  const loc = useLocation()
  if (loading) return <Loading />
  if (!session) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />
  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-slate-800 bg-slate-900 text-slate-300 md:sticky md:top-0 md:flex md:h-screen md:w-56 md:shrink-0 md:flex-col md:border-r md:border-b-0">
        <div className="flex items-center gap-2 px-4 py-4">
          <img src="/shield.svg" alt="" className="h-6 w-6" />
          <div>
            <div className="text-sm font-semibold text-white">FinGuard AI</div>
            <div className="text-[11px] text-slate-400">Phases 1-4 · agents + governance</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-y-auto md:pb-0">
          {NAV.filter(n => can(n.perm)).map(n => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => `whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? 'bg-slate-800 text-white' : 'hover:bg-slate-800/60 hover:text-white'}`}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden px-4 pt-4 text-[11px] leading-relaxed text-slate-500 md:mt-auto md:block md:pb-4">
          <div className="text-slate-300">{session.user.full_name}</div>
          <div>{ROLE_LABEL[session.user.role] ?? session.user.role}</div>
          <button onClick={logout} className="mt-2 text-slate-400 underline hover:text-white">Sign out</button>
          <p className="mt-3">Synthetic data only. Scores are indicators for human review, never verdicts.</p>
          <a href="/docs" target="_blank" rel="noreferrer" className="mt-1 block text-slate-400 underline">API docs</a>
        </div>
        <button onClick={logout} className="px-4 pb-3 text-left text-xs text-slate-400 underline md:hidden">Sign out ({session.user.username})</button>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-6">
        <Routes>
          <Route path="/" element={<Guard perm="view_monitoring"><Dashboard /></Guard>} />
          <Route path="/investigations" element={<Guard perm="view_investigations"><Investigations /></Guard>} />
          <Route path="/investigations/:id" element={<Guard perm="view_investigations"><InvestigationPage /></Guard>} />
          <Route path="/transactions" element={<Guard perm="view_customers"><Transactions /></Guard>} />
          <Route path="/transactions/:id" element={<Guard perm="view_customers"><TransactionPage /></Guard>} />
          <Route path="/customers" element={<Guard perm="view_customers"><Customers /></Guard>} />
          <Route path="/customers/:id" element={<Guard perm="view_customers"><CustomerPage /></Guard>} />
          <Route path="/alerts" element={<Guard perm="view_customers"><Alerts /></Guard>} />
          <Route path="/network" element={<Guard perm="view_customers"><Network /></Guard>} />
          <Route path="/compliance" element={<Guard perm="ask_compliance"><Compliance /></Guard>} />
          <Route path="/models" element={<Guard perm="view_monitoring"><Models /></Guard>} />
          <Route path="/score" element={<Guard perm="score_transaction"><ScoreTester /></Guard>} />
          <Route path="/governance" element={<Guard perm="view_audit"><Governance /></Guard>} />
          <Route path="/users" element={<Guard perm="manage_users"><Users /></Guard>} />
          <Route path="*" element={<p className="text-slate-500">Page not found.</p>} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/*" element={<Shell />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
