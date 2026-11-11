"""Graph metrics and suspicious network identification."""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd


def account_metrics(G: nx.DiGraph, high_risk_accounts: set[str], seed: int = 42) -> pd.DataFrame:
    """Centrality, community and neighbourhood-risk metrics for every account node.

    * degree centrality  - how many distinct counterparties
    * PageRank           - weighted by value: where money accumulates
    * betweenness        - brokers on many shortest paths (sampled k-node approximation)
    * Louvain community  - densely connected groups (undirected, weighted by tx count)
    """
    n = G.number_of_nodes()
    deg = nx.degree_centrality(G)
    pr = nx.pagerank(G, weight="total_amount", alpha=0.85)
    btw = nx.betweenness_centrality(G, k=min(400, n), seed=seed, normalized=True) if n > 2 else {v: 0.0 for v in G}
    U = G.to_undirected()
    comms = nx.community.louvain_communities(U, weight="tx_count", seed=seed) if U.number_of_edges() else [{v} for v in G]
    comm_of = {v: cid for cid, c in enumerate(sorted(comms, key=len, reverse=True)) for v in c}
    comm_size = {cid: len(c) for cid, c in enumerate(sorted(comms, key=len, reverse=True))}

    rows = []
    for v in G.nodes:
        nbrs = set(G.predecessors(v)) | set(G.successors(v))
        rows.append({
            "account_id": v,
            "in_degree": G.in_degree(v), "out_degree": G.out_degree(v),
            "degree_centrality": round(deg[v], 6), "pagerank": pr[v], "betweenness": round(btw[v], 6),
            "community_id": comm_of[v], "community_size": comm_size[comm_of[v]],
            "neighbour_high_risk_share": round(len(nbrs & high_risk_accounts) / len(nbrs), 4) if nbrs else 0.0,
        })
    df = pd.DataFrame(rows)
    df["pagerank_percentile"] = df["pagerank"].rank(pct=True).round(4)
    return df


def find_networks(G: nx.DiGraph, patterns: list[dict], edges: pd.DataFrame,
                  min_size: int = 3, max_size: int = 60, seed: int = 42) -> list[dict]:
    """Suspicious networks = connected groups in the *risk subgraph*.

    The risk subgraph keeps only edges that are part of a time-ordered pattern or that
    carried at least one HIGH-risk transaction. Oversized components (usually glued
    together by a busy business account) are split with Louvain.
    """
    R = nx.DiGraph()
    for p in patterns:
        acc = p["account_ids"]
        for a, b in zip(acc[:-1], acc[1:]):
            R.add_edge(a, b)
    for e in edges[edges["high_risk_count"] > 0].itertuples():
        R.add_edge(e.src_account_id, e.dst_account_id)

    groups: list[set] = []

    def split(nodes: set, depth: int = 0) -> None:
        """Recursively Louvain-split until every group is small enough for a human to review."""
        if len(nodes) < min_size:
            return
        if len(nodes) <= max_size or depth >= 4:
            groups.append(set(nodes))
            return
        parts = nx.community.louvain_communities(R.subgraph(nodes).to_undirected(), seed=seed, resolution=1.0 + depth)
        if len(parts) == 1:                      # cannot split further
            groups.append(set(nodes))
            return
        for c in parts:
            split(set(c), depth + 1)

    for comp in nx.weakly_connected_components(R):
        split(set(comp))

    e_idx = edges.set_index(["src_account_id", "dst_account_id"])
    networks = []
    for members in groups:
        sub = G.subgraph(members)
        pairs = list(sub.edges)
        sub_edges = e_idx.loc[pairs] if pairs else e_idx.iloc[0:0]
        total = float(sub_edges["total_amount"].sum())
        xb = float((sub_edges["total_amount"] * sub_edges["is_cross_border"]).sum() / total) if total else 0.0
        member_patterns = [p for p in patterns if sum(a in members for a in p["account_ids"]) > len(p["account_ids"]) / 2]
        cycles = sum(p["pattern_type"] == "CYCLE" for p in member_patterns)
        chains = sum(p["pattern_type"] == "LAYERING_CHAIN" for p in member_patterns)
        hubs = []
        for v in members:
            i, o = sub.in_degree(v), sub.out_degree(v)
            if i >= 4 and i >= 2 * max(o, 1):
                hubs.append({"account_id": v, "role": "FAN_IN_HUB", "degree": i})
            elif o >= 4 and o >= 2 * max(i, 1):
                hubs.append({"account_id": v, "role": "FAN_OUT_HUB", "degree": o})
            elif i >= 3 and o >= 3:
                hubs.append({"account_id": v, "role": "PASS_THROUGH_HUB", "degree": i + o})
        high = int(sub_edges["high_risk_count"].sum())
        hints = []
        if cycles:
            hints.append("circular flow (round-tripping)")
        if chains:
            hints.append("layering chain")
        roles = {h["role"] for h in hubs}
        if "FAN_IN_HUB" in roles:
            hints.append("fan-in / funnel account")
        if "FAN_OUT_HUB" in roles:
            hints.append("fan-out / distribution account")
        if "PASS_THROUGH_HUB" in roles:
            hints.append("gather-and-scatter hub")
        if len(pairs) >= 1.5 * len(members) and not hubs:
            hints.append("dense many-to-many transfers")
        if xb >= 0.3:
            hints.append("significant cross-border value")
        score = (40 * min(high / 10, 1) + 20 * min(cycles, 1) + 15 * min(chains / 2, 1)
                 + 15 * min(len(hubs), 1) + 10 * xb)
        networks.append({
            "accounts": sorted(members), "size": len(members), "edge_count": len(pairs),
            "total_value": round(total, 2), "high_risk_tx_count": high, "cycle_count": cycles,
            "chain_count": chains, "cross_border_share": round(xb, 4),
            "hubs": sorted(hubs, key=lambda h: -h["degree"]), "typology_hints": hints,
            "risk_score": round(float(np.clip(score, 0, 100)), 2),
        })
    networks.sort(key=lambda n: -n["risk_score"])
    for i, n in enumerate(networks, start=1):
        n["id"] = i
        n["risk_level"] = "HIGH" if n["risk_score"] >= 60 else "MEDIUM" if n["risk_score"] >= 35 else "LOW"
    return networks
