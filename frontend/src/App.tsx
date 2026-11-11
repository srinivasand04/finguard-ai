import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Transactions from './pages/Transactions'
import TransactionPage from './pages/TransactionPage'
import Customers from './pages/Customers'
import CustomerPage from './pages/CustomerPage'
import Alerts from './pages/Alerts'
import Models from './pages/Models'
import ScoreTester from './pages/ScoreTester'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/transactions', label: 'Transactions' },
  { to: '/customers', label: 'Customers' },
  { to: '/alerts', label: 'Alerts' },
  { to: '/models', label: 'Models' },
  { to: '/score', label: 'Live scoring' },
]

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen md:flex">
        <aside className="border-b border-slate-800 bg-slate-900 text-slate-300 md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:border-r md:border-b-0">
          <div className="flex items-center gap-2 px-4 py-4">
            <img src="/shield.svg" alt="" className="h-6 w-6" />
            <div>
              <div className="text-sm font-semibold text-white">FinGuard AI</div>
              <div className="text-[11px] text-slate-400">Phase 1 · Detection</div>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
            {NAV.map(n => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => `whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? 'bg-slate-800 text-white' : 'hover:bg-slate-800/60 hover:text-white'}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="hidden px-4 pt-6 text-[11px] leading-relaxed text-slate-500 md:block">
            Synthetic data only. Scores are indicators for human review, never verdicts.
            <a href="/docs" target="_blank" rel="noreferrer" className="mt-2 block text-slate-400 underline">API docs</a>
          </div>
        </aside>
        <main className="min-w-0 flex-1 p-4 md:p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/transactions" element={<Transactions />} />
            <Route path="/transactions/:id" element={<TransactionPage />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/customers/:id" element={<CustomerPage />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/models" element={<Models />} />
            <Route path="/score" element={<ScoreTester />} />
            <Route path="*" element={<p className="text-slate-500">Page not found.</p>} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
