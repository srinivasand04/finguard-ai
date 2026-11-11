"""Train and register the Phase 1 detection models.

* fraud_xgboost            - supervised, production scorer (native per-feature contributions)
* fraud_random_forest      - supervised benchmark
* anomaly_isolation_forest - unsupervised, label-free

Split is chronological (no shuffling): train 0-60%, validation 60-75% (threshold
selection), test 75-100% (reported metrics). Labels come from the simulator's
SAR flags and are used for training/evaluation only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from xgboost import XGBClassifier

from app.config import get_settings
from app.models import AuditLog, ModelVersion
from ml.data import load_accounts, load_transactions, risk_config
from ml.features import FEATURES, build_features


def _split(n: int):
    a, b = int(n * 0.60), int(n * 0.75)
    return slice(0, a), slice(a, b), slice(b, n)


def _best_threshold(y, p) -> float:
    prec, rec, thr = precision_recall_curve(y, p)
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
    return float(thr[np.argmax(f1[:-1])]) if len(thr) else 0.5


def _top_k_metrics(y, score, fracs=(0.005, 0.01, 0.02)) -> dict:
    order = np.argsort(-score)
    out = {}
    for f in fracs:
        k = max(1, int(len(y) * f))
        hit = y[order[:k]].sum()
        out[f"precision_at_top_{f:.1%}"] = round(float(hit / k), 4)
        out[f"recall_at_top_{f:.1%}"] = round(float(hit / max(y.sum(), 1)), 4)
    return out


def classifier_metrics(y, p, threshold) -> dict:
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "threshold": round(float(threshold), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "base_rate": round(float(y.mean()), 5),
        **_top_k_metrics(y, p),
    }


def _register(session: Session, **kw) -> ModelVersion:
    mv = ModelVersion(**kw)
    session.add(mv)
    session.flush()
    return mv


def train_all(engine: Engine) -> dict:
    settings = get_settings()
    cfg = risk_config()
    version = datetime.now().strftime("v%Y%m%d-%H%M%S")
    accounts = load_accounts(engine)
    tx = load_transactions(engine)
    feats = build_features(tx, accounts, cfg["high_risk_countries"])
    labels = tx.set_index("transaction_id").loc[feats["transaction_id"], "sim_is_sar"].astype(int).to_numpy()
    X = feats[FEATURES].to_numpy(dtype=float)
    tr, va, te = _split(len(X))
    ts = tx.set_index("transaction_id").loc[feats["transaction_id"], "timestamp"].to_numpy()
    data_hash = hashlib.sha256(pd.util.hash_pandas_object(feats[["transaction_id"]], index=False).values.tobytes()).hexdigest()[:16]
    training_data = {
        "rows_total": int(len(X)), "positives_total": int(labels.sum()),
        "train": {"rows": tr.stop - tr.start, "positives": int(labels[tr].sum()), "from": str(ts[tr.start]), "to": str(ts[tr.stop - 1])},
        "validation": {"rows": va.stop - va.start, "positives": int(labels[va].sum()), "from": str(ts[va.start]), "to": str(ts[va.stop - 1])},
        "test": {"rows": te.stop - te.start, "positives": int(labels[te].sum()), "from": str(ts[te.start]), "to": str(ts[te.stop - 1])},
        "split": "chronological 60/15/25", "feature_snapshot_hash": data_hash,
    }
    out_fraud = settings.models_dir / "fraud"
    out_anom = settings.models_dir / "anomaly"
    out_fraud.mkdir(parents=True, exist_ok=True)
    out_anom.mkdir(parents=True, exist_ok=True)
    summary = {"version": version, "training_data": training_data, "models": {}}

    pos_w = float((labels[tr] == 0).sum() / max(labels[tr].sum(), 1))
    # ---------------- XGBoost
    xgb_params = dict(n_estimators=400, max_depth=5, learning_rate=0.05, subsample=0.9, colsample_bytree=0.8,
                      min_child_weight=3, scale_pos_weight=pos_w, eval_metric="aucpr", random_state=42, n_jobs=-1)
    xgb = XGBClassifier(**xgb_params)
    xgb.fit(X[tr], labels[tr], eval_set=[(X[va], labels[va])], verbose=False)
    thr = _best_threshold(labels[va], xgb.predict_proba(X[va])[:, 1])
    xgb_metrics = classifier_metrics(labels[te], xgb.predict_proba(X[te])[:, 1], thr)
    gain = xgb.get_booster().get_score(importance_type="gain")
    xgb_imp = {FEATURES[int(k[1:])]: round(v, 3) for k, v in gain.items()}
    xgb_imp = dict(sorted(xgb_imp.items(), key=lambda kv: -kv[1]))
    path = out_fraud / f"fraud_xgboost_{version}.joblib"
    joblib.dump({"model": xgb, "features": FEATURES, "threshold": thr, "version": version}, path)

    # ---------------- Random Forest benchmark
    rf_params = dict(n_estimators=300, max_depth=14, min_samples_leaf=3, class_weight="balanced_subsample",
                     n_jobs=-1, random_state=42)
    rf = RandomForestClassifier(**rf_params).fit(X[tr], labels[tr])
    rf_thr = _best_threshold(labels[va], rf.predict_proba(X[va])[:, 1])
    rf_metrics = classifier_metrics(labels[te], rf.predict_proba(X[te])[:, 1], rf_thr)
    rf_imp = dict(sorted({f: round(float(v), 4) for f, v in zip(FEATURES, rf.feature_importances_)}.items(), key=lambda kv: -kv[1]))
    rf_path = out_fraud / f"fraud_random_forest_{version}.joblib"
    joblib.dump({"model": rf, "features": FEATURES, "threshold": rf_thr, "version": version}, rf_path)

    # ---------------- Isolation Forest (label-free)
    if_params = dict(n_estimators=300, max_samples=4096, contamination="auto", random_state=42, n_jobs=-1)
    iso = IsolationForest(**if_params).fit(X[tr])
    train_scores = -iso.score_samples(X[tr])
    reference = np.quantile(train_scores, np.linspace(0, 1, 1001))  # for percentile normalisation
    te_scores = -iso.score_samples(X[te])
    iso_metrics = {
        "roc_auc_vs_sar_labels": round(float(roc_auc_score(labels[te], te_scores)), 4),
        "pr_auc_vs_sar_labels": round(float(average_precision_score(labels[te], te_scores)), 4),
        "base_rate": round(float(labels[te].mean()), 5),
        **_top_k_metrics(labels[te], te_scores),
        "note": "Unsupervised: labels used only to evaluate, never to fit.",
    }
    iso_path = out_anom / f"anomaly_isolation_forest_{version}.joblib"
    joblib.dump({"model": iso, "features": FEATURES, "reference_quantiles": reference, "version": version}, iso_path)

    with Session(engine) as s:
        s.query(ModelVersion).update({ModelVersion.is_active: False})
        common = dict(version=version, features=FEATURES, training_data=training_data)
        m1 = _register(s, model_name="fraud_xgboost", model_type="supervised", algorithm="XGBClassifier",
                       artifact_path=str(path), hyperparameters=xgb_params, metrics=xgb_metrics,
                       feature_importance=xgb_imp, is_active=True, **common)
        m2 = _register(s, model_name="fraud_random_forest", model_type="supervised", algorithm="RandomForestClassifier",
                       artifact_path=str(rf_path), hyperparameters=rf_params, metrics=rf_metrics,
                       feature_importance=rf_imp, is_active=False, **common)
        m3 = _register(s, model_name="anomaly_isolation_forest", model_type="unsupervised", algorithm="IsolationForest",
                       artifact_path=str(iso_path), hyperparameters=if_params, metrics=iso_metrics,
                       feature_importance={}, is_active=True, **common)
        s.add(AuditLog(actor="system:training", action="MODEL_TRAINED", entity_type="model_version",
                       entity_id=version, details={"model_ids": [m1.id, m2.id, m3.id]}))
        s.commit()
    summary["models"] = {"fraud_xgboost": xgb_metrics, "fraud_random_forest": rf_metrics, "anomaly_isolation_forest": iso_metrics}
    summary["top_features_xgboost"] = list(xgb_imp)[:10]
    (settings.models_dir / f"evaluation_{version}.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
