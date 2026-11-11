"""Health, dashboard, model registry and audit endpoints."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, case, cast, func, select, text
from sqlalchemy.orm import Session

from app import cache
from app.db import get_session
from app.models import Account, Alert, AuditLog, Customer, CustomerRisk, FraudPrediction, ModelVersion, Transaction
from app.schemas import DISCLAIMER, AuditLogOut, ModelVersionOut, Page

router = APIRouter(tags=["system"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/health")
def health(session: SessionDep):
    try:
        session.execute(text("SELECT 1"))
        db = True
    except Exception:
        db = False
    return {"status": "ok" if db else "degraded", "database": db, "redis": cache.ping()}


def _summary(session: Session) -> dict:
    n = lambda m: session.scalar(select(func.count()).select_from(m)) or 0  # noqa: E731
    tx_stats = session.execute(select(func.count(), func.coalesce(func.sum(Transaction.amount), 0),
                                      func.min(Transaction.timestamp), func.max(Transaction.timestamp))).one()
    bands = dict(session.execute(select(FraudPrediction.risk_band, func.count()).group_by(FraudPrediction.risk_band)).all())
    levels = dict(session.execute(select(CustomerRisk.risk_level, func.count()).group_by(CustomerRisk.risk_level)).all())
    alert_types = dict(session.execute(select(Alert.alert_type, func.count()).group_by(Alert.alert_type)).all())
    alert_sev = dict(session.execute(select(Alert.severity, func.count()).group_by(Alert.severity)).all())
    categories = [{"category": c, "count": k, "total": round(float(t), 2)} for c, k, t in session.execute(
        select(Transaction.category, func.count(), func.sum(Transaction.amount)).group_by(Transaction.category)
        .order_by(func.count().desc()))]
    active = session.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))).all()
    return {
        "customers": n(Customer), "accounts": n(Account), "transactions": tx_stats[0],
        "total_volume": round(float(tx_stats[1]), 2),
        "period": {"from": tx_stats[2], "to": tx_stats[3]},
        "transaction_risk_bands": bands,
        "customer_risk_levels": levels,
        "alerts": {"total": sum(alert_types.values()), "by_type": alert_types, "by_severity": alert_sev,
                   "open": session.scalar(select(func.count()).select_from(Alert).where(Alert.status == "OPEN")) or 0},
        "categories": categories,
        "active_models": [{"id": m.id, "name": m.model_name, "version": m.version,
                           "pr_auc": m.metrics.get("pr_auc", m.metrics.get("pr_auc_vs_sar_labels")),
                           "roc_auc": m.metrics.get("roc_auc", m.metrics.get("roc_auc_vs_sar_labels"))} for m in active],
        "disclaimer": DISCLAIMER,
    }


@router.get("/api/v1/dashboard/summary", summary="Headline monitoring metrics (cached in Redis)")
def summary(session: SessionDep):
    return cache.cached("dashboard:summary", lambda: _summary(session))


@router.get("/api/v1/dashboard/timeseries", summary="Daily volume and flagged activity")
def timeseries(session: SessionDep):
    def produce():
        day = func.date(Transaction.timestamp)
        q = (select(day, func.count(), func.sum(Transaction.amount),
                    func.sum(case((FraudPrediction.risk_band == "HIGH", 1), else_=0)),
                    func.sum(case((FraudPrediction.risk_band == "MEDIUM", 1), else_=0)))
             .outerjoin(FraudPrediction, FraudPrediction.transaction_id == Transaction.transaction_id)
             .group_by(day).order_by(day))
        return [{"date": str(d), "count": c, "volume": round(float(v or 0), 2), "high": int(h or 0), "medium": int(m or 0)}
                for d, c, v, h, m in session.execute(q)]
    return cache.cached("dashboard:timeseries", produce)


@router.get("/api/v1/dashboard/risk-distribution", summary="Histogram of transaction and customer risk scores")
def risk_distribution(session: SessionDep):
    def produce():
        def hist(col):
            # Postgres CAST(float AS int) rounds, so floor explicitly; SQLite's CAST truncates (== floor for >= 0)
            pg = session.get_bind().dialect.name == "postgresql"
            bucket = case((col >= 90, 9), else_=cast(func.floor(col / 10) if pg else col / 10, Integer))
            return {int(b): c for b, c in session.execute(select(bucket, func.count()).group_by(bucket))}
        tx, cu = hist(FraudPrediction.risk_score), hist(CustomerRisk.risk_score)
        return [{"bucket": f"{i * 10}-{i * 10 + 9}", "transactions": tx.get(i, 0), "customers": cu.get(i, 0)} for i in range(10)]
    return cache.cached("dashboard:risk_distribution", produce)


@router.get("/api/v1/models", response_model=list[ModelVersionOut], tags=["models"])
def models(session: SessionDep, active_only: bool = False):
    q = select(ModelVersion).order_by(ModelVersion.created_at.desc(), ModelVersion.id.desc())
    if active_only:
        q = q.where(ModelVersion.is_active.is_(True))
    return session.scalars(q).all()


@router.get("/api/v1/models/{model_id}", response_model=ModelVersionOut, tags=["models"])
def model(model_id: int, session: SessionDep):
    m = session.get(ModelVersion, model_id)
    if not m:
        raise HTTPException(404, f"Model {model_id} not found")
    return m


@router.get("/api/v1/audit-logs", response_model=Page[AuditLogOut], tags=["governance"])
def audit_logs(session: SessionDep, action: str | None = None,
               page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action == action)
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.scalars(q.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    return Page(items=rows, total=total, page=page, size=size)
