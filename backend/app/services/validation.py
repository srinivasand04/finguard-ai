"""Data validation and cleaning for AMLSim-format inputs.

Every function is pure (DataFrame in, DataFrames out) so it can be unit tested.
Rows that cannot be repaired are rejected with an explicit reason; nothing is
dropped silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

VALID_TX_TYPES = {"TRANSFER", "PAYMENT", "WIRE", "CASH_DEPOSIT", "CASH_WITHDRAWAL", "DEBIT", "CREDIT"}
REQUIRED = {
    "customers": ["CUSTOMER_ID", "FULL_NAME", "SEGMENT", "COUNTRY", "ONBOARDING_DATE", "KYC_LEVEL"],
    "accounts": ["ACCOUNT_ID", "CUSTOMER_ID", "INIT_BALANCE", "COUNTRY", "ACCOUNT_TYPE"],
    "transactions": ["TX_ID", "SENDER_ACCOUNT_ID", "RECEIVER_ACCOUNT_ID", "TX_TYPE", "TX_AMOUNT", "TIMESTAMP"],
}


class SchemaError(ValueError):
    pass


@dataclass
class ValidationResult:
    clean: pd.DataFrame
    rejected: pd.DataFrame
    report: dict = field(default_factory=dict)


def check_columns(df: pd.DataFrame, kind: str) -> None:
    missing = [c for c in REQUIRED[kind] if c not in df.columns]
    if missing:
        raise SchemaError(f"{kind}: missing required columns {missing}")


def _reject(df: pd.DataFrame, mask: pd.Series, reason: str, bucket: list[pd.DataFrame]) -> pd.DataFrame:
    if mask.any():
        bad = df[mask].copy()
        bad["REJECT_REASON"] = reason
        bucket.append(bad)
    return df[~mask]


def _to_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "y", "t"])


def validate_customers(df: pd.DataFrame) -> ValidationResult:
    check_columns(df, "customers")
    rejected: list[pd.DataFrame] = []
    n_in = len(df)
    df = df.copy()
    df["CUSTOMER_ID"] = df["CUSTOMER_ID"].astype(str).str.strip()
    df["SEGMENT"] = df["SEGMENT"].astype(str).str.strip().str.upper()
    df["COUNTRY"] = df["COUNTRY"].astype(str).str.strip().str.upper()
    df["KYC_LEVEL"] = df["KYC_LEVEL"].astype(str).str.strip().str.upper()
    df = _reject(df, df["CUSTOMER_ID"].isin(["", "nan"]), "missing_customer_id", rejected)
    df = _reject(df, df.duplicated("CUSTOMER_ID", keep="first"), "duplicate_customer_id", rejected)
    df["ONBOARDING_DATE"] = pd.to_datetime(df["ONBOARDING_DATE"], errors="coerce").dt.date
    df = _reject(df, df["ONBOARDING_DATE"].isna(), "invalid_onboarding_date", rejected)
    if "DATE_OF_BIRTH" in df:
        df["DATE_OF_BIRTH"] = pd.to_datetime(df["DATE_OF_BIRTH"], errors="coerce").dt.date
    df["PEP_FLAG"] = _to_bool(df["PEP_FLAG"]) if "PEP_FLAG" in df else False
    rej = pd.concat(rejected) if rejected else pd.DataFrame()
    return ValidationResult(df, rej, {"input_rows": n_in, "clean_rows": len(df), "rejected_rows": len(rej),
                                      "rejections_by_reason": _counts(rej)})


def validate_accounts(df: pd.DataFrame, customer_ids: set[str]) -> ValidationResult:
    check_columns(df, "accounts")
    rejected: list[pd.DataFrame] = []
    n_in = len(df)
    df = df.copy()
    for c in ["ACCOUNT_ID", "CUSTOMER_ID"]:
        df[c] = df[c].astype(str).str.strip()
    df["ACCOUNT_TYPE"] = df["ACCOUNT_TYPE"].astype(str).str.strip().str.upper()
    df["COUNTRY"] = df["COUNTRY"].astype(str).str.strip().str.upper()
    df = _reject(df, df["ACCOUNT_ID"].isin(["", "nan"]), "missing_account_id", rejected)
    df = _reject(df, df.duplicated("ACCOUNT_ID", keep="first"), "duplicate_account_id", rejected)
    df = _reject(df, ~df["CUSTOMER_ID"].isin(customer_ids), "unknown_customer", rejected)
    df["INIT_BALANCE"] = pd.to_numeric(df["INIT_BALANCE"], errors="coerce")
    df = _reject(df, df["INIT_BALANCE"].isna(), "invalid_balance", rejected)
    df["IS_SAR"] = _to_bool(df["IS_SAR"]) if "IS_SAR" in df else False
    if "OPEN_DATE" in df:
        df["OPEN_DATE"] = pd.to_datetime(df["OPEN_DATE"], errors="coerce").dt.date
    if "BANK_ID" not in df:
        df["BANK_ID"] = "UNKNOWN"
    rej = pd.concat(rejected) if rejected else pd.DataFrame()
    return ValidationResult(df, rej, {"input_rows": n_in, "clean_rows": len(df), "rejected_rows": len(rej),
                                      "rejections_by_reason": _counts(rej)})


def validate_transactions(df: pd.DataFrame, account_ids: set[str]) -> ValidationResult:
    """Clean + validate transactions. Fixable issues (whitespace, case) are repaired and counted."""
    check_columns(df, "transactions")
    rejected: list[pd.DataFrame] = []
    n_in = len(df)
    df = df.copy()
    fixes = {}

    raw_type = df["TX_TYPE"].astype(str)
    df["TX_TYPE"] = raw_type.str.strip().str.upper()
    fixes["normalised_tx_type"] = int((raw_type != df["TX_TYPE"]).sum())
    for c in ["SENDER_ACCOUNT_ID", "RECEIVER_ACCOUNT_ID"]:
        df[c] = df[c].fillna("").astype(str).str.strip()

    # exact duplicate rows first, then conflicting re-use of a TX_ID
    df = _reject(df, df.duplicated(keep="first"), "duplicate_row", rejected)
    df = _reject(df, df.duplicated("TX_ID", keep="first"), "duplicate_tx_id", rejected)
    df = _reject(df, (df["SENDER_ACCOUNT_ID"] == "") | (df["RECEIVER_ACCOUNT_ID"] == ""), "missing_account_reference", rejected)
    df = _reject(df, ~df["SENDER_ACCOUNT_ID"].isin(account_ids) | ~df["RECEIVER_ACCOUNT_ID"].isin(account_ids),
                 "unknown_account", rejected)
    df = _reject(df, df["SENDER_ACCOUNT_ID"] == df["RECEIVER_ACCOUNT_ID"], "self_transfer", rejected)
    df["TX_AMOUNT"] = pd.to_numeric(df["TX_AMOUNT"], errors="coerce")
    df = _reject(df, df["TX_AMOUNT"].isna() | (df["TX_AMOUNT"] <= 0), "non_positive_or_invalid_amount", rejected)
    df["TIMESTAMP"] = pd.to_datetime(df["TIMESTAMP"], errors="coerce")
    df = _reject(df, df["TIMESTAMP"].isna(), "invalid_timestamp", rejected)
    df = _reject(df, ~df["TX_TYPE"].isin(VALID_TX_TYPES), "unknown_tx_type", rejected)

    df["TX_ID"] = pd.to_numeric(df["TX_ID"], errors="coerce").astype("int64")
    df["IS_SAR"] = _to_bool(df["IS_SAR"]) if "IS_SAR" in df else False
    if "ALERT_ID" in df:
        df["ALERT_ID"] = pd.to_numeric(df["ALERT_ID"], errors="coerce").fillna(-1).astype(int)
    else:
        df["ALERT_ID"] = -1
    df = df.sort_values(["TIMESTAMP", "TX_ID"]).reset_index(drop=True)
    rej = pd.concat(rejected) if rejected else pd.DataFrame()
    return ValidationResult(df, rej, {"input_rows": n_in, "clean_rows": len(df), "rejected_rows": len(rej),
                                      "rejections_by_reason": _counts(rej), "auto_fixes": fixes})


def categorise(tx: pd.DataFrame, accounts: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    """Attach customer ids, cross-border flag and a business category to each transaction."""
    acc = accounts[["ACCOUNT_ID", "CUSTOMER_ID", "COUNTRY"]].merge(
        customers[["CUSTOMER_ID", "SEGMENT"]], on="CUSTOMER_ID", how="left")
    s = acc.add_prefix("S_").rename(columns={"S_ACCOUNT_ID": "SENDER_ACCOUNT_ID"})
    r = acc.add_prefix("R_").rename(columns={"R_ACCOUNT_ID": "RECEIVER_ACCOUNT_ID"})
    out = tx.merge(s, on="SENDER_ACCOUNT_ID", how="left").merge(r, on="RECEIVER_ACCOUNT_ID", how="left")
    out["IS_CROSS_BORDER"] = out["S_COUNTRY"] != out["R_COUNTRY"]
    s_biz = out["S_SEGMENT"] != "RETAIL"
    r_biz = out["R_SEGMENT"] != "RETAIL"
    cat = pd.Series("P2P_TRANSFER", index=out.index)
    cat[~s_biz & r_biz] = "MERCHANT_PAYMENT"
    cat[s_biz & r_biz] = "BUSINESS_TRANSFER"
    cat[s_biz & ~r_biz] = "BUSINESS_TO_PERSON"
    cat[(out["S_SEGMENT"] == "CORPORATE") & ~r_biz & (out["TX_TYPE"] == "TRANSFER")] = "SALARY_OR_PAYROLL"
    out["CATEGORY"] = cat
    return out


def _counts(rej: pd.DataFrame) -> dict:
    if rej.empty:
        return {}
    return {k: int(v) for k, v in rej["REJECT_REASON"].value_counts().items()}
