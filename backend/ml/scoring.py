"""Batch and near-real-time transaction scoring with explanations."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import AuditLog, ModelVersion
from app.services.ingestion import bulk_insert, truncate
from ml.data import load_accounts, load_transactions, risk_config
from ml.features import FEATURES, build_features, describe_factor


@dataclass
class ActiveModels:
    fraud_id: int
    fraud: dict
    anomaly_id: int
    anomaly: dict


def load_active_models(engine: Engine) -> ActiveModels:
    with Session(engine) as s:
        rows = s.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))).all()
    by_name = {r.model_name: r for r in rows}
    if "fraud_xgboost" not in by_name or "anomaly_isolation_forest" not in by_name:
        raise RuntimeError("No active models registered - run `python -m app.cli train` first")
    f, a = by_name["fraud_xgboost"], by_name["anomaly_isolation_forest"]
    return ActiveModels(f.id, _load_artifact(f.artifact_path), a.id, _load_artifact(a.artifact_path))


@lru_cache(maxsize=8)
def _load_artifact(path: str) -> dict:
    return joblib.load(path)


def anomaly_percentile(raw: np.ndarray, reference: np.ndarray) -> np.ndarray:
    return np.searchsorted(reference, raw, side="right") / len(reference)


def risk_from(prob: np.ndarray, anomaly_pct: np.ndarray, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    c = cfg["transaction_risk"]
    floor = c["anomaly_percentile_floor"]
    anomaly_component = np.clip((anomaly_pct - floor) / (1 - floor), 0, 1)
    score = 100 * (c["fraud_weight"] * prob + c["anomaly_weight"] * anomaly_component)
    bands = np.where(score >= c["bands"]["HIGH"], "HIGH", np.where(score >= c["bands"]["MEDIUM"], "MEDIUM", "LOW"))
    return np.round(score, 2), bands


def score_features(feats: pd.DataFrame, models: ActiveModels, cfg: dict, top_n: int = 3) -> pd.DataFrame:
    X = feats[FEATURES].to_numpy(dtype=float)
    clf = models.fraud["model"]
    prob = clf.predict_proba(X)[:, 1]
    booster = clf.get_booster()
    # Fast approximate (Saabas) contributions for everything, exact TreeSHAP for rows that matter
    # (prob >= 1%), which keeps batch scoring quick while flagged transactions get exact explanations.
    contribs = booster.predict(xgb.DMatrix(X), pred_contribs=True, approx_contribs=True)[:, :-1]  # drop bias column
    exact_rows = np.where(prob >= 0.01)[0]
    if len(exact_rows):
        contribs[exact_rows] = booster.predict(xgb.DMatrix(X[exact_rows]), pred_contribs=True)[:, :-1]
    raw = -models.anomaly["model"].score_samples(X)
    pct = anomaly_percentile(raw, models.anomaly["reference_quantiles"])
    score, band = risk_from(prob, pct, cfg)

    top_idx = np.argsort(-contribs, axis=1)[:, :top_n]
    factors = []
    for i in range(len(X)):
        row = []
        for j in top_idx[i]:
            if contribs[i, j] <= 0:
                continue
            row.append({"feature": FEATURES[j], "value": round(float(X[i, j]), 4),
                        "contribution": round(float(contribs[i, j]), 4),
                        "description": describe_factor(FEATURES[j], float(X[i, j]))})
        factors.append(row)
    return pd.DataFrame({
        "transaction_id": feats["transaction_id"].to_numpy(),
        "fraud_probability": np.round(prob, 5),
        "anomaly_score": np.round(pct, 4),
        "risk_score": score,
        "risk_band": band,
        "top_factors": factors,
    })


def score_all(engine: Engine) -> dict:
    cfg = risk_config()
    models = load_active_models(engine)
    accounts = load_accounts(engine)
    tx = load_transactions(engine)
    feats = build_features(tx, accounts, cfg["high_risk_countries"])
    scored = score_features(feats, models, cfg)
    scored["model_version_id"] = models.fraud_id
    scored["anomaly_model_version_id"] = models.anomaly_id
    scored["top_factors"] = scored["top_factors"].map(json.dumps)
    truncate(engine, ["alerts", "fraud_predictions"])
    bulk_insert(scored[["transaction_id", "model_version_id", "anomaly_model_version_id", "fraud_probability",
                        "anomaly_score", "risk_score", "risk_band", "top_factors"]], "fraud_predictions", engine)
    summary = {"scored": int(len(scored)), "band_counts": scored["risk_band"].value_counts().to_dict(),
               "model_version_id": models.fraud_id}
    with Session(engine) as s:
        s.add(AuditLog(actor="system:scoring", action="BATCH_SCORING", entity_type="model_version",
                       entity_id=str(models.fraud_id), details=summary))
        s.commit()
    return summary


def score_single(engine: Engine, tx: dict) -> dict:
    """Near-real-time scoring of a new (not yet stored) transaction against stored history.

    Pulls the history of both accounts, appends the new transaction and runs the exact
    same feature pipeline as batch scoring, then returns the new row's score.
    """
    cfg = risk_config()
    models = load_active_models(engine)
    accounts = load_accounts(engine)
    known = set(accounts["account_id"])
    for k in ("sender_account_id", "receiver_account_id"):
        if tx[k] not in known:
            raise KeyError(f"Unknown account {tx[k]}")
    hist = load_transactions(engine, [tx["sender_account_id"], tx["receiver_account_id"]])
    acc = accounts.set_index("account_id")
    new = pd.DataFrame([{
        "transaction_id": -1,
        "sender_account_id": tx["sender_account_id"],
        "receiver_account_id": tx["receiver_account_id"],
        "tx_type": tx["tx_type"],
        "amount": float(tx["amount"]),
        "timestamp": pd.Timestamp(tx["timestamp"]).tz_localize(None),
        "is_cross_border": acc.at[tx["sender_account_id"], "country"] != acc.at[tx["receiver_account_id"], "country"],
    }])
    hist = hist[hist["timestamp"] < new["timestamp"].iloc[0]]
    frame = pd.concat([hist[new.columns], new], ignore_index=True)
    feats = build_features(frame, accounts, cfg["high_risk_countries"])
    row = feats[feats["transaction_id"] == -1]
    out = score_features(row, models, cfg, top_n=5).iloc[0].to_dict()
    out.pop("transaction_id")
    out["features"] = {k: round(float(row.iloc[0][k]), 4) for k in FEATURES}
    out["model_version_id"] = models.fraud_id
    out["is_cross_border"] = bool(new["is_cross_border"].iloc[0])
    return out
