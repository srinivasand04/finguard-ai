"""Graph intelligence API: summary, ego networks for visualisation, patterns, networks, paths."""
from __future__ import annotations

import json
from typing import Annotated, Literal

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (Account, AccountGraphMetrics, Customer, CustomerRisk, GraphEdge, GraphPattern,
                        SuspiciousNetwork, Transaction)
from app.schemas import DISCLAIMER

router = APIRouter(prefix="/api/v1/graph", tags=["graph"])
SessionDep = Annotated[Session, Depends(get_session)]


def _js(v):
    return json.loads(v) if isinstance(v, str) else v


def _metrics_out(m: AccountGraphMetrics) -> dict:
    return {k: getattr(m, k) for k in ("account_id", "customer_id", "in_degree", "out_degree", "degree_centrality",
                                       "pagerank", "pagerank_percentile", "betweenness", "community_id",
                                       "community_size", "cycle_count", "chain_count", "network_id",
                                       "neighbour_high_risk_share", "graph_version")}


def _pattern_out(p: GraphPattern) -> dict:
    return {"id": p.id, "pattern_type": p.pattern_type, "account_ids": _js(p.account_ids),
            "customer_ids": _js(p.customer_ids), "transaction_ids": _js(p.transaction_ids), "hops": p.hops,
            "start_amount": p.start_amount, "end_amount": p.end_amount, "start_ts": p.start_ts, "end_ts": p.end_ts,
            "duration_hours": p.duration_hours, "score": p.score, "network_id": p.network_id}


def _network_out(n: SuspiciousNetwork, full: bool = False) -> dict:
    out = {"id": n.id, "size": n.size, "edge_count": n.edge_count, "total_value": n.total_value,
           "high_risk_tx_count": n.high_risk_tx_count, "cycle_count": n.cycle_count, "chain_count": n.chain_count,
           "cross_border_share": n.cross_border_share, "hubs": _js(n.hubs), "typology_hints": _js(n.typology_hints),
           "risk_score": n.risk_score, "risk_level": n.risk_level, "customer_ids": _js(n.customer_ids)}
    if full:
        out["account_ids"] = _js(n.account_ids)
    return out


def _subgraph(session: Session, accounts: set[str], highlight_edges: set[tuple[str, str]] | None = None,
              focus: set[str] | None = None, max_edges: int = 400) -> dict:
    """Nodes + edges among `accounts`, enriched for visualisation."""
    if not accounts:
        return {"nodes": [], "edges": []}
    edges = session.scalars(select(GraphEdge).where(GraphEdge.src_account_id.in_(accounts),
                                                    GraphEdge.dst_account_id.in_(accounts))
                            .order_by(GraphEdge.total_amount.desc()).limit(max_edges)).all()
    rows = session.execute(
        select(Account.account_id, Account.customer_id, Account.country, Customer.full_name, Customer.segment,
               CustomerRisk.risk_level, AccountGraphMetrics.pagerank_percentile, AccountGraphMetrics.network_id,
               AccountGraphMetrics.cycle_count, AccountGraphMetrics.chain_count)
        .join(Customer, Customer.customer_id == Account.customer_id)
        .outerjoin(CustomerRisk, CustomerRisk.customer_id == Account.customer_id)
        .outerjoin(AccountGraphMetrics, AccountGraphMetrics.account_id == Account.account_id)
        .where(Account.account_id.in_(accounts))).all()
    nodes = [{"id": r.account_id, "customer_id": r.customer_id, "label": r.account_id, "name": r.full_name,
              "segment": r.segment, "country": r.country, "risk_level": r.risk_level,
              "pagerank_percentile": r.pagerank_percentile, "network_id": r.network_id,
              "cycle_count": r.cycle_count or 0, "chain_count": r.chain_count or 0,
              "focus": bool(focus and r.account_id in focus)} for r in rows]
    hl = highlight_edges or set()
    return {"nodes": nodes, "edges": [
        {"id": f"{e.src_account_id}->{e.dst_account_id}", "source": e.src_account_id, "target": e.dst_account_id,
         "tx_count": e.tx_count, "total_amount": e.total_amount, "high_risk_count": e.high_risk_count,
         "max_risk_score": e.max_risk_score, "is_cross_border": e.is_cross_border,
         "highlight": (e.src_account_id, e.dst_account_id) in hl} for e in edges]}


