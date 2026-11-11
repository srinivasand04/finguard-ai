"""Build the account money-flow graph.

Nodes are accounts (with customer, country, segment attributes); a directed edge
A -> B aggregates every transaction A sent to B (count, value, first/last time and
the highest ML risk seen on that relationship).
"""
from __future__ import annotations

import networkx as nx
import pandas as pd


def aggregate_edges(tx: pd.DataFrame) -> pd.DataFrame:
    """tx needs sender/receiver account ids, amount, timestamp, is_cross_border, risk_score, risk_band."""
    t = tx.assign(high=(tx["risk_band"] == "HIGH").astype(int), risk_score=tx["risk_score"].fillna(0))
    g = t.groupby(["sender_account_id", "receiver_account_id"], sort=False)
    edges = g.agg(tx_count=("amount", "size"), total_amount=("amount", "sum"), first_ts=("timestamp", "min"),
                  last_ts=("timestamp", "max"), max_risk_score=("risk_score", "max"),
                  high_risk_count=("high", "sum"), is_cross_border=("is_cross_border", "max")).reset_index()
    edges = edges.rename(columns={"sender_account_id": "src_account_id", "receiver_account_id": "dst_account_id"})
    edges["total_amount"] = edges["total_amount"].round(2)
    return edges


def build_graph(edges: pd.DataFrame, accounts: pd.DataFrame | None = None) -> nx.DiGraph:
    G = nx.DiGraph()
    if accounts is not None:
        for a in accounts.itertuples():
            G.add_node(a.account_id, customer_id=a.customer_id, country=a.country, segment=a.segment)
    for e in edges.itertuples():
        G.add_edge(e.src_account_id, e.dst_account_id, tx_count=int(e.tx_count), total_amount=float(e.total_amount),
                   high_risk_count=int(e.high_risk_count), max_risk_score=float(e.max_risk_score))
    return G
