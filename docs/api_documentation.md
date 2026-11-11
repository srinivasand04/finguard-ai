# API (Phase 1)

Interactive OpenAPI docs: http://localhost:8000/docs. All list endpoints return `{items, total, page, size}`; `size` ≤ 200.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | DB + Redis status |
| GET | `/api/v1/dashboard/summary` | Headline metrics (Redis-cached 60s) |
| GET | `/api/v1/dashboard/timeseries` | Daily count, value, high/medium flags |
| GET | `/api/v1/dashboard/risk-distribution` | Histogram of transaction and customer risk scores |
| GET | `/api/v1/customers` | Search: `q` (id/name), `segment`, `risk_level`, `country`, `sort` |
| GET | `/api/v1/customers/{id}` | Profile, accounts, risk, alert count |
| GET | `/api/v1/customers/{id}/risk` | Explainable risk indicators + behavioural profile |
| GET | `/api/v1/customers/{id}/transactions` | History, `risk_band`, `sort` |
| GET | `/api/v1/customers/{id}/counterparties` | Top counterparties by value, both directions |
| GET | `/api/v1/accounts/{id}` | Account |
| GET | `/api/v1/accounts/{id}/velocity` | 24h/7d/30d/90d windows + daily series |
| GET | `/api/v1/transactions` | Filters: `customer_id`, `account_id`, `tx_type`, `category`, `min_amount`, `max_amount`, `date_from`, `date_to`, `risk_band`, `cross_border`, `sort` |
| GET | `/api/v1/transactions/{id}` | Transaction + prediction + top factors |
| POST | `/api/v1/transactions/score` | Near-real-time scoring of a new transaction (not stored; audit-logged) |
| GET | `/api/v1/alerts` | Filters: `alert_type`, `severity`, `status`, `customer_id` (severity-then-score order) |
| GET | `/api/v1/alerts/{id}` | Alert |
| GET | `/api/v1/models` | Model registry (`active_only`) |
| GET | `/api/v1/models/{id}` | Metrics, importance, training data, hyperparameters |
| GET | `/api/v1/audit-logs` | Audit trail (`action` filter) |

Example:

```bash
curl -X POST http://localhost:8000/api/v1/transactions/score -H "Content-Type: application/json" \
  -d '{"sender_account_id":"ACC101149","receiver_account_id":"ACC100725","amount":9500,"tx_type":"WIRE","timestamp":"2026-06-30T02:15:00"}'
```

Errors: 404 for unknown ids, 422 for invalid input (e.g. negative amount, unknown `tx_type`, sender = receiver), 503 if no active model is registered.
