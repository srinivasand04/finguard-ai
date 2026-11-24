"""GNN experiment: does a graph neural network add signal on top of FinGuard's 28 features?

Protocol (everything is decided before looking at the test period):
1. Chronological split, identical to the production model: train 60% / validation 15% / test 25%.
2. The account graph and account labels come ONLY from the training period (no look-ahead).
3. A directed GraphSAGE learns account representations. Predictions are OUT-OF-FOLD: each
   account's score and embedding come from a GNN that never saw that account's label, so
   XGBoost cannot learn to trust a leaked signal.
4. Each transaction gets sender/receiver GNN scores + compressed embeddings (NVIDIA blueprint
   pattern: GNN embeddings -> XGBoost).
5. Baseline XGBoost (28 features) vs XGBoost + GNN features, same hyperparameters, threshold
   tuned on validation, metrics on test, plus a paired bootstrap of the PR-AUC difference.
6. Ablation: the identical network trained with NO edges (each account sees only its own
   features). If it matches the GNN, the gain comes from account summaries, not from the graph.
"""
from __future__ import annotations

import json
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.decomposition import PCA
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from xgboost import XGBClassifier

from app.config import get_settings
from app.models import AuditLog, ModelVersion
from gnn.graph_data import NODE_FEATURES, AccountGraph, build_account_graph
from gnn.model import AccountGNN
from ml.data import load_accounts, load_transactions, risk_config
from ml.features import FEATURES, build_features
from ml.train import _best_threshold, _split, classifier_metrics

EMB_DIMS = 8


def train_gnn_oof(g: AccountGraph, folds: int = 5, epochs: int = 200, hidden: int = 32, lr: float = 0.01,
                  seed: int = 42) -> tuple[np.ndarray, np.ndarray, dict]:
    """Out-of-fold node probabilities and embeddings for every account."""
    torch.manual_seed(seed)
    n = g.x.shape[0]
    prob = np.zeros(n)
    emb = np.zeros((n, hidden))
    inactive_sum_p, inactive_sum_e = np.zeros(n), np.zeros((n, hidden))
    active_idx = np.where(g.active.numpy())[0]
    y_active = g.y.numpy()[active_idx]
    if y_active.sum() < folds or (len(y_active) - y_active.sum()) < folds:
        raise ValueError("Not enough labelled accounts in the training period for the GNN")
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    losses = []
    for fold, (tr_i, ho_i) in enumerate(skf.split(active_idx, y_active)):
        train_nodes = torch.tensor(active_idx[tr_i])
        y_tr = g.y[train_nodes]
        pos_weight = torch.tensor((len(y_tr) - y_tr.sum()) / max(y_tr.sum(), 1))
        model = AccountGNN(g.x.shape[1], hidden)
        opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=5e-4)
        loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        model.train()
        for _ in range(epochs):
            opt.zero_grad()
            logits, _ = model(g.x, g.edge_index)
            loss = loss_fn(logits[train_nodes], y_tr)
            loss.backward()
            opt.step()
        losses.append(round(float(loss), 4))
        model.eval()
        with torch.no_grad():
            logits, h = model(g.x, g.edge_index)
        p, h = torch.sigmoid(logits).numpy(), h.numpy()
        ho_nodes = active_idx[ho_i]
        prob[ho_nodes], emb[ho_nodes] = p[ho_nodes], h[ho_nodes]
        inactive_sum_p += p                                  # accounts with no training-period activity:
        inactive_sum_e += h                                  # average of all fold models (no label exists)
    inactive = ~g.active.numpy()
    prob[inactive], emb[inactive] = inactive_sum_p[inactive] / folds, inactive_sum_e[inactive] / folds
    node_metrics = {
        "accounts": int(n), "active_in_training_period": int(len(active_idx)),
        "positive_accounts": int(y_active.sum()),
        "oof_roc_auc": round(float(roc_auc_score(y_active, prob[active_idx])), 4),
        "oof_pr_auc": round(float(average_precision_score(y_active, prob[active_idx])), 4),
        "base_rate": round(float(y_active.mean()), 4), "final_train_loss_per_fold": losses,
    }
    return prob, emb, node_metrics