@router.get("/summary", summary="Graph size, communities, patterns, networks and most central accounts")
def summary(session: SessionDep):
    n_nodes = session.scalar(select(func.count()).select_from(AccountGraphMetrics)) or 0
    if not n_nodes:
        raise HTTPException(503, "Graph not built yet - run `python -m app.cli graph`")
    top = lambda col: [  # noqa: E731
        {"account_id": a, "customer_id": c, "value": round(v, 6)} for a, c, v in session.execute(
            select(AccountGraphMetrics.account_id, AccountGraphMetrics.customer_id, col).order_by(col.desc()).limit(10))]
    return {
        "nodes": n_nodes,
        "edges": session.scalar(select(func.count()).select_from(GraphEdge)) or 0,
        "communities": session.scalar(select(func.count(func.distinct(AccountGraphMetrics.community_id)))) or 0,
        "graph_version": session.scalar(select(AccountGraphMetrics.graph_version).limit(1)),
        "patterns": dict(session.execute(select(GraphPattern.pattern_type, func.count()).group_by(GraphPattern.pattern_type)).all()),
        "networks": dict(session.execute(select(SuspiciousNetwork.risk_level, func.count()).group_by(SuspiciousNetwork.risk_level)).all()),
        "top_pagerank": top(AccountGraphMetrics.pagerank),
        "top_betweenness": top(AccountGraphMetrics.betweenness),
        "disclaimer": DISCLAIMER,
    }


@router.get("/accounts/{account_id}", summary="Graph metrics, patterns and network for one account")
def account(account_id: str, session: SessionDep):
    m = session.get(AccountGraphMetrics, account_id)
    if not m:
        raise HTTPException(404, f"No graph metrics for {account_id}")
    pats = session.scalars(select(GraphPattern).where(cast(GraphPattern.account_ids, String).like(f'%"{account_id}"%'))
                           .order_by(GraphPattern.score.desc()).limit(20)).all()
    net = session.get(SuspiciousNetwork, m.network_id) if m.network_id else None
    return {"metrics": _metrics_out(m), "patterns": [_pattern_out(p) for p in pats],
            "network": _network_out(net) if net else None}


@router.get("/ego", summary="Ego network around an account or customer (nodes/edges for visualisation)")
def ego(session: SessionDep, account_id: str | None = None, customer_id: str | None = None,
        depth: int = Query(1, ge=1, le=2), max_neighbours: int = Query(25, ge=5, le=100)):
    if customer_id:
        centre = set(session.scalars(select(Account.account_id).where(Account.customer_id == customer_id)))
    elif account_id:
        centre = {account_id} if session.get(Account, account_id) else set()
    else:
        raise HTTPException(422, "Provide account_id or customer_id")
    if not centre:
        raise HTTPException(404, "Account/customer not found")
    nodes, frontier = set(centre), set(centre)
    for _ in range(depth):
        # strongest relationships first so busy merchants don't flood the picture
        rows = session.execute(select(GraphEdge.src_account_id, GraphEdge.dst_account_id, GraphEdge.total_amount,
                                      GraphEdge.high_risk_count)
                               .where(or_(GraphEdge.src_account_id.in_(frontier), GraphEdge.dst_account_id.in_(frontier)))).all()
        ranked = sorted(rows, key=lambda r: (-(r.high_risk_count > 0), -r.total_amount))
        new: set[str] = set()
        for r in ranked:
            other = r.dst_account_id if r.src_account_id in frontier else r.src_account_id
            if other not in nodes:
                new.add(other)
            if len(new) >= max_neighbours * len(frontier) or len(new) >= max_neighbours * 4:
                break
        nodes |= new
        frontier = new
    return {"centre": sorted(centre), **_subgraph(session, nodes, focus=centre)}


