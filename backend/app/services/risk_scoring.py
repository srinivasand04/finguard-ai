"""Customer transaction profiling and explainable, configurable customer risk scoring.

The score is a weighted sum of triggered indicators defined in config/risk_config.json.
Each indicator carries its observed value, threshold and a plain-language label, so a
reviewer can see exactly why a score is what it is. Scores are prioritisation signals,
not determinations of wrongdoing.
"""
from __future__ import annotations

import json
import operator

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services.ingestion import bulk_insert, truncate
from ml.data import load_accounts, load_transactions, risk_config

OPS = {">=": operator.ge, ">": operator.gt, "<": operator.lt, "<=": operator.le, "==": operator.eq}


def build_profiles(tx: pd.DataFrame, preds: pd.DataFrame, customers: pd.DataFrame, accounts: pd.DataFrame,
                   high_risk: list[str], as_of: pd.Timestamp, graph: pd.DataFrame | None = None) -> pd.DataFrame:
    """One behavioural profile row per customer (pure function, unit tested)."""
    tx = tx.merge(preds[["transaction_id", "fraud_probability", "anomaly_score", "risk_band"]], on="transaction_id", how="left")
    acc_country = accounts.set_index("account_id")["country"]
    tx["receiver_hr"] = tx["receiver_account_id"].map(acc_country).isin(high_risk)
    tx["sender_hr"] = tx["sender_account_id"].map(acc_country).isin(high_risk)
    tx["night"] = tx["timestamp"].dt.hour < 5
    tx["near_thr"] = tx["amount"].between(9000, 9999.99)
    first_pair = tx.sort_values("timestamp").drop_duplicates(["sender_customer_id", "receiver_customer_id"])
    recent_cut = as_of - pd.Timedelta(days=30)

    out_g = tx.groupby("sender_customer_id")
    in_g = tx.groupby("receiver_customer_id")
    p = pd.DataFrame(index=customers["customer_id"])
    p["tx_out_count"] = out_g.size()
    p["tx_in_count"] = in_g.size()
    p["total_out"] = out_g["amount"].sum()
    p["total_in"] = in_g["amount"].sum()
    p["avg_out_amount"] = out_g["amount"].mean()
    p["max_out_amount"] = out_g["amount"].max()
    p["active_days"] = out_g["timestamp"].apply(lambda s: s.dt.normalize().nunique())
    p["distinct_counterparties"] = out_g["receiver_customer_id"].nunique()
    p["new_counterparties_30d"] = first_pair[first_pair["timestamp"] >= recent_cut].groupby("sender_customer_id").size()
    p["cross_border_share"] = out_g["is_cross_border"].mean()
    hr_any = tx.assign(hr=tx["receiver_hr"] | tx["sender_hr"])
    p["high_risk_country_share"] = pd.concat([
        hr_any[["sender_customer_id", "hr"]].rename(columns={"sender_customer_id": "c"}),
        hr_any[["receiver_customer_id", "hr"]].rename(columns={"receiver_customer_id": "c"}),
    ]).groupby("c")["hr"].mean()
    p["night_tx_share"] = out_g["night"].mean()
    p["near_threshold_count"] = out_g["near_thr"].sum()
    p["pass_through_ratio"] = p["total_out"] / p["total_in"].replace(0, np.nan)

    last30 = tx[tx["timestamp"] >= recent_cut].groupby("sender_customer_id")["amount"].sum()
    prior = tx[tx["timestamp"] < recent_cut]
    months_prior = max((recent_cut - tx["timestamp"].min()).days / 30.0, 1.0)
    prior_monthly = prior.groupby("sender_customer_id")["amount"].sum() / months_prior
    p["out_last_30d"] = last30
    p["out_monthly_baseline"] = prior_monthly
    p["volume_change_ratio"] = (last30 / prior_monthly.replace(0, np.nan))

    involved = pd.concat([
        tx[["sender_customer_id", "transaction_id", "fraud_probability", "anomaly_score", "risk_band"]].rename(columns={"sender_customer_id": "c"}),
        tx[["receiver_customer_id", "transaction_id", "fraud_probability", "anomaly_score", "risk_band"]].rename(columns={"receiver_customer_id": "c"}),
    ]).drop_duplicates(["c", "transaction_id"])
    ig = involved.groupby("c")
    p["high_risk_tx_count"] = ig["risk_band"].apply(lambda s: int((s == "HIGH").sum()))
    p["medium_risk_tx_count"] = ig["risk_band"].apply(lambda s: int((s == "MEDIUM").sum()))
    p["max_fraud_probability"] = ig["fraud_probability"].max()
    p["mean_anomaly_score"] = ig["anomaly_score"].mean()

    c = customers.set_index("customer_id")
    p["pep_flag"] = c["pep_flag"].astype(bool)
    p["relationship_days"] = (as_of - pd.to_datetime(c["onboarding_date"])).dt.days
    p["home_country_high_risk"] = c["country"].isin(high_risk)
    p["n_accounts"] = accounts.groupby("customer_id").size()

    # Phase 2: graph findings (per account -> per customer)
    if graph is not None and not graph.empty:
        gg = graph.groupby("customer_id")
        p["graph_cycle_count"] = gg["cycle_count"].sum()
        p["graph_chain_count"] = gg["chain_count"].sum()
        p["network_risk_score"] = gg["network_risk_score"].max()
        p["neighbour_high_risk_share"] = gg["neighbour_high_risk_share"].max()
        p["pagerank_percentile"] = gg["pagerank_percentile"].max()
        p["betweenness"] = gg["betweenness"].max()
        p[["graph_cycle_count", "graph_chain_count"]] = p[["graph_cycle_count", "graph_chain_count"]].fillna(0).astype(int)
        p["network_risk_score"] = p["network_risk_score"].fillna(0)

    counts = ["tx_out_count", "tx_in_count", "new_counterparties_30d", "near_threshold_count", "high_risk_tx_count",
              "medium_risk_tx_count", "n_accounts", "active_days", "distinct_counterparties"]
    p[counts] = p[counts].fillna(0).astype(int)
    p[["total_out", "total_in", "out_last_30d"]] = p[["total_out", "total_in", "out_last_30d"]].fillna(0)
    return p


