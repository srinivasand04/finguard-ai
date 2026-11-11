# FinGuard AI - Dashboard

React 19 + TypeScript + Tailwind CSS 4 + Recharts, built with Vite.

```bash
npm install
npm run dev     # http://localhost:5173, proxies /api to the FastAPI backend on :8000
npm run build   # type-check + production build
```

Pages (`src/pages/`):

| Page | Shows |
|---|---|
| Dashboard | KPIs, daily volume, flagged activity, risk distribution, alert mix, active models |
| Transactions | Filterable/sortable search; detail page with ML probability, anomaly percentile and per-feature explanation |
| Customers | Search; profile with risk indicators, behavioural profile, account velocity, counterparties, history |
| Alerts | ML, anomaly, structuring-rule and high-risk-customer alerts with reasons |
| Models | Registry, test-set metrics, confusion matrix, data split, feature importance |
| Live scoring | Score a hypothetical transaction against stored history in near real time |

`src/api.ts` holds typed API clients; `src/components/ui.tsx` holds shared UI pieces.
