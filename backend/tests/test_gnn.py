"""GNN experiment: no look-ahead in the graph, model shapes, and an end-to-end run."""
import pandas as pd
import torch

from gnn.graph_data import NODE_FEATURES, build_account_graph
from gnn.model import AccountGNN

ACCOUNTS = pd.DataFrame({"account_id": ["A", "B", "C", "D"], "customer_id": ["1", "2", "3", "4"],
                         "country": ["DE", "DE", "PA", "DE"], "opened_date": ["2025-01-01"] * 4,
                         "segment": ["RETAIL", "SME", "RETAIL", "CORPORATE"], "sim_is_sar": [False] * 4})


def tx(rows):
    df = pd.DataFrame(rows, columns=["transaction_id", "sender_account_id", "receiver_account_id", "amount",
                                     "timestamp", "sim_is_sar"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["is_cross_border"] = False
    return df


def test_graph_uses_only_the_past():
    t = tx([(1, "A", "B", 100, "2026-01-01", False),
            (2, "B", "C", 9500, "2026-01-05", True),        # laundering before the cutoff
            (3, "C", "D", 9000, "2026-03-01", True)])       # after the cutoff: must be invisible
    g = build_account_graph(t, ACCOUNTS, pd.Timestamp("2026-02-01"), ["PA"])
    assert g.edge_index.shape[1] == 2 and g.max_edge_time < g.cutoff
    labels = dict(zip(g.account_ids, g.y.tolist()))
    assert labels == {"A": 0.0, "B": 1.0, "C": 1.0, "D": 0.0}      # D's future laundering is not leaked
    assert g.active.tolist() == [True, True, True, False]
    assert g.x.shape == (4, len(NODE_FEATURES)) and torch.isfinite(g.x).all()


def test_directed_gnn_shapes_and_no_edge_ablation():
    m = AccountGNN(d_in=5, hidden=8)
    x = torch.randn(4, 5)
    logits, h = m(x, torch.tensor([[0, 1], [1, 2]]))
    assert logits.shape == (4,) and h.shape == (4, 8)
    logits, h = m(x, torch.empty((2, 0), dtype=torch.long))     # ablation: no edges still runs
    assert logits.shape == (4,)


def test_gnn_experiment_end_to_end(pipeline):
    from sqlalchemy import text

    from gnn.experiment import run_gnn_experiment

    out = run_gnn_experiment(pipeline["engine"], folds=3, epochs=15, hidden=16)
    for k in ("baseline_xgboost", "xgboost_plus_gnn", "xgboost_plus_no_graph_ablation", "bootstrap",
              "bootstrap_gnn_vs_ablation", "gnn"):
        assert k in out
    assert out["gnn"]["active_in_training_period"] <= out["gnn"]["accounts"]
    assert 0 <= out["bootstrap"]["probability_gnn_better"] <= 1
    with pipeline["engine"].connect() as c:
        active = c.execute(text("SELECT is_active FROM model_versions WHERE model_name='fraud_xgboost_gnn'")).scalar()
    assert active in (0, False)                                   # registered as a benchmark, never auto-promoted
