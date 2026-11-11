# API (Phases 1-2)

Interactive OpenAPI docs: http://localhost:8000/docs. All list endpoints return `{items, total, page, size}`; `size` ≤ 200.

## Phase 1 - transaction intelligence and detection

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

## Phase 2 - graph intelligence

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/graph/summary` | Nodes, edges, communities, pattern and network counts, top PageRank / betweenness |
| GET | `/api/v1/graph/accounts/{id}` | Account graph metrics, patterns it is part of, its network |
| GET | `/api/v1/graph/ego` | `account_id` or `customer_id`, `depth` 1-2: nodes/edges for visualisation |
| GET | `/api/v1/graph/patterns` | Cycles and layering chains: `pattern_type`, `min_score`, `account_id`, `customer_id` |
| GET | `/api/v1/graph/patterns/{id}` | Pattern with its transactions in hop order and highlighted subgraph |
| GET | `/api/v1/graph/networks` | Suspicious networks ranked by risk (`risk_level`) |
| GET | `/api/v1/graph/networks/{id}` | Members, hubs, typology hints, patterns and subgraph |
| GET | `/api/v1/graph/path` | Shortest money-flow path `source` -> `target` (`directed`) |

## Phase 2 - compliance knowledge (RAG)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/compliance/status` | Index size, embedding/reranker models, which LLM provider will answer |
| GET | `/api/v1/compliance/documents` | Indexed documents |
| GET | `/api/v1/compliance/documents/{id}` | Document chunks with section and page |
| GET | `/api/v1/compliance/search` | `q`, `mode` (hybrid / dense / bm25), `rerank`, `doc_type`, `k` |
| POST | `/api/v1/compliance/ask` | `{question, k, mode, rerank, provider, doc_type}` -> answer, verified citations, sources (audit-logged) |
| GET | `/api/v1/compliance/evaluation` | Latest retrieval and answer evaluation |

Alert types: `HIGH_RISK_TRANSACTION`, `ANOMALOUS_TRANSACTION`, `POSSIBLE_STRUCTURING`, `HIGH_RISK_CUSTOMER` (Phase 1) and `CIRCULAR_FLOW`, `LAYERING_CHAIN`, `SUSPICIOUS_NETWORK` (Phase 2, source `GRAPH`).

## Examples

```bash
curl -X POST http://localhost:8000/api/v1/transactions/score -H "Content-Type: application/json" \
  -d '{"sender_account_id":"ACC101149","receiver_account_id":"ACC100725","amount":9500,"tx_type":"WIRE","timestamp":"2026-06-30T02:15:00"}'
```

```bash
curl -X POST http://localhost:8000/api/v1/compliance/ask -H "Content-Type: application/json" \
  -d '{"question":"What pattern should trigger a structuring alert?"}'
```

Errors: 404 for unknown ids, 422 for invalid input (e.g. negative amount, unknown `tx_type`, sender = receiver, question shorter than 3 characters), 503 if no active model, graph or compliance index is available.
