"""Load modelling data from PostgreSQL."""
from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import get_settings

TX_COLS = ("transaction_id, sender_account_id, receiver_account_id, sender_customer_id, receiver_customer_id, "
           "tx_type, category, amount, timestamp, is_cross_border, sim_is_sar")


@lru_cache
def risk_config() -> dict:
    return json.loads(get_settings().risk_config_path.read_text())


def load_accounts(engine: Engine) -> pd.DataFrame:
    return pd.read_sql(text(
        "SELECT a.account_id, a.customer_id, a.country, a.opened_date, a.sim_is_sar, c.segment "
        "FROM accounts a JOIN customers c ON c.customer_id = a.customer_id"), engine)


def load_transactions(engine: Engine, account_ids: list[str] | None = None) -> pd.DataFrame:
    if account_ids is None:
        sql, params = f"SELECT {TX_COLS} FROM transactions", {}
    else:
        sql = (f"SELECT {TX_COLS} FROM transactions WHERE sender_account_id = ANY(:ids) OR receiver_account_id = ANY(:ids)"
               if engine.dialect.name == "postgresql" else
               f"SELECT {TX_COLS} FROM transactions WHERE sender_account_id IN ({','.join(':i%d' % i for i in range(len(account_ids)))}) "
               f"OR receiver_account_id IN ({','.join(':i%d' % i for i in range(len(account_ids)))})")
        params = {"ids": account_ids} if engine.dialect.name == "postgresql" else {f"i{i}": a for i, a in enumerate(account_ids)}
    df = pd.read_sql(text(sql), engine, params=params)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["amount"] = df["amount"].astype(float)
    for c in ["is_cross_border", "sim_is_sar"]:
        df[c] = df[c].astype(bool)
    return df
