# Database Design (Phases 1-2)

PostgreSQL 16 is the source of truth. Tables are defined in `backend/app/models.py` and created with `python -m app.cli init-db`.

```
customers 1──* accounts 1──* transactions (sender / receiver) 1──* fraud_predictions *──1 model_versions
customers 1──1 customer_risk
customers 1──* alerts *──0..1 transactions
audit_logs (append-only event log)
```

| Table | Key columns | Notes |
|---|---|---|
| `customers` | `customer_id` PK, `segment`, `country`, `kyc_level`, `pep_flag`, `onboarding_date` | Synthetic profiles |
| `accounts` | `account_id` PK, `customer_id` FK, `account_type`, `country`, `bank_id`, `opened_date`, `sim_is_sar` | `sim_is_sar` = simulator label, training/evaluation only |
| `transactions` | `transaction_id` PK, sender/receiver account + customer FKs, `tx_type`, `category`, `amount`, `timestamp`, `is_cross_border`, `sim_is_sar`, `sim_alert_id` | Indexed on (sender, ts), (receiver, ts), customers, ts |
| `model_versions` | `id` PK, `model_name`+`version` unique, `algorithm`, `artifact_path`, `features`, `hyperparameters`, `metrics`, `feature_importance`, `training_data`, `is_active` | Model registry |
| `fraud_predictions` | `id` PK, `transaction_id` FK, `model_version_id` FK, `anomaly_model_version_id` FK, `fraud_probability`, `anomaly_score`, `risk_score`, `risk_band`, `top_factors` JSON | One row per transaction per scoring run |
| `customer_risk` | `customer_id` PK/FK, `risk_score`, `risk_level`, `indicators` JSON, `profile` JSON, `scoring_version` | Explainable scoring output |
| `alerts` | `id` PK, `alert_type`, `source`, `severity`, `status`, `customer_id` FK, `account_id`, `transaction_id`, `score`, `reasons` JSON | Read-only in Phase 1 |
| `audit_logs` | `id` PK, `actor`, `action`, `entity_type`, `entity_id`, `details` JSON, `created_at` | Ingestion, training, scoring, risk, alerts, scoring requests |

Design choices
- Simulator ground truth is stored in clearly named `sim_*` columns and never exposed as a verdict through the API.
- Pipeline outputs (`fraud_predictions`, `customer_risk`, `alerts`) are fully rebuilt by each run and traced to a `model_versions` row or `scoring_version`.
- JSON columns hold explanation payloads that will be referenced as evidence in Phase 3.

## Phase 2 tables

| Table | Key columns | Notes |
|---|---|---|
| `graph_edges` | `src_account_id`, `dst_account_id` (unique pair), `tx_count`, `total_amount`, `first_ts`, `last_ts`, `max_risk_score`, `high_risk_count`, `is_cross_border` | Aggregated money-flow edge per account pair |
| `account_graph_metrics` | `account_id` PK, `in/out_degree`, `degree_centrality`, `pagerank`, `pagerank_percentile`, `betweenness`, `community_id`, `community_size`, `cycle_count`, `chain_count`, `network_id`, `neighbour_high_risk_share`, `graph_version` | One row per account per graph run |
| `graph_patterns` | `id`, `pattern_type` (CYCLE / LAYERING_CHAIN), `account_ids`, `customer_ids`, `transaction_ids` (JSON, in hop order), `hops`, `start/end_amount`, `start/end_ts`, `duration_hours`, `score`, `network_id` | Time-ordered flows - each references its exact transactions (evidence for Phase 3) |
| `suspicious_networks` | `id`, `account_ids`, `customer_ids`, `size`, `edge_count`, `total_value`, `high_risk_tx_count`, `cycle_count`, `chain_count`, `cross_border_share`, `hubs`, `typology_hints`, `risk_score`, `risk_level` | Connected groups in the risk subgraph |
| `compliance_documents` | `id`, `title`, `doc_type`, `source_path`, `file_format`, `pages`, `sha256` (unique), `chunk_count`, `synthetic` | Source documents (PDF/DOCX/TXT/MD) |
| `compliance_chunks` | `id` (= Qdrant point id), `document_id` FK, `chunk_index`, `section`, `page`, `text` | Section-aware chunks; vectors live in Qdrant collection `compliance_chunks` |

`transactions.sim_alert_type` (Phase 2) stores the simulator typology so graph detection can be evaluated per typology.

**Qdrant** holds one 384-d cosine vector per chunk (all-MiniLM-L6-v2) with payload `document_id, title, doc_type, section, page`. Postgres stays the source of truth for chunk text; BM25 is built in memory from it.

Tables planned for Phase 3: `investigations`, `investigation_evidence`, `investigation_reports`, `approvals`, `agent_execution_logs`.
