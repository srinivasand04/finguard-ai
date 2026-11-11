"""PostgreSQL schema (Phase 1 tables).

Phase 1 creates: customers, accounts, transactions, fraud_predictions,
customer_risk, alerts, model_versions, audit_logs.
Investigation/evidence/report/approval tables arrive in Phase 3.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric,
                        String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# BIGINT in Postgres, INTEGER in SQLite (so autoincrement works in the test database)
BigID = BigInteger().with_variant(Integer, "sqlite")


class Customer(Base):
    __tablename__ = "customers"
    customer_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    segment: Mapped[str] = mapped_column(String(20), index=True)  # RETAIL / SME / CORPORATE
    country: Mapped[str] = mapped_column(String(2), index=True)
    occupation: Mapped[str | None] = mapped_column(String(80))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    onboarding_date: Mapped[date] = mapped_column(Date)
    kyc_level: Mapped[str] = mapped_column(String(20))
    pep_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list["Account"]] = relationship(back_populates="customer")
    risk: Mapped["CustomerRisk | None"] = relationship(back_populates="customer", uselist=False)


class Account(Base):
    __tablename__ = "accounts"
    account_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    account_type: Mapped[str] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2))
    bank_id: Mapped[str] = mapped_column(String(20))
    initial_balance: Mapped[float] = mapped_column(Numeric(18, 2))
    opened_date: Mapped[date] = mapped_column(Date)
    # Ground-truth label from the simulator. Used only for training/evaluation, never shown as a verdict.
    sim_is_sar: Mapped[bool] = mapped_column(Boolean, default=False)

    customer: Mapped[Customer] = relationship(back_populates="accounts")


class Transaction(Base):
    __tablename__ = "transactions"
    transaction_id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=False)
    sender_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    receiver_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    sender_customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    receiver_customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    tx_type: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(30))  # derived categorisation
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    is_cross_border: Mapped[bool] = mapped_column(Boolean, default=False)
    # Simulator labels (training/evaluation only)
    sim_is_sar: Mapped[bool] = mapped_column(Boolean, default=False)
    sim_alert_id: Mapped[int | None] = mapped_column(Integer)
    source_file: Mapped[str | None] = mapped_column(String(120))
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_tx_sender_ts", "sender_account_id", "timestamp"),
        Index("ix_tx_receiver_ts", "receiver_account_id", "timestamp"),
        Index("ix_tx_sender_cust", "sender_customer_id"),
        Index("ix_tx_receiver_cust", "receiver_customer_id"),
        Index("ix_tx_timestamp", "timestamp"),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(60))  # fraud_xgboost / fraud_random_forest / anomaly_isolation_forest
    version: Mapped[str] = mapped_column(String(40))
    model_type: Mapped[str] = mapped_column(String(40))  # supervised / unsupervised
    algorithm: Mapped[str] = mapped_column(String(60))
    artifact_path: Mapped[str] = mapped_column(String(300))
    features: Mapped[list] = mapped_column(JSON)
    hyperparameters: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    feature_importance: Mapped[dict] = mapped_column(JSON)
    training_data: Mapped[dict] = mapped_column(JSON)  # row counts, time split, data hash
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("model_name", "version"),)


class FraudPrediction(Base):
    __tablename__ = "fraud_predictions"
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.transaction_id"), index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    anomaly_model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    fraud_probability: Mapped[float] = mapped_column(Float)
    anomaly_score: Mapped[float | None] = mapped_column(Float)  # 0..1, higher = more unusual
    risk_score: Mapped[float] = mapped_column(Float, index=True)  # blended 0..100
    risk_band: Mapped[str] = mapped_column(String(10), index=True)  # LOW / MEDIUM / HIGH
    top_factors: Mapped[list] = mapped_column(JSON)
    scored_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CustomerRisk(Base):
    __tablename__ = "customer_risk"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), primary_key=True)
    risk_score: Mapped[float] = mapped_column(Float, index=True)  # 0..100
    risk_level: Mapped[str] = mapped_column(String(10), index=True)  # LOW / MEDIUM / HIGH
    indicators: Mapped[list] = mapped_column(JSON)  # explainable indicator list
    profile: Mapped[dict] = mapped_column(JSON)  # behavioural profile metrics
    scoring_version: Mapped[str] = mapped_column(String(40))
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped[Customer] = relationship(back_populates="risk")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(30))  # ML_MODEL / ANOMALY_MODEL / RULE / CUSTOMER_RISK
    severity: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"), index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.account_id"))
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.transaction_id"))
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(80))  # user id or "system:<job>"
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
