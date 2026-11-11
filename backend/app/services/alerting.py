"""Alert generation from ML scores, anomaly scores, rules and customer risk.

Alerts are prompts for human review. Every alert lists the reasons that raised it.
"""
from __future__ import annotations

import json

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.ingestion import bulk_insert, truncate
from ml.data import risk_config


def _severity(score: float) -> str:
    return "CRITICAL" if score >= 85 else "HIGH" if score >= 60 else "MEDIUM"


def detect_structuring(tx: pd.DataFrame, lo: float, hi: float, min_count: int, window_days: int) -> pd.DataFrame:
    """Accounts with >= min_count near-threshold amounts inside any rolling window."""
    near = tx[(tx["amount"] >= lo) & (tx["amount"] < hi)].sort_values("timestamp")
    hits = []
    for acc, g in near.groupby("sender_account_id"):
        times = g["timestamp"].to_numpy()
        j = 0
        for i in range(len(times)):
            while times[i] - times[j] > pd.Timedelta(days=window_days).to_timedelta64():
                j += 1
            if i - j + 1 >= min_count:
                w = g.iloc[j:i + 1]
                hits.append({"account_id": acc, "customer_id": g["sender_customer_id"].iloc[0],
                             "transaction_id": int(w["transaction_id"].iloc[-1]), "count": len(w),
                             "total": float(w["amount"].sum()), "tx_ids": [int(x) for x in w["transaction_id"]]})
                break
    return pd.DataFrame(hits)


def generate_alerts(engine: Engine) -> dict:
    cfg = risk_config()["alerts"]
    q = text("""
        SELECT t.transaction_id, t.sender_account_id, t.sender_customer_id, t.amount, t.timestamp,
               p.fraud_probability, p.anomaly_score, p.risk_score, p.risk_band, p.top_factors
        FROM transactions t JOIN fraud_predictions p ON p.transaction_id = t.transaction_id""")
    df = pd.read_sql(q, engine)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["amount"] = df["amount"].astype(float)
    rows = []

    hi = df[df["risk_band"] == cfg["transaction_risk_band"]]
    for r in hi.itertuples():
        factors = json.loads(r.top_factors) if isinstance(r.top_factors, str) else r.top_factors
        rows.append({"alert_type": "HIGH_RISK_TRANSACTION", "source": "ML_MODEL", "severity": _severity(r.risk_score),
                     "customer_id": r.sender_customer_id, "account_id": r.sender_account_id,
                     "transaction_id": r.transaction_id, "score": round(r.risk_score, 2),
                     "reasons": [f"ML suspicion probability {r.fraud_probability:.2f}"] + [f["description"] for f in factors]})

    anom = df[(df["anomaly_score"] >= cfg["anomaly_percentile"]) & (df["risk_band"] != cfg["transaction_risk_band"])]
    for r in anom.itertuples():
        rows.append({"alert_type": "ANOMALOUS_TRANSACTION", "source": "ANOMALY_MODEL", "severity": "MEDIUM",
                     "customer_id": r.sender_customer_id, "account_id": r.sender_account_id,
                     "transaction_id": r.transaction_id, "score": round(100 * r.anomaly_score, 2),
                     "reasons": [f"Isolation Forest: more unusual than {100 * r.anomaly_score:.1f}% of reference transactions"]})

    lo, hi_thr = cfg["near_threshold_range"]
    st = detect_structuring(df, lo, hi_thr, cfg["structuring_min_count"], cfg["structuring_window_days"])
    for r in st.itertuples():
        rows.append({"alert_type": "POSSIBLE_STRUCTURING", "source": "RULE", "severity": "HIGH",
                     "customer_id": r.customer_id, "account_id": r.account_id, "transaction_id": r.transaction_id,
                     "score": 70.0,
                     "reasons": [f"{r.count} transactions between {lo:,.0f} and {hi_thr:,.0f} within {cfg['structuring_window_days']} days "
                                 f"(total {r.total:,.2f})", f"Transactions: {r.tx_ids}"]})

    cr = pd.read_sql(text("SELECT customer_id, risk_score, indicators FROM customer_risk WHERE risk_level = 'HIGH'"), engine)
    for r in cr.itertuples():
        ind = json.loads(r.indicators) if isinstance(r.indicators, str) else r.indicators
        rows.append({"alert_type": "HIGH_RISK_CUSTOMER", "source": "CUSTOMER_RISK", "severity": _severity(r.risk_score),
                     "customer_id": r.customer_id, "account_id": None, "transaction_id": None,
                     "score": float(r.risk_score), "reasons": [i["label"] for i in ind]})

    out = pd.DataFrame(rows)
    out["status"] = "OPEN"
    out["reasons"] = out["reasons"].map(json.dumps)
    out["transaction_id"] = out["transaction_id"].astype("Int64")
    truncate(engine, ["alerts"])
    bulk_insert(out, "alerts", engine)
    summary = {"alerts": len(out), "by_type": out["alert_type"].value_counts().to_dict(),
               "by_severity": out["severity"].value_counts().to_dict()}
    with Session(engine) as s:
        s.add(AuditLog(actor="system:alerting", action="ALERTS_GENERATED", entity_type="alerts", entity_id=None, details=summary))
        s.commit()
    return summary
