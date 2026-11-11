"""Transaction feature engineering.

All behavioural features are point-in-time: for a transaction at time t they
only use events strictly before t, so there is no look-ahead leakage and the
same code serves batch training and near-real-time scoring.

Input `tx` columns: transaction_id, sender_account_id, receiver_account_id,
amount, timestamp, tx_type, is_cross_border.
Input `accounts` columns: account_id, country, opened_date, segment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW_7D = pd.Timedelta(days=7)
WINDOW_24H = pd.Timedelta(hours=24)
TX_TYPES = ["TRANSFER", "PAYMENT", "WIRE"]
SEGMENT_CODE = {"RETAIL": 0, "SME": 1, "CORPORATE": 2}

FEATURES = [
    "log_amount", "is_round_amount", "near_threshold", "hour", "is_night", "day_of_week", "is_weekend",
    "type_TRANSFER", "type_PAYMENT", "type_WIRE", "is_cross_border",
    "receiver_high_risk_country", "sender_high_risk_country",
    "sender_account_age_days", "receiver_account_age_days", "sender_segment", "receiver_segment",
    "sender_tx_count_24h", "sender_tx_count_7d", "sender_amount_sum_7d_log",
    "sender_prior_tx_count", "amount_vs_sender_mean", "is_new_counterparty", "sender_new_counterparties_7d",
    "receiver_in_count_7d", "receiver_new_senders_7d", "sender_in_amount_7d_log", "pass_through_ratio",
]

FEATURE_DESCRIPTIONS = {
    "log_amount": "Transaction amount",
    "is_round_amount": "Round-number amount",
    "near_threshold": "Amount just below 10,000 reporting threshold",
    "hour": "Hour of day",
    "is_night": "Night-time transaction (00:00-05:00)",
    "day_of_week": "Day of week",
    "is_weekend": "Weekend transaction",
    "type_TRANSFER": "Transfer type",
    "type_PAYMENT": "Payment type",
    "type_WIRE": "Wire type",
    "is_cross_border": "Cross-border transaction",
    "receiver_high_risk_country": "Receiver in elevated-risk jurisdiction",
    "sender_high_risk_country": "Sender in elevated-risk jurisdiction",
    "sender_account_age_days": "Sender account age",
    "receiver_account_age_days": "Receiver account age",
    "sender_segment": "Sender customer segment",
    "receiver_segment": "Receiver customer segment",
    "sender_tx_count_24h": "Sender transactions in previous 24h (velocity)",
    "sender_tx_count_7d": "Sender transactions in previous 7 days (velocity)",
    "sender_amount_sum_7d_log": "Sender outgoing value in previous 7 days",
    "sender_prior_tx_count": "Sender transaction history length",
    "amount_vs_sender_mean": "Amount relative to sender's usual amount",
    "is_new_counterparty": "First payment to this counterparty",
    "sender_new_counterparties_7d": "New counterparties of sender in previous 7 days",
    "receiver_in_count_7d": "Incoming transactions to receiver in previous 7 days (fan-in)",
    "receiver_new_senders_7d": "New senders to receiver in previous 7 days",
    "sender_in_amount_7d_log": "Funds received by sender in previous 7 days",
    "pass_through_ratio": "Amount relative to funds just received (pass-through)",
}


def _window_sum(events: pd.DataFrame, key: str, val: str, queries: pd.DataFrame, qkey: str,
                window: pd.Timedelta | None) -> np.ndarray:
    """Sum of `val` over events with the same key in [t - window, t) for each query row.

    Uses cumulative sums + two as-of joins, which is O(n log n) and exact.
    window=None means all history before t.
    """
    ev = events[[key, "timestamp", val]].sort_values("timestamp", kind="mergesort").copy()
    ev["_cum"] = ev.groupby(key)[val].cumsum()
    ev = ev.rename(columns={key: "_k"})[["_k", "timestamp", "_cum"]]
    q = pd.DataFrame({"_k": queries[qkey].to_numpy(), "timestamp": queries["timestamp"].to_numpy(),
                      "_row": np.arange(len(queries))}).sort_values("timestamp", kind="mergesort")

    def cum_before(ts_col: pd.Series) -> np.ndarray:
        qq = q.assign(timestamp=ts_col)
        m = pd.merge_asof(qq.sort_values("timestamp", kind="mergesort"), ev, on="timestamp", by="_k",
                          allow_exact_matches=False, direction="backward")
        return m.sort_values("_row")["_cum"].fillna(0).to_numpy()

    upto_t = cum_before(q["timestamp"])
    if window is None:
        return upto_t
    upto_start = cum_before(q["timestamp"] - window)
    return upto_t - upto_start


def build_features(tx: pd.DataFrame, accounts: pd.DataFrame, high_risk_countries: list[str]) -> pd.DataFrame:
    df = tx.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["amount"] = df["amount"].astype(float)
    df = df.sort_values(["timestamp", "transaction_id"], kind="mergesort").reset_index(drop=True)

    acc = accounts.set_index("account_id")
    opened = pd.to_datetime(acc["opened_date"])
    hr = set(high_risk_countries)

    f = pd.DataFrame(index=df.index)
    f["transaction_id"] = df["transaction_id"].to_numpy()
    f["log_amount"] = np.log1p(df["amount"])
    f["is_round_amount"] = ((df["amount"] % 100).round(2) == 0).astype(int)
    f["near_threshold"] = ((df["amount"] >= 9000) & (df["amount"] < 10000)).astype(int)
    f["hour"] = df["timestamp"].dt.hour
    f["is_night"] = (f["hour"] < 5).astype(int)
    f["day_of_week"] = df["timestamp"].dt.dayofweek
    f["is_weekend"] = (f["day_of_week"] >= 5).astype(int)
    for t in TX_TYPES:
        f[f"type_{t}"] = (df["tx_type"] == t).astype(int)
    f["is_cross_border"] = df["is_cross_border"].astype(int)
    f["receiver_high_risk_country"] = df["receiver_account_id"].map(acc["country"]).isin(hr).astype(int)
    f["sender_high_risk_country"] = df["sender_account_id"].map(acc["country"]).isin(hr).astype(int)
    f["sender_account_age_days"] = (df["timestamp"] - df["sender_account_id"].map(opened)).dt.days.clip(lower=0).fillna(0)
    f["receiver_account_age_days"] = (df["timestamp"] - df["receiver_account_id"].map(opened)).dt.days.clip(lower=0).fillna(0)
    f["sender_segment"] = df["sender_account_id"].map(acc["segment"]).map(SEGMENT_CODE).fillna(0).astype(int)
    f["receiver_segment"] = df["receiver_account_id"].map(acc["segment"]).map(SEGMENT_CODE).fillna(0).astype(int)

    # --- velocity / behaviour (strictly prior events) ---
    out_ev = df[["sender_account_id", "timestamp", "amount"]].assign(one=1.0)
    f["sender_tx_count_24h"] = _window_sum(out_ev, "sender_account_id", "one", df, "sender_account_id", WINDOW_24H)
    f["sender_tx_count_7d"] = _window_sum(out_ev, "sender_account_id", "one", df, "sender_account_id", WINDOW_7D)
    f["sender_amount_sum_7d_log"] = np.log1p(_window_sum(out_ev, "sender_account_id", "amount", df, "sender_account_id", WINDOW_7D))
    prior_cnt = _window_sum(out_ev, "sender_account_id", "one", df, "sender_account_id", None)
    prior_sum = _window_sum(out_ev, "sender_account_id", "amount", df, "sender_account_id", None)
    f["sender_prior_tx_count"] = prior_cnt
    prior_mean = np.where(prior_cnt > 0, prior_sum / np.maximum(prior_cnt, 1), np.nan)
    f["amount_vs_sender_mean"] = np.where(np.isnan(prior_mean), 1.0, df["amount"] / prior_mean).clip(0, 1000)

    pair_rank = df.groupby(["sender_account_id", "receiver_account_id"]).cumcount()
    df["_new_pair"] = (pair_rank == 0).astype(float)
    f["is_new_counterparty"] = df["_new_pair"].astype(int)
    f["sender_new_counterparties_7d"] = _window_sum(df, "sender_account_id", "_new_pair", df, "sender_account_id", WINDOW_7D)

    in_ev = df[["receiver_account_id", "timestamp", "amount", "_new_pair"]].assign(one=1.0)
    f["receiver_in_count_7d"] = _window_sum(in_ev, "receiver_account_id", "one", df, "receiver_account_id", WINDOW_7D)
    f["receiver_new_senders_7d"] = _window_sum(in_ev, "receiver_account_id", "_new_pair", df, "receiver_account_id", WINDOW_7D)
    # money that arrived into the *sender* recently (layering / pass-through)
    in_sender = _window_sum(in_ev, "receiver_account_id", "amount", df, "sender_account_id", WINDOW_7D)
    f["sender_in_amount_7d_log"] = np.log1p(in_sender)
    f["pass_through_ratio"] = np.where(in_sender > 0, df["amount"] / np.maximum(in_sender, 1), 0).clip(0, 10)
    return f


def describe_factor(name: str, value: float) -> str:
    base = FEATURE_DESCRIPTIONS.get(name, name)
    if name.endswith("_log"):
        return f"{base}: {np.expm1(value):,.0f}"
    if name == "log_amount":
        return f"{base}: {np.expm1(value):,.2f}"
    if name in {"sender_segment", "receiver_segment"}:
        seg = {v: k for k, v in SEGMENT_CODE.items()}.get(int(value), str(value))
        return f"{base}: {seg.lower()}"
    if name in {"amount_vs_sender_mean", "pass_through_ratio"}:
        return f"{base}: {value:.2f}x"
    if set(np.unique([value])) <= {0, 1} and name.startswith(("is_", "type_", "near_", "receiver_high", "sender_high")):
        return f"{base}: {'yes' if value else 'no'}"
    return f"{base}: {value:,.0f}"
