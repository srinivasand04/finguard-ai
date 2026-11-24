"""Leakage-safe graph construction for the GNN.

Everything here is computed from transactions BEFORE `cutoff` (the end of the training
period of the chronological split). Validation and test transactions are later scored with
node representations that only know the past - exactly what a bank would have at that time.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

SEGMENTS = ["RETAIL", "SME", "CORPORATE"]
NODE_FEATURES = ["log_out_count", "log_in_count", "log_out_sum", "log_in_sum", "log_mean_out", "log_out_degree",
                 "log_in_degree", "cross_border_share", "night_share", "near_threshold", "log_account_age",
                 "home_high_risk", "seg_RETAIL", "seg_SME", "seg_CORPORATE"]


@dataclass
class AccountGraph:
    account_ids: list[str]                 # node order
    index: dict[str, int]                  # account_id -> node index
    x: torch.Tensor                        # [n_nodes, n_features], standardised
    edge_index: torch.Tensor               # [2, n_edges] directed sender -> receiver (unique pairs)
    y: torch.Tensor                        # [n_nodes] 1 = involved in a simulated SAR tx before cutoff
    active: torch.Tensor                   # [n_nodes] bool - had any transaction before cutoff
    cutoff: pd.Timestamp
    max_edge_time: pd.Timestamp | None


def build_account_graph(tx: pd.DataFrame, accounts: pd.DataFrame, cutoff: pd.Timestamp,
                        high_risk_countries: list[str]) -> AccountGraph:
    """tx: transaction_id, sender/receiver_account_id, amount, timestamp, is_cross_border, sim_is_sar."""
    past = tx[tx["timestamp"] < cutoff]
    ids = accounts["account_id"].tolist()
    idx = {a: i for i, a in enumerate(ids)}
    n = len(ids)
    acc = accounts.set_index("account_id")

    out_g, in_g = past.groupby("sender_account_id"), past.groupby("receiver_account_id")
    f = pd.DataFrame(index=ids)
    f["log_out_count"] = np.log1p(out_g.size())
    f["log_in_count"] = np.log1p(in_g.size())
    f["log_out_sum"] = np.log1p(out_g["amount"].sum())
    f["log_in_sum"] = np.log1p(in_g["amount"].sum())
    f["log_mean_out"] = np.log1p(out_g["amount"].mean())
    f["log_out_degree"] = np.log1p(out_g["receiver_account_id"].nunique())
    f["log_in_degree"] = np.log1p(in_g["sender_account_id"].nunique())
    f["cross_border_share"] = out_g["is_cross_border"].mean()
    f["night_share"] = out_g["timestamp"].apply(lambda s: (s.dt.hour < 5).mean())
    f["near_threshold"] = out_g["amount"].apply(lambda s: float(((s >= 9000) & (s < 10000)).sum()))
    opened = pd.to_datetime(acc["opened_date"])
    f["log_account_age"] = np.log1p((cutoff - opened).dt.days.clip(lower=0)).reindex(ids)
    f["home_high_risk"] = acc["country"].isin(high_risk_countries).astype(float).reindex(ids)
    for s in SEGMENTS:
        f[f"seg_{s}"] = (acc["segment"] == s).astype(float).reindex(ids)
    f = f[NODE_FEATURES].fillna(0.0).astype(float)
    mu, sd = f.mean(), f.std().replace(0, 1.0)
    x = torch.tensor(((f - mu) / sd).to_numpy(), dtype=torch.float32)

    pairs = past[["sender_account_id", "receiver_account_id"]].drop_duplicates()
    src = pairs["sender_account_id"].map(idx).to_numpy()
    dst = pairs["receiver_account_id"].map(idx).to_numpy()
    edge_index = torch.tensor(np.vstack([src, dst]), dtype=torch.long)

    sar = past[past["sim_is_sar"]]
    y = np.zeros(n, dtype=np.float32)
    for col in ("sender_account_id", "receiver_account_id"):
        y[sar[col].map(idx).dropna().astype(int).to_numpy()] = 1.0
    active = np.zeros(n, dtype=bool)
    for col in ("sender_account_id", "receiver_account_id"):
        active[past[col].map(idx).dropna().astype(int).unique()] = True

    return AccountGraph(ids, idx, x, edge_index, torch.tensor(y), torch.tensor(active), cutoff,
                        past["timestamp"].max() if len(past) else None)