@router.get("/patterns", summary="Time-ordered cycles and layering chains")
def patterns(session: SessionDep, pattern_type: Literal["CYCLE", "LAYERING_CHAIN"] | None = None,
             min_score: float = 0, account_id: str | None = None, customer_id: str | None = None,
             page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    q = select(GraphPattern).where(GraphPattern.score >= min_score)
    if pattern_type:
        q = q.where(GraphPattern.pattern_type == pattern_type)
    if account_id:
        q = q.where(cast(GraphPattern.account_ids, String).like(f'%"{account_id}"%'))
    if customer_id:
        q = q.where(cast(GraphPattern.customer_ids, String).like(f'%"{customer_id}"%'))
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.scalars(q.order_by(GraphPattern.score.desc(), GraphPattern.id).offset((page - 1) * size).limit(size)).all()
    return {"items": [_pattern_out(p) for p in rows], "total": total, "page": page, "size": size}


@router.get("/patterns/{pattern_id}", summary="Pattern with its transactions and subgraph")
def pattern(pattern_id: int, session: SessionDep):
    p = session.get(GraphPattern, pattern_id)
    if not p:
        raise HTTPException(404, f"Pattern {pattern_id} not found")
    out = _pattern_out(p)
    txs = session.scalars(select(Transaction).where(Transaction.transaction_id.in_(out["transaction_ids"]))).all()
    order = {t: i for i, t in enumerate(out["transaction_ids"])}
    out["transactions"] = sorted([{"transaction_id": t.transaction_id, "sender_account_id": t.sender_account_id,
                                   "receiver_account_id": t.receiver_account_id, "amount": float(t.amount),
                                   "timestamp": t.timestamp, "tx_type": t.tx_type} for t in txs],
                                 key=lambda t: order[t["transaction_id"]])
    acc = out["account_ids"]
    out["graph"] = _subgraph(session, set(acc), highlight_edges=set(zip(acc[:-1], acc[1:])), focus={acc[0]})
    out["disclaimer"] = DISCLAIMER
    return out


@router.get("/networks", summary="Suspicious networks ranked by risk")
def networks(session: SessionDep, risk_level: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
             page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200)):
    q = select(SuspiciousNetwork)
    if risk_level:
        q = q.where(SuspiciousNetwork.risk_level == risk_level)
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.scalars(q.order_by(SuspiciousNetwork.risk_score.desc(), SuspiciousNetwork.id)
                           .offset((page - 1) * size).limit(size)).all()
    return {"items": [_network_out(n) for n in rows], "total": total, "page": page, "size": size}


@router.get("/networks/{network_id}", summary="Network members, subgraph and patterns")
def network(network_id: int, session: SessionDep):
    n = session.get(SuspiciousNetwork, network_id)
    if not n:
        raise HTTPException(404, f"Network {network_id} not found")
    out = _network_out(n, full=True)
    pats = session.scalars(select(GraphPattern).where(GraphPattern.network_id == network_id)
                           .order_by(GraphPattern.score.desc()).limit(50)).all()
    out["patterns"] = [_pattern_out(p) for p in pats]
    hub_ids = {h["account_id"] for h in out["hubs"]}
    out["graph"] = _subgraph(session, set(out["account_ids"]), focus=hub_ids)
    out["disclaimer"] = DISCLAIMER
    return out


_GRAPH_CACHE: dict[str, nx.DiGraph] = {}


def _graph_for(session: Session) -> nx.DiGraph:
    """In-memory DiGraph of the current graph version (rebuilt only when the version changes)."""
    version = session.scalar(select(AccountGraphMetrics.graph_version).limit(1))
    if not version:
        raise HTTPException(503, "Graph not built yet")
    if version not in _GRAPH_CACHE:
        G = nx.DiGraph()
        G.add_edges_from((s, d) for s, d in session.execute(select(GraphEdge.src_account_id, GraphEdge.dst_account_id)))
        _GRAPH_CACHE.clear()
        _GRAPH_CACHE[version] = G
    return _GRAPH_CACHE[version]


@router.get("/path", summary="Shortest money-flow path between two accounts")
def path(session: SessionDep, source: str, target: str, directed: bool = True):
    G = _graph_for(session)
    if source not in G or target not in G:
        raise HTTPException(404, "Source or target account has no graph edges")
    H = G if directed else G.to_undirected(as_view=True)
    try:
        nodes = nx.shortest_path(H, source, target)
    except nx.NetworkXNoPath:
        return {"source": source, "target": target, "directed": directed, "found": False, "path": [], "graph": {"nodes": [], "edges": []}}
    hops = set(zip(nodes[:-1], nodes[1:])) | (set(zip(nodes[1:], nodes[:-1])) if not directed else set())
    return {"source": source, "target": target, "directed": directed, "found": True, "path": nodes,
            "hops": len(nodes) - 1, "graph": _subgraph(session, set(nodes), highlight_edges=hops, focus={source, target})}
