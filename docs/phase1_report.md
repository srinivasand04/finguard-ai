# Phase 1 Report - Financial Data Intelligence & ML Detection

Run date: 2026-11-11 · model version `v20261111-005137` · all data synthetic.

## 1. Data

| Item | Value |
|---|---|
| Customers / accounts | 1,500 / 2,382 (88% domestic DE, 12% foreign incl. elevated-risk jurisdictions) |
| Transactions generated | 229,057 over 180 days (2026-01-01 → 2026-06-29) |
| Accounts in laundering patterns | 232 (~10%, a reused "mule" pool) |
| Simulated SAR transactions | 1,122 (0.49%) from 120 patterns across 8 typologies |
| Rows rejected by validation | 2,712 - exactly the injected dirty rows (452 each: duplicates, missing account, unknown account, self-transfer, non-positive amount, bad timestamp) |
| Rows auto-repaired | 452 (messy transaction type casing/whitespace) |
| Loaded into Postgres | 226,345 transactions |

**Why a generator instead of running AMLSim directly:** AMLSim needs a Java/Maven build plus a manually downloaded MASON jar. The generator writes AMLSim's own file layout (`accounts.csv`, `transactions.csv`, `alerts.csv`) and typology names, so `python -m app.cli ingest --source <amlsim output dir>` works with a real AMLSim run unchanged. Customer profiles (`customers.csv`) are a FinGuard extension, as the spec requires.

Typologies: fan_out, fan_in, cycle, scatter_gather, gather_scatter, bipartite, stack (AMLSim) + structuring.

## 2. Models (chronological split: train 60% / validation 15% / test 25%)

Test period 2026-05-17 → 2026-06-29: 56,587 transactions, 141 SAR (base rate 0.25%).

| Model | Role | ROC-AUC | PR-AUC | Precision | Recall | F1 | Recall @ top 1% |
|---|---|---|---|---|---|---|---|
| XGBoost | **active scorer** | 0.993 | **0.782** | 0.832 | 0.702 | 0.762 | 0.858 |
| Random Forest | benchmark | 0.991 | 0.647 | 0.606 | 0.709 | 0.654 | 0.851 |
| Isolation Forest | unsupervised anomaly | 0.818 | 0.043 | - | - | - | 0.206 |

Threshold for precision/recall chosen on the validation slice (max F1), then applied to the test slice - never tuned on test.

**Reading these numbers honestly**
- PR-AUC is the headline metric: with a 0.25% base rate, accuracy and ROC-AUC look excellent for almost any model.
- Synthetic patterns are cleaner than real laundering, so these metrics are optimistic. Expect much lower numbers on real or AMLSim-scale data.
- Isolation Forest is weak at finding *labelled* SAR activity (PR-AUC 0.04 vs 0.0025 base rate - still 17x better than random). Its role is to surface *unusual* behaviour the supervised model was never trained on, so it contributes only 20% of the blended risk score and only above the 95th percentile.

Top XGBoost features (gain): `is_new_counterparty`, `near_threshold`, `sender_segment`, `amount_vs_sender_mean`, `log_amount`, `type_TRANSFER`, `is_night`.

### Leakage controls
- All behavioural features use only events strictly **before** each transaction (cumulative sums + as-of joins), identical code for batch and real-time scoring.
- Chronological split, no shuffling.
- An earlier generator version typed every laundering transaction as TRANSFER/WIRE, which made `type_PAYMENT` the top feature (PR-AUC 0.86). This was a generator artefact, so it was fixed - laundering transactions now follow the same typing rule as normal ones.

## 3. Transaction risk score

`risk_score = 100 × (0.8 × ML probability + 0.2 × anomaly component)`, anomaly component = 0 below the 95th anomaly percentile. Bands: HIGH ≥ 60, MEDIUM ≥ 30 (configurable in `backend/config/risk_config.json`).

Result: 1,259 HIGH · 775 MEDIUM · 224,311 LOW.

Explanations: exact XGBoost TreeSHAP contributions for every transaction with probability ≥ 1%, fast approximate contributions for the rest (cut batch scoring from 494s to 71s).

## 4. Customer risk

Weighted, explainable indicators (each stored with observed value, threshold and weight): high-risk transaction count, peak ML probability, new counterparties (30d), volume spike vs own baseline, pass-through, elevated-risk geography, near-threshold amounts, night activity, PEP, new relationship, domicile. Score capped at 100; HIGH ≥ 60, MEDIUM ≥ 30.

Result: 49 HIGH · 234 MEDIUM · 1,217 LOW.

## 5. Alerts (1,911, all OPEN, read-only in Phase 1)

| Type | Source | Count |
|---|---|---|
| HIGH_RISK_TRANSACTION | XGBoost risk band HIGH | 1,259 |
| ANOMALOUS_TRANSACTION | Isolation Forest ≥ 99.7th percentile (and not already HIGH) | 575 |
| HIGH_RISK_CUSTOMER | Customer risk level HIGH | 49 |
| POSSIBLE_STRUCTURING | Rule: ≥ 3 amounts in [9,000, 10,000) within 7 days | 28 |

## 6. Known limitations / carried into later phases
- No authentication or RBAC yet (Phase 4); the API is read-only apart from the stateless scoring endpoint, which writes an audit-log entry.
- Alert triage/case management and approvals → Phase 3.
- Cycle and network typologies are only partly visible to transaction-level features → Phase 2 graph features will add them.
- Schema is created with `create_all`; Alembic migrations should be added before the schema changes in Phase 2.
- The country "elevated-risk" list is illustrative demo configuration, not a statement about any jurisdiction.