def _triggered(rule: dict, row: pd.Series) -> bool:
    v = row.get(rule["metric"])
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return False
    for m, minimum in rule.get("min_metric", {}).items():
        if (row.get(m) or 0) < minimum:
            return False
    if rule["op"] == "between":
        lo, hi = rule["threshold"]
        return lo <= v <= hi
    return bool(OPS[rule["op"]](v, rule["threshold"]))


def score_profile(row: pd.Series, cfg: dict) -> tuple[float, str, list[dict]]:
    rc = cfg["customer_risk"]
    indicators, score = [], 0.0
    for rule in rc["indicators"]:
        if _triggered(rule, row):
            score += rule["weight"]
            v = row.get(rule["metric"])
            indicators.append({
                "code": rule["code"], "label": rule["label"], "metric": rule["metric"],
                "value": v.item() if hasattr(v, "item") else v,
                "threshold": rule["threshold"], "weight": rule["weight"],
            })
    score = min(score, 100.0)
    lv = rc["levels"]
    level = "HIGH" if score >= lv["HIGH"] else "MEDIUM" if score >= lv["MEDIUM"] else "LOW"
    indicators.sort(key=lambda i: -i["weight"])
    return score, level, indicators


def _clean(v):
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 4)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def run_customer_risk(engine: Engine) -> dict:
    cfg = risk_config()
    tx = load_transactions(engine)
    preds = pd.read_sql(text("SELECT transaction_id, fraud_probability, anomaly_score, risk_band FROM fraud_predictions"), engine)
    customers = pd.read_sql(text("SELECT customer_id, country, onboarding_date, pep_flag FROM customers"), engine)
    accounts = load_accounts(engine)
    as_of = tx["timestamp"].max()
    graph = pd.read_sql(text(
        "SELECT g.customer_id, g.cycle_count, g.chain_count, g.neighbour_high_risk_share, g.pagerank_percentile, "
        "g.betweenness, COALESCE(n.risk_score, 0) AS network_risk_score "
        "FROM account_graph_metrics g LEFT JOIN suspicious_networks n ON n.id = g.network_id"), engine)
    profiles = build_profiles(tx, preds, customers, accounts, cfg["high_risk_countries"], as_of, graph)

    rows = []
    for cid, r in profiles.iterrows():
        score, level, ind = score_profile(r, cfg)
        rows.append({"customer_id": cid, "risk_score": score, "risk_level": level,
                     "indicators": json.dumps(ind, default=_clean),
                     "profile": json.dumps({k: _clean(v) for k, v in r.items()}),
                     "scoring_version": cfg["scoring_version"]})
    df = pd.DataFrame(rows)
    truncate(engine, ["customer_risk"])
    bulk_insert(df, "customer_risk", engine)
    summary = {"customers_scored": len(df), "level_counts": df["risk_level"].value_counts().to_dict(),
               "as_of": str(as_of), "scoring_version": cfg["scoring_version"]}
    with Session(engine) as s:
        s.add(AuditLog(actor="system:risk", action="CUSTOMER_RISK_SCORING", entity_type="scoring_version",
                       entity_id=cfg["scoring_version"], details=summary))
        s.commit()
    return summary
