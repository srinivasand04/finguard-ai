"""Graph analysis job: build graph -> metrics -> patterns -> networks -> store -> evaluate."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog
from app.services.ingestion import bulk_insert, truncate
from graph.analytics import account_metrics, find_networks
from graph.builder import aggregate_edges, build_graph
from graph.patterns import FlowConfig, find_flow_patterns
from ml.data import load_accounts

GRAPH_TABLES = ["graph_patterns", "suspicious_networks", "account_graph_metrics", "graph_edges"]


def _load(engine: Engine) -> pd.DataFrame:
    df = pd.read_sql(text("""
        SELECT t.transaction_id, t.sender_account_id, t.receiver_account_id, t.amount, t.timestamp,
               t.is_cross_border, t.sim_is_sar, t.sim_alert_id, t.sim_alert_type, p.risk_score, p.risk_band
        FROM transactions t LEFT JOIN fraud_predictions p ON p.transaction_id = t.transaction_id"""), engine)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["amount"] = df["amount"].astype(float)
    df["is_cross_border"] = df["is_cross_border"].astype(bool)
    df["sim_is_sar"] = df["sim_is_sar"].astype(bool)
    return df


def evaluate(tx: pd.DataFrame, accounts: pd.DataFrame, patterns: list[dict], networks: list[dict]) -> dict:
    """Score detection against simulator ground truth (never used to *find* anything)."""
    sar_tx = set(tx.loc[tx["sim_is_sar"], "transaction_id"])
    out: dict = {"patterns": {}, "typology_coverage": {}, "networks": {}}
    for kind in ("CYCLE", "LAYERING_CHAIN"):
        ps = [p for p in patterns if p["pattern_type"] == kind]
        hits = sum(sum(t in sar_tx for t in p["transaction_ids"]) / p["hops"] >= 0.5 for p in ps)
        out["patterns"][kind] = {"found": len(ps), "mostly_sar": hits,
                                 "precision": round(hits / len(ps), 4) if ps else None}
    covered_tx = {t for p in patterns for t in p["transaction_ids"]}
    in_network = {a for n in networks for a in n["accounts"]}
    alerts = tx[tx["sim_alert_id"].notna()].groupby("sim_alert_id").agg(
        typ=("sim_alert_type", "first"), txs=("transaction_id", list),
        accs=("sender_account_id", lambda s: set(s)), recv=("receiver_account_id", lambda s: set(s)))
    for typ, g in alerts.groupby("typ"):
        by_pattern = sum(any(t in covered_tx for t in row.txs) for row in g.itertuples())
        by_network = sum(len((row.accs | row.recv) & in_network) / len(row.accs | row.recv) >= 0.5 for row in g.itertuples())
        out["typology_coverage"][typ] = {"patterns_simulated": len(g),
                                         "detected_by_flow_patterns": round(by_pattern / len(g), 3),
                                         "mostly_inside_networks": round(by_network / len(g), 3)}
    sar_acc = set(accounts.loc[accounts["sim_is_sar"].astype(bool), "account_id"])
    out["networks"] = {
        "found": len(networks), "accounts_in_networks": len(in_network),
        "account_precision": round(len(in_network & sar_acc) / len(in_network), 4) if in_network else None,
        "sar_account_recall": round(len(in_network & sar_acc) / len(sar_acc), 4) if sar_acc else None,
        "by_level": dict(Counter(n["risk_level"] for n in networks)),
    }
    return out


def run_graph_analysis(engine: Engine, cfg: FlowConfig | None = None) -> dict:
    started = datetime.now()
    version = started.strftime("g%Y%m%d-%H%M%S")
    tx = _load(engine)
    accounts = load_accounts(engine)
    acc_customer = dict(zip(accounts["account_id"], accounts["customer_id"]))

    edges = aggregate_edges(tx)
    G = build_graph(edges, accounts)
    high_risk_acc = set(tx.loc[tx["risk_band"] == "HIGH", "sender_account_id"]) | set(tx.loc[tx["risk_band"] == "HIGH", "receiver_account_id"])
    metrics = account_metrics(G, high_risk_acc)
    patterns = find_flow_patterns(tx, cfg)
    networks = find_networks(G, patterns, edges)

    # cross-link: which network each account / pattern belongs to, and pattern counts per account
    net_of = {a: n["id"] for n in networks for a in n["accounts"]}
    cyc, chn = Counter(), Counter()
    for p in patterns:
        (cyc if p["pattern_type"] == "CYCLE" else chn).update(set(p["account_ids"]))
        nets = Counter(net_of.get(a) for a in p["account_ids"] if a in net_of)
        p["network_id"] = nets.most_common(1)[0][0] if nets else None
        p["customer_ids"] = sorted({acc_customer[a] for a in p["account_ids"]})
    metrics["customer_id"] = metrics["account_id"].map(acc_customer)
    metrics["cycle_count"] = metrics["account_id"].map(cyc).fillna(0).astype(int)
    metrics["chain_count"] = metrics["account_id"].map(chn).fillna(0).astype(int)
    metrics["network_id"] = metrics["account_id"].map(net_of).astype("Int64")
    metrics["graph_version"] = version

    truncate(engine, GRAPH_TABLES)
    bulk_insert(edges, "graph_edges", engine)
    bulk_insert(metrics[["account_id", "customer_id", "in_degree", "out_degree", "degree_centrality", "pagerank",
                         "pagerank_percentile", "betweenness", "community_id", "community_size", "cycle_count",
                         "chain_count", "network_id", "neighbour_high_risk_share", "graph_version"]],
                "account_graph_metrics", engine)
    if patterns:
        pdf = pd.DataFrame(patterns)
        for c in ("account_ids", "customer_ids", "transaction_ids"):
            pdf[c] = pdf[c].map(json.dumps)
        pdf["network_id"] = pdf["network_id"].astype("Int64")
        bulk_insert(pdf[["pattern_type", "account_ids", "customer_ids", "transaction_ids", "hops", "start_amount",
                         "end_amount", "start_ts", "end_ts", "duration_hours", "score", "network_id"]],
                    "graph_patterns", engine)
    if networks:
        ndf = pd.DataFrame([{**n, "account_ids": json.dumps(n["accounts"]),
                             "customer_ids": json.dumps(sorted({acc_customer[a] for a in n["accounts"]})),
                             "hubs": json.dumps(n["hubs"]), "typology_hints": json.dumps(n["typology_hints"])}
                            for n in networks])
        bulk_insert(ndf[["id", "account_ids", "customer_ids", "size", "edge_count", "total_value", "high_risk_tx_count",
                         "cycle_count", "chain_count", "cross_border_share", "hubs", "typology_hints", "risk_score",
                         "risk_level"]], "suspicious_networks", engine)

    evaluation = evaluate(tx, accounts, patterns, networks)
    summary = {
        "graph_version": version,
        "duration_seconds": round((datetime.now() - started).total_seconds(), 1),
        "nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
        "communities": int(metrics["community_id"].nunique()),
        "patterns": dict(Counter(p["pattern_type"] for p in patterns)),
        "networks": dict(Counter(n["risk_level"] for n in networks)),
        "flow_config": (cfg or FlowConfig()).__dict__,
        "evaluation": evaluation,
    }
    out = get_settings().models_dir / "graph"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"graph_evaluation_{version}.json").write_text(json.dumps(summary, indent=2, default=str))
    with Session(engine) as s:
        s.add(AuditLog(actor="system:graph", action="GRAPH_ANALYSIS", entity_type="graph_version", entity_id=version,
                       details=json.loads(json.dumps(summary, default=str))))
        s.commit()
    return summary
