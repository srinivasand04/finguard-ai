# Database Design (Phase 1)

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

Tables planned for later phases: `investigations`, `investigation_evidence`, `investigation_reports`, `compliance_documents`, `approvals`, `agent_execution_logs`.