def transaction_gnn_features(tx_rows: pd.DataFrame, g: AccountGraph, prob: np.ndarray, emb_pca: np.ndarray) -> pd.DataFrame:
    si = tx_rows["sender_account_id"].map(g.index).to_numpy()
    ri = tx_rows["receiver_account_id"].map(g.index).to_numpy()
    out = {"gnn_sender_prob": prob[si], "gnn_receiver_prob": prob[ri],
           "gnn_max_prob": np.maximum(prob[si], prob[ri])}
    for k in range(emb_pca.shape[1]):
        out[f"gnn_sender_emb_{k}"] = emb_pca[si, k]
        out[f"gnn_receiver_emb_{k}"] = emb_pca[ri, k]
    return pd.DataFrame(out)


def paired_bootstrap(y: np.ndarray, p_base: np.ndarray, p_new: np.ndarray, n: int = 1000, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    deltas, base, new = [], [], []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() == 0:
            continue
        b, w = average_precision_score(y[i], p_base[i]), average_precision_score(y[i], p_new[i])
        base.append(b), new.append(w), deltas.append(w - b)
    d = np.array(deltas)
    return {"resamples": int(len(d)), "pr_auc_delta_mean": round(float(d.mean()), 4),
            "pr_auc_delta_ci95": [round(float(np.percentile(d, 2.5)), 4), round(float(np.percentile(d, 97.5)), 4)],
            "probability_gnn_better": round(float((d > 0).mean()), 3),
            "baseline_pr_auc_ci95": [round(float(np.percentile(base, 2.5)), 4), round(float(np.percentile(base, 97.5)), 4)],
            "gnn_pr_auc_ci95": [round(float(np.percentile(new, 2.5)), 4), round(float(np.percentile(new, 97.5)), 4)]}


def run_gnn_experiment(engine: Engine, folds: int = 5, epochs: int = 200, hidden: int = 32,
                       register: bool = True, seed: int = 42) -> dict:
    s = get_settings()
    cfg = risk_config()
    version = datetime.now().strftime("gnn%Y%m%d-%H%M%S")
    tx = load_transactions(engine)
    accounts = load_accounts(engine)
    feats = build_features(tx, accounts, cfg["high_risk_countries"])
    rows = tx.set_index("transaction_id").loc[feats["transaction_id"]].reset_index()
    y = rows["sim_is_sar"].astype(int).to_numpy()
    tr, va, te = _split(len(rows))
    cutoff = pd.Timestamp(rows["timestamp"].iloc[va.start])

    g = build_account_graph(tx, accounts, cutoff, cfg["high_risk_countries"])
    assert g.max_edge_time is None or g.max_edge_time < cutoff, "graph must only contain training-period edges"
    prob, emb, node_metrics = train_gnn_oof(g, folds=folds, epochs=epochs, hidden=hidden, seed=seed)
    pca = PCA(n_components=EMB_DIMS, random_state=42).fit(emb[g.active.numpy()])
    emb_pca = pca.transform(emb)
    gnn_feats = transaction_gnn_features(rows, g, prob, emb_pca)
    gnn_cols = list(gnn_feats.columns)

    # ablation: same model and features, but no edges -> a per-account MLP
    g_noedge = AccountGraph(**{**g.__dict__, "edge_index": torch.empty((2, 0), dtype=torch.long)})
    prob_ne, emb_ne, node_metrics_ne = train_gnn_oof(g_noedge, folds=folds, epochs=epochs, hidden=hidden, seed=seed)
    pca_ne = PCA(n_components=EMB_DIMS, random_state=42).fit(emb_ne[g.active.numpy()])
    ne_feats = transaction_gnn_features(rows, g, prob_ne, pca_ne.transform(emb_ne))

    X_base = feats[FEATURES].to_numpy(dtype=float)
    X_gnn = np.hstack([X_base, gnn_feats.to_numpy(dtype=float)])
    X_ne = np.hstack([X_base, ne_feats.to_numpy(dtype=float)])
    pos_w = float((y[tr] == 0).sum() / max(y[tr].sum(), 1))
    params = dict(n_estimators=400, max_depth=5, learning_rate=0.05, subsample=0.9, colsample_bytree=0.8,
                  min_child_weight=3, scale_pos_weight=pos_w, eval_metric="aucpr", random_state=42, n_jobs=-1)
    results, preds = {}, {}
    for name, X in (("baseline_xgboost", X_base), ("xgboost_plus_gnn", X_gnn),
                    ("xgboost_plus_no_graph_ablation", X_ne)):
        m = XGBClassifier(**params).fit(X[tr], y[tr], eval_set=[(X[va], y[va])], verbose=False)
        thr = _best_threshold(y[va], m.predict_proba(X[va])[:, 1])
        preds[name] = m.predict_proba(X[te])[:, 1]
        results[name] = classifier_metrics(y[te], preds[name], thr)
        if name == "xgboost_plus_gnn":
            gain = m.get_booster().get_score(importance_type="gain")
            names = FEATURES + gnn_cols
            importance = dict(sorted({names[int(k[1:])]: round(v, 3) for k, v in gain.items()}.items(), key=lambda kv: -kv[1]))
            final_model = m
    boot = paired_bootstrap(y[te], preds["baseline_xgboost"], preds["xgboost_plus_gnn"])
    boot_ablation = paired_bootstrap(y[te], preds["baseline_xgboost"], preds["xgboost_plus_no_graph_ablation"])
    boot_graph_vs_ablation = paired_bootstrap(y[te], preds["xgboost_plus_no_graph_ablation"], preds["xgboost_plus_gnn"])
    gnn_in_top10 = [f for f in list(importance)[:10] if f.startswith("gnn_")]

    out_dir = s.models_dir / "gnn"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"xgboost_gnn_{version}.joblib"
    joblib.dump({"xgboost": final_model, "features": FEATURES + gnn_cols, "pca": pca, "node_prob": prob,
                 "node_index": g.index, "cutoff": str(cutoff), "version": version}, artifact)
    summary = {
        "version": version, "seed": seed, "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "protocol": "chronological 60/15/25; graph + labels from training period only; out-of-fold GNN features",
        "graph": {"cutoff": str(cutoff), "nodes": int(g.x.shape[0]), "edges": int(g.edge_index.shape[1]),
                  "node_features": NODE_FEATURES},
        "gnn": {"architecture": "directed GraphSAGE, 2 layers", "hidden": hidden, "folds": folds, "epochs": epochs,
                "embedding_pca_dims": EMB_DIMS, **node_metrics},
        "test": {"rows": te.stop - te.start, "positives": int(y[te].sum())},
        "baseline_xgboost": results["baseline_xgboost"],
        "xgboost_plus_gnn": results["xgboost_plus_gnn"],
        "xgboost_plus_no_graph_ablation": results["xgboost_plus_no_graph_ablation"],
        "ablation_node_metrics": node_metrics_ne,
        "bootstrap": boot,
        "bootstrap_ablation_vs_baseline": boot_ablation,
        "bootstrap_gnn_vs_ablation": boot_graph_vs_ablation,
        "gnn_features_in_top10_importance": gnn_in_top10,
        "top_features": list(importance)[:12],
    }
    (out_dir / "gnn_evaluation_latest.json").write_text(json.dumps(summary, indent=2, default=str))
    if register:
        with Session(engine) as session:
            mv = ModelVersion(
                model_name="fraud_xgboost_gnn", version=version, model_type="supervised+graph",
                algorithm="Directed GraphSAGE (PyTorch Geometric) + XGBClassifier", artifact_path=str(artifact),
                features=FEATURES + gnn_cols,
                hyperparameters={"gnn": {"hidden": hidden, "folds": folds, "epochs": epochs, "lr": 0.01},
                                 "xgboost": {k: v for k, v in params.items() if k != "n_jobs"}},
                metrics={**results["xgboost_plus_gnn"],
                         "baseline_pr_auc": results["baseline_xgboost"]["pr_auc"],
                         "pr_auc_delta_mean": boot["pr_auc_delta_mean"],
                         "pr_auc_delta_ci95": boot["pr_auc_delta_ci95"],
                         "probability_gnn_better": boot["probability_gnn_better"],
                         "no_graph_ablation_pr_auc": results["xgboost_plus_no_graph_ablation"]["pr_auc"],
                         "probability_graph_beats_ablation": boot_graph_vs_ablation["probability_gnn_better"],
                         "note": "Experimental benchmark - not used for live scoring."},
                feature_importance=importance, training_data={"cutoff": str(cutoff), **summary["test"],
                                                              "graph_nodes": summary["graph"]["nodes"],
                                                              "graph_edges": summary["graph"]["edges"]},
                is_active=False)
            session.add(mv)
            session.add(AuditLog(actor="system:gnn", action="GNN_EXPERIMENT", entity_type="model_version",
                                 entity_id=version, details={k: summary[k] for k in ("bootstrap", "test")}))
            session.commit()
    return summary
