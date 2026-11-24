# Graph Neural Network experiment

Question: **does a graph neural network (GNN) add useful signal on top of FinGuard's 28 transaction features?**

This follows the pattern of NVIDIA's open AI Blueprint for financial fraud detection (GNN embeddings fed into XGBoost) and borrows the reverse-direction message passing idea from IBM's open-source Multi-GNN for anti-money laundering.

Run it: `python -m app.cli gnn-experiment` (≈2-4 min on CPU). Results: `models/gnn/gnn_evaluation_latest.json`; the model is registered as `fraud_xgboost_gnn` (inactive benchmark, visible on the Models page).

## Method

| Step | Choice | Why |
|---|---|---|
| Split | Same chronological 60 / 15 / 25 split as the production model | Apples-to-apples comparison |
| Graph | 2,382 accounts, 50,312 directed money-flow edges, **training period only** | Validation/test transactions are scored with what was known at the time - no look-ahead (unit-tested) |
| Node features | 15 per account (activity, amounts, degrees, cross-border and night share, near-threshold count, age, segment, home-country risk) | Account behaviour summary |
| Labels | Account took part in a simulated laundering transaction **before the cutoff** | No future labels |
| Model | Directed GraphSAGE, 2 layers, 32 hidden units, PyTorch Geometric; separate weights for incoming and outgoing money | Money in vs money out mean different things (fan-in vs fan-out) |
| Stacking | 5-fold **out-of-fold** predictions: each account's score/embedding comes from a GNN that never saw its label | Prevents XGBoost from learning a leaked signal |
| Transaction features added | sender / receiver / max GNN probability + 8 PCA dims of each embedding (19 features) | NVIDIA blueprint pattern |
| **Ablation** | Identical network with **no edges** (each account sees only itself) | Separates "graph" gain from "account history" gain |
| Uncertainty | Paired bootstrap (1,000 resamples) of the test PR-AUC difference + 4 training seeds | Only 41 laundering transactions in the test period |

## Results (test period: 56,604 transactions, 41 laundering)

| Model | PR-AUC (seed 42) | PR-AUC mean of 4 seeds | Recall in top 1% of alerts |
|---|---|---|---|
| Baseline XGBoost (28 features) | 0.687 | 0.687 | 83% |
| + GNN features | 0.770 | **0.782** | 90% |
| + same network **without edges** (ablation) | 0.831 | **0.832** | 95% |

| Comparison (paired bootstrap, seed 42) | PR-AUC gain | 95% interval | Probability better |
|---|---|---|---|
| GNN vs baseline | +0.08 | -0.04 to +0.21 | 91% - promising, not conclusive |
| No-edge ablation vs baseline | **+0.14** | **+0.06 to +0.23** | **100% - significant** |
| GNN vs ablation | -0.06 | -0.14 to +0.01 | 5% |

Account-level ranking (out-of-fold, base rate 0.10):

| | PR-AUC, mean of 4 seeds |
|---|---|
| GNN (uses the graph) | **0.77** |
| Ablation (no graph) | 0.65 |

## What this means

1. **The graph does help find laundering accounts** - consistently +0.12 PR-AUC at account level across every seed.
2. **For scoring individual transactions, account history was what mattered.** The biggest, statistically solid gain (+0.14) came from giving XGBoost a memory of each account's past behaviour - something the original 28 features (7-day windows) lacked. The GNN features also helped (+0.08 to +0.11 on average) but less than the simpler version.
3. **Likely reason:** message passing pulls neighbours' scores together, so ordinary businesses that *receive* money from mule accounts look riskier; that adds false positives at transaction level (precision at the tuned threshold 0.57 for the GNN vs 0.63 for the ablation).
4. **Practical recommendation:** promote the account-history features first (cheap, significant); use the GNN for **account-level** tasks it is better at - mule-account ranking and suspicious-network triage - rather than as a transaction feature.

## Caveats

- Synthetic data: the simulator reuses a pool of mule accounts across patterns, which makes "this account was involved before" a strong signal. Real repeat-mule rates differ.
- 41 test positives make every transaction-level number noisy - hence the bootstrap intervals and seeds.
- Not compared against IBM's AMLworld benchmark yet; FinGuard's simulator uses the same eight typologies, so that is the natural next step.
- The GNN model is a registered benchmark, not used for live scoring (the online scoring path would need GNN inference).

## Sources for the approach

- NVIDIA AI Blueprint for financial fraud detection (GNN embeddings → XGBoost): https://build.nvidia.com/nvidia/financial-fraud-detection/modelcard
- IBM Multi-GNN for anti-money laundering (directed multigraphs, reverse message passing): https://github.com/IBM/Multi-GNN
- PyTorch Geometric GraphSAGE (`SAGEConv`): https://pytorch-geometric.readthedocs.io/
