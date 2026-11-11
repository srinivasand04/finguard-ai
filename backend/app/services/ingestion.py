"""AMLSim ingestion pipeline: read -> validate/clean -> categorise -> load into PostgreSQL."""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services import validation as v

log = logging.getLogger(__name__)

# Child tables first so truncation respects foreign keys
LOAD_ORDER = ["customers", "accounts", "transactions"]
DEPENDENTS = ["alerts", "fraud_predictions", "customer_risk"]


def bulk_insert(df: pd.DataFrame, table: str, engine: Engine) -> None:
    """COPY into Postgres (fast); plain inserts for other dialects (tests use SQLite)."""
    if df.empty:
        return
    if engine.dialect.name == "postgresql":
        buf = io.StringIO()
        df.to_csv(buf, index=False, header=False, na_rep="\\N")
        buf.seek(0)
        cols = ", ".join(df.columns)
        raw = engine.raw_connection()
        try:
            with raw.cursor() as cur:
                with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')") as cp:
                    while chunk := buf.read(1 << 20):
                        cp.write(chunk)
            raw.commit()
        finally:
            raw.close()
    else:
        df.to_sql(table, engine, if_exists="append", index=False, chunksize=2000)


def truncate(engine: Engine, tables: list[str]) -> None:
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        else:
            for t in tables:
                conn.execute(text(f"DELETE FROM {t}"))


def run_ingestion(source_dir: Path, engine: Engine, processed_dir: Path) -> dict:
    """Full (idempotent) reload of the transactional data. Returns a validation report."""
    started = datetime.now()
    source_dir = Path(source_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    raw = {name: pd.read_csv(source_dir / f"{name}.csv", dtype=str, keep_default_na=False)
           for name in ["customers", "accounts", "transactions"]}

    cust = v.validate_customers(raw["customers"])
    acc = v.validate_accounts(raw["accounts"], set(cust.clean["CUSTOMER_ID"]))
    tx = v.validate_transactions(raw["transactions"], set(acc.clean["ACCOUNT_ID"]))
    txc = v.categorise(tx.clean, acc.clean, cust.clean)

    for name, res in [("customers", cust), ("accounts", acc), ("transactions", tx)]:
        if not res.rejected.empty:
            res.rejected.to_csv(processed_dir / f"rejected_{name}.csv", index=False)

    customers_db = pd.DataFrame({
        "customer_id": cust.clean["CUSTOMER_ID"],
        "full_name": cust.clean["FULL_NAME"],
        "segment": cust.clean["SEGMENT"],
        "country": cust.clean["COUNTRY"],
        "occupation": cust.clean.get("OCCUPATION"),
        "date_of_birth": cust.clean.get("DATE_OF_BIRTH"),
        "onboarding_date": cust.clean["ONBOARDING_DATE"],
        "kyc_level": cust.clean["KYC_LEVEL"],
        "pep_flag": cust.clean["PEP_FLAG"],
    })
    accounts_db = pd.DataFrame({
        "account_id": acc.clean["ACCOUNT_ID"],
        "customer_id": acc.clean["CUSTOMER_ID"],
        "account_type": acc.clean["ACCOUNT_TYPE"],
        "country": acc.clean["COUNTRY"],
        "bank_id": acc.clean["BANK_ID"],
        "initial_balance": acc.clean["INIT_BALANCE"].round(2),
        "opened_date": acc.clean.get("OPEN_DATE"),
        "sim_is_sar": acc.clean["IS_SAR"],
    })
    tx_db = pd.DataFrame({
        "transaction_id": txc["TX_ID"],
        "sender_account_id": txc["SENDER_ACCOUNT_ID"],
        "receiver_account_id": txc["RECEIVER_ACCOUNT_ID"],
        "sender_customer_id": txc["S_CUSTOMER_ID"],
        "receiver_customer_id": txc["R_CUSTOMER_ID"],
        "tx_type": txc["TX_TYPE"],
        "category": txc["CATEGORY"],
        "amount": txc["TX_AMOUNT"].round(2),
        "currency": "EUR",
        "timestamp": txc["TIMESTAMP"],
        "is_cross_border": txc["IS_CROSS_BORDER"],
        "sim_is_sar": txc["IS_SAR"],
        "sim_alert_id": txc["ALERT_ID"].where(txc["ALERT_ID"] >= 0),
        "source_file": f"{source_dir.name}/transactions.csv",
    })
    tx_db["sim_alert_id"] = tx_db["sim_alert_id"].astype("Int64")

    truncate(engine, DEPENDENTS + list(reversed(LOAD_ORDER)))
    bulk_insert(customers_db, "customers", engine)
    bulk_insert(accounts_db, "accounts", engine)
    bulk_insert(tx_db, "transactions", engine)

    report = {
        "source": str(source_dir),
        "started_at": started.isoformat(timespec="seconds"),
        "duration_seconds": round((datetime.now() - started).total_seconds(), 1),
        "customers": cust.report,
        "accounts": acc.report,
        "transactions": tx.report,
        "category_counts": {k: int(c) for k, c in txc["CATEGORY"].value_counts().items()},
    }
    (processed_dir / "ingestion_report.json").write_text(json.dumps(report, indent=2, default=str))
    _audit(engine, "DATA_INGESTION", "dataset", source_dir.name, report)
    return report


def _audit(engine: Engine, action: str, entity_type: str, entity_id: str, details: dict) -> None:
    from sqlalchemy.orm import Session

    from app.models import AuditLog

    with Session(engine) as s:
        s.add(AuditLog(actor="system:ingestion", action=action, entity_type=entity_type, entity_id=entity_id,
                       details=json.loads(json.dumps(details, default=str))))
        s.commit()
