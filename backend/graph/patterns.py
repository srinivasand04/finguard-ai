"""Time-ordered money-flow patterns: CYCLES and LAYERING CHAINS.

A plain graph cycle (A->B->C->A on the aggregated graph) is common and harmless -
salaries, supplier payments and refunds create them all the time. What matters for
AML is money that *moves forward in time* and keeps most of its value:

    tx1: A -> B  (t1, amount x)
    tx2: B -> C  (t2, amount ~x)   with t1 < t2 <= t1 + max_gap
    tx3: C -> A  (t3, amount ~x)   ...

So the search runs over individual transactions, not aggregated edges. From each
transaction it follows the receiving account's *next* outgoing transactions inside a
time window whose amount stays within [ratio_low, ratio_high] of the previous hop.

* returns to the starting account with >= 3 hops      -> CYCLE (round-tripping)
* never returns, >= min_chain_hops, cannot be extended -> LAYERING_CHAIN, but only if
  most intermediate hops are *unusual for the forwarding account* (amount >= unusual_factor
  x that account's median outgoing payment). Busy businesses legitimately pass similar
  amounts along every day; a retail account that normally spends 70 forwarding 3,000
  within hours is what layering looks like.

Chains are only started from "origin" transactions (no qualifying inflow just before),
so the same chain is not reported once per hop. Branching, depth and total output are
capped to keep the search bounded on busy business accounts.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class FlowConfig:
    min_amount: float = 1000.0       # ignore small everyday payments
    max_gap_hours: float = 96.0      # next hop must follow within this window
    ratio_low: float = 0.7           # next hop keeps 70%..110% of the previous amount
    ratio_high: float = 1.1
    max_hops: int = 6
    min_cycle_hops: int = 3
    min_chain_hops: int = 3
    max_branch: int = 4              # follow at most N candidate next hops
    max_duration_days: float = 21.0
    max_patterns: int = 20000
    unusual_factor: float = 3.0      # chain hop must be >= 3x the forwarder's median outgoing amount
    min_unusual_share: float = 0.5   # ...for at least half of the intermediate hops


def _score(kind: str, hops: int, retention: float, duration_h: float, cfg: FlowConfig) -> float:
    type_w = 1.0 if kind == "CYCLE" else 0.6
    hop_w = min(hops / cfg.max_hops, 1.0)
    keep_w = max(0.0, 1 - abs(1 - retention) / 0.3)          # value kept along the path
    speed_w = max(0.0, 1 - duration_h / (cfg.max_duration_days * 24))
    return round(100 * (0.4 * type_w + 0.2 * hop_w + 0.2 * keep_w + 0.2 * speed_w), 2)


def find_flow_patterns(tx: pd.DataFrame, cfg: FlowConfig | None = None) -> list[dict]:
    """tx columns: transaction_id, sender_account_id, receiver_account_id, amount, timestamp."""
    cfg = cfg or FlowConfig()
    median_out = tx.groupby("sender_account_id")["amount"].median()   # behavioural baseline, all amounts
    t = tx[tx["amount"] >= cfg.min_amount].sort_values(["timestamp", "transaction_id"], kind="mergesort").reset_index(drop=True)
    if t.empty:
        return []
    ids = t["transaction_id"].to_numpy()
    snd = t["sender_account_id"].to_numpy()
    rcv = t["receiver_account_id"].to_numpy()
    amt = t["amount"].to_numpy(dtype=float)
    ts = t["timestamp"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    gap = int(cfg.max_gap_hours * 3600 * 1e9)
    max_dur = int(cfg.max_duration_days * 86400 * 1e9)

    # positional indices of each account's outgoing / incoming transactions, already time-sorted
    out_idx = {k: np.asarray(v) for k, v in t.groupby("sender_account_id", sort=False).indices.items()}
    in_idx = {k: np.asarray(v) for k, v in t.groupby("receiver_account_id", sort=False).indices.items()}

    def next_hops(i: int, start_ts: int) -> list[int]:
        cand = out_idx.get(rcv[i])
        if cand is None:
            return []
        cts = ts[cand]
        lo, hi = np.searchsorted(cts, ts[i], "right"), np.searchsorted(cts, ts[i] + gap, "right")
        picks = []
        for j in cand[lo:hi]:
            r = amt[j] / amt[i]
            if cfg.ratio_low <= r <= cfg.ratio_high and ts[j] - start_ts <= max_dur:
                picks.append(int(j))
                if len(picks) >= cfg.max_branch:
                    break
        return picks

    def is_origin(i: int) -> bool:
        """True if no qualifying inflow reached the sender shortly before tx i."""
        cand = in_idx.get(snd[i])
        if cand is None:
            return True
        cts = ts[cand]
        lo, hi = np.searchsorted(cts, ts[i] - gap, "left"), np.searchsorted(cts, ts[i], "left")
        for k in cand[lo:hi]:
            r = amt[i] / amt[k]
            if cfg.ratio_low <= r <= cfg.ratio_high:
                return False
        return True

    base = t["sender_account_id"].map(median_out).to_numpy(dtype=float)
    unusual = amt >= cfg.unusual_factor * base          # per transaction: big for *this* sender?

    def chain_is_unusual(path: list[int]) -> bool:
        inner = path[1:]                                 # hops sent by intermediate accounts
        return sum(bool(unusual[j]) for j in inner) >= cfg.min_unusual_share * len(inner)

    found: dict[tuple, dict] = {}

    def record(kind: str, path: list[int]) -> None:
        accounts = [snd[path[0]]] + [rcv[p] for p in path]
        key = (kind, frozenset(accounts) if kind == "CYCLE" else tuple(accounts))
        if key in found:                      # same ring / same route seen again
            found[key]["repeats"] += 1
            return
        dur_h = (ts[path[-1]] - ts[path[0]]) / 3.6e12
        retention = amt[path[-1]] / amt[path[0]]
        found[key] = {
            "pattern_type": kind, "account_ids": [str(a) for a in accounts],
            "transaction_ids": [int(ids[p]) for p in path], "hops": len(path),
            "start_amount": round(float(amt[path[0]]), 2), "end_amount": round(float(amt[path[-1]]), 2),
            "start_ts": pd.Timestamp(ts[path[0]]), "end_ts": pd.Timestamp(ts[path[-1]]),
            "duration_hours": round(float(dur_h), 2),
            "score": _score(kind, len(path), retention, dur_h, cfg), "repeats": 1,
        }

    for i in range(len(t)):
        if len(found) >= cfg.max_patterns:
            break
        origin = is_origin(i)
        # iterative DFS: (path, visited accounts)
        stack = [([i], [snd[i], rcv[i]])]
        while stack:
            path, visited = stack.pop()
            extended = False
            for j in next_hops(path[-1], ts[path[0]]):
                nxt = rcv[j]
                if nxt == visited[0]:
                    if len(path) + 1 >= cfg.min_cycle_hops:
                        record("CYCLE", path + [j])
                    extended = True
                elif nxt not in visited and len(path) + 1 <= cfg.max_hops:
                    stack.append((path + [j], visited + [nxt]))
                    extended = True
            if not extended and origin and len(path) >= cfg.min_chain_hops and chain_is_unusual(path):
                record("LAYERING_CHAIN", path)
    return sorted(found.values(), key=lambda p: -p["score"])
