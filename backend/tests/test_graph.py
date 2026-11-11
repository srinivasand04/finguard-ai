"""Graph intelligence: unit tests for flow patterns / networks + API tests."""
import networkx as nx
import pandas as pd

from graph.analytics import account_metrics, find_networks
from graph.builder import aggregate_edges, build_graph
from graph.patterns import FlowConfig, find_flow_patterns


def tx(rows):
    df = pd.DataFrame(rows, columns=["transaction_id", "sender_account_id", "receiver_account_id", "amount", "timestamp"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


CFG = FlowConfig(min_amount=1000, max_gap_hours=96)


def test_time_ordered_cycle_is_found():
    p = find_flow_patterns(tx([
        (1, "A", "B", 5000, "2026-01-01 10:00"),
        (2, "B", "C", 4900, "2026-01-02 10:00"),
        (3, "C", "A", 4800, "2026-01-03 10:00"),
    ]), CFG)
    cycles = [x for x in p if x["pattern_type"] == "CYCLE"]
    assert len(cycles) == 1
    assert cycles[0]["account_ids"] == ["A", "B", "C", "A"] and cycles[0]["transaction_ids"] == [1, 2, 3]
    assert cycles[0]["duration_hours"] == 48


def test_out_of_order_or_value_changing_flows_are_not_cycles():
    unordered = tx([(1, "A", "B", 5000, "2026-01-03"), (2, "B", "C", 4900, "2026-01-02"), (3, "C", "A", 4800, "2026-01-01")])
    assert not [x for x in find_flow_patterns(unordered, CFG) if x["pattern_type"] == "CYCLE"]
    value_drop = tx([(1, "A", "B", 5000, "2026-01-01"), (2, "B", "C", 900, "2026-01-02"), (3, "C", "A", 880, "2026-01-03")])
    assert find_flow_patterns(value_drop, CFG) == []      # second hop keeps only 18% of the value
    too_slow = tx([(1, "A", "B", 5000, "2026-01-01"), (2, "B", "C", 4900, "2026-01-10"), (3, "C", "A", 4800, "2026-01-11")])
    assert not [x for x in find_flow_patterns(too_slow, CFG) if x["pattern_type"] == "CYCLE"]


CHAIN = [
    (1, "A", "B", 8000, "2026-01-01 08:00"),
    (2, "B", "C", 7800, "2026-01-01 20:00"),
    (3, "C", "D", 7600, "2026-01-02 09:00"),
    (4, "D", "E", 7500, "2026-01-02 18:00"),
]


def test_layering_chain_reported_once_from_its_origin():
    # B, C, D normally make small everyday payments, so forwarding ~7,700 is unusual for them
    everyday = [(100 + i, acc, "SHOP", 60, f"2025-12-{10 + i} 12:00") for i, acc in enumerate("BCDBCDBCD")]
    p = find_flow_patterns(tx(CHAIN + everyday), CFG)
    chains = [x for x in p if x["pattern_type"] == "LAYERING_CHAIN"]
    assert len(chains) == 1                                # not once per hop
    assert chains[0]["account_ids"] == ["A", "B", "C", "D", "E"] and chains[0]["hops"] == 4


def test_chain_through_busy_businesses_is_not_layering():
    # same route, but B, C, D routinely pay amounts of this size - normal business flow
    routine = [(100 + i, acc, "SUPPLIER", 7000 + i, f"2025-12-{10 + i} 12:00") for i, acc in enumerate("BCDBCDBCD")]
    p = find_flow_patterns(tx(CHAIN + routine), CFG)
    assert not [x for x in p if x["pattern_type"] == "LAYERING_CHAIN"]


def test_networks_find_hub_and_cycle_hint():
    t = tx([(i, f"S{i}", "HUB", 2000, f"2026-01-0{1 + i % 5}") for i in range(1, 6)] +
           [(10, "X", "Y", 5000, "2026-01-01"), (11, "Y", "Z", 4900, "2026-01-02"), (12, "Z", "X", 4800, "2026-01-03")])
    t["is_cross_border"] = False
    t["risk_score"] = 80.0
    t["risk_band"] = "HIGH"
    edges = aggregate_edges(t)
    G = build_graph(edges)
    pats = find_flow_patterns(t, CFG)
    nets = find_networks(G, pats, edges)
    assert len(nets) == 2
    hub_net = next(n for n in nets if "HUB" in n["accounts"])
    assert hub_net["hubs"][0] == {"account_id": "HUB", "role": "FAN_IN_HUB", "degree": 5}
    ring = next(n for n in nets if "X" in n["accounts"])
    assert ring["cycle_count"] == 1 and "circular flow (round-tripping)" in ring["typology_hints"]


def test_account_metrics_shapes():
    G = nx.DiGraph([("A", "B", {"total_amount": 10.0, "tx_count": 1}), ("B", "C", {"total_amount": 10.0, "tx_count": 1})])
    m = account_metrics(G, high_risk_accounts={"C"}).set_index("account_id")
    assert m.loc["B", "betweenness"] > m.loc["A", "betweenness"]
    assert m.loc["B", "neighbour_high_risk_share"] == 0.5
    assert m["pagerank_percentile"].between(0, 1).all()


# ---------------------------------------------------------------- API (full pipeline fixture)
def test_graph_pipeline_ran(pipeline):
    g = pipeline["graph"]
    assert g["nodes"] > 0 and g["edges"] > 0
    assert set(g["evaluation"]) == {"patterns", "typology_coverage", "networks"}


def test_graph_api(client, pipeline):
    s = client.get("/api/v1/graph/summary").json()
    assert s["nodes"] > 0 and s["top_pagerank"]
    acc = s["top_pagerank"][0]["account_id"]
    a = client.get(f"/api/v1/graph/accounts/{acc}").json()
    assert a["metrics"]["account_id"] == acc
    ego = client.get("/api/v1/graph/ego", params={"account_id": acc, "depth": 1}).json()
    ids = {n["id"] for n in ego["nodes"]}
    assert acc in ids and all(e["source"] in ids and e["target"] in ids for e in ego["edges"])
    assert client.get("/api/v1/graph/ego").status_code == 422
    assert client.get("/api/v1/graph/accounts/NOPE").status_code == 404

    pats = client.get("/api/v1/graph/patterns", params={"size": 5}).json()
    if pats["total"]:
        p = client.get(f"/api/v1/graph/patterns/{pats['items'][0]['id']}").json()
        assert [t["transaction_id"] for t in p["transactions"]] == p["transaction_ids"]
        assert any(e["highlight"] for e in p["graph"]["edges"])
        first = p["account_ids"][0]
        by_acc = client.get("/api/v1/graph/patterns", params={"account_id": first}).json()
        assert all(first in x["account_ids"] for x in by_acc["items"])
    nets = client.get("/api/v1/graph/networks").json()
    if nets["total"]:
        n = client.get(f"/api/v1/graph/networks/{nets['items'][0]['id']}").json()
        assert len(n["account_ids"]) == n["size"]

    e = ego["edges"][0]
    path = client.get("/api/v1/graph/path", params={"source": e["source"], "target": e["target"]}).json()
    assert path["found"] and path["path"][0] == e["source"] and path["hops"] >= 1
