from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Alert, Customer
from app.schemas import AlertOut, Page

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=Page[AlertOut], summary="List alerts (read-only in Phase 1)")
def list_alerts(session: SessionDep,
                alert_type: Literal["HIGH_RISK_TRANSACTION", "ANOMALOUS_TRANSACTION", "POSSIBLE_STRUCTURING",
                                    "HIGH_RISK_CUSTOMER", "CIRCULAR_FLOW", "LAYERING_CHAIN",
                                    "SUSPICIOUS_NETWORK"] | None = None,
                severity: Literal["MEDIUM", "HIGH", "CRITICAL"] | None = None,
                status: str | None = None, customer_id: str | None = None,
                page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    stmt = select(Alert, Customer.full_name).join(Customer, Customer.customer_id == Alert.customer_id)
    for col, val in ((Alert.alert_type, alert_type), (Alert.severity, severity), (Alert.status, status),
                     (Alert.customer_id, customer_id)):
        if val:
            stmt = stmt.where(col == val)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    # severity first (scores from different sources are on different scales), then score
    sev_rank = case((Alert.severity == "CRITICAL", 0), (Alert.severity == "HIGH", 1), else_=2)
    rows = session.execute(stmt.order_by(sev_rank, Alert.score.desc(), Alert.id).offset((page - 1) * size).limit(size)).all()
    return Page(items=[AlertOut.model_validate(a).model_copy(update={"customer_name": n}) for a, n in rows],
                total=total, page=page, size=size)


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: int, session: SessionDep):
    a = session.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, f"Alert {alert_id} not found")
    c = session.get(Customer, a.customer_id)
    return AlertOut.model_validate(a).model_copy(update={"customer_name": c.full_name if c else None})
