from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.routers.transactions import list_transactions
from app.db import get_session
from app.models import Alert, Customer, CustomerRisk, Transaction
from app.schemas import (AccountOut, CustomerDetail, CustomerRiskOut, CustomerSummary, Page, TransactionOut)

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])
SessionDep = Annotated[Session, Depends(get_session)]


def risk_out(r: CustomerRisk) -> CustomerRiskOut:
    return CustomerRiskOut(customer_id=r.customer_id, risk_score=r.risk_score, risk_level=r.risk_level,
                           indicators=r.indicators, profile=r.profile, scoring_version=r.scoring_version,
                           computed_at=r.computed_at)


@router.get("", response_model=Page[CustomerSummary], summary="Search customers")
def search(session: SessionDep,
           q: str | None = Query(None, description="Customer id or name (partial)"),
           segment: Literal["RETAIL", "SME", "CORPORATE"] | None = None,
           risk_level: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
           country: str | None = None,
           sort: Literal["risk_desc", "id_asc", "name_asc"] = "risk_desc",
           page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    stmt = select(Customer, CustomerRisk).outerjoin(CustomerRisk, CustomerRisk.customer_id == Customer.customer_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Customer.customer_id.ilike(like), Customer.full_name.ilike(like)))
    if segment:
        stmt = stmt.where(Customer.segment == segment)
    if risk_level:
        stmt = stmt.where(CustomerRisk.risk_level == risk_level)
    if country:
        stmt = stmt.where(Customer.country == country.upper())
    order = {"risk_desc": CustomerRisk.risk_score.desc().nulls_last(), "id_asc": Customer.customer_id.asc(),
             "name_asc": Customer.full_name.asc()}[sort]
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.execute(stmt.order_by(order, Customer.customer_id).offset((page - 1) * size).limit(size)).all()
    items = [CustomerSummary.model_validate(c).model_copy(update={"risk_score": r.risk_score if r else None,
                                                                   "risk_level": r.risk_level if r else None})
             for c, r in rows]
    return Page(items=items, total=total, page=page, size=size)


@router.get("/{customer_id}", response_model=CustomerDetail, summary="Customer profile with accounts and risk")
def get_customer(customer_id: str, session: SessionDep):
    c = session.scalar(select(Customer).options(selectinload(Customer.accounts), selectinload(Customer.risk))
                       .where(Customer.customer_id == customer_id))
    if not c:
        raise HTTPException(404, f"Customer {customer_id} not found")
    alerts = session.scalar(select(func.count()).select_from(Alert).where(Alert.customer_id == customer_id)) or 0
    return CustomerDetail(
        customer_id=c.customer_id, full_name=c.full_name, segment=c.segment, country=c.country,
        kyc_level=c.kyc_level, pep_flag=c.pep_flag, onboarding_date=c.onboarding_date,
        occupation=c.occupation, date_of_birth=c.date_of_birth,
        accounts=[AccountOut.model_validate(a) for a in c.accounts],
        risk=risk_out(c.risk) if c.risk else None,
        risk_score=c.risk.risk_score if c.risk else None, risk_level=c.risk.risk_level if c.risk else None,
        alert_count=alerts)


@router.get("/{customer_id}/risk", response_model=CustomerRiskOut, summary="Explainable customer risk profile")
def get_risk(customer_id: str, session: SessionDep):
    r = session.get(CustomerRisk, customer_id)
    if not r:
        raise HTTPException(404, f"No risk profile for {customer_id}")
    return risk_out(r)


@router.get("/{customer_id}/transactions", response_model=Page[TransactionOut], summary="Customer transaction history")
def transactions(customer_id: str, session: SessionDep,
                 risk_band: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
                 sort: Literal["timestamp_desc", "timestamp_asc", "amount_desc", "risk_desc"] = "timestamp_desc",
                 page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    if not session.get(Customer, customer_id):
        raise HTTPException(404, f"Customer {customer_id} not found")
    return list_transactions(session, customer_id=customer_id, risk_band=risk_band, sort=sort, page=page, size=size)


@router.get("/{customer_id}/counterparties", summary="Top counterparties by value (both directions)")
def counterparties(customer_id: str, session: SessionDep, limit: int = Query(15, ge=1, le=100)):
    if not session.get(Customer, customer_id):
        raise HTTPException(404, f"Customer {customer_id} not found")
    out_q = (select(Transaction.receiver_customer_id.label("cp"), func.count().label("n"),
                    func.sum(Transaction.amount).label("total"))
             .where(Transaction.sender_customer_id == customer_id).group_by(Transaction.receiver_customer_id))
    in_q = (select(Transaction.sender_customer_id.label("cp"), func.count().label("n"),
                   func.sum(Transaction.amount).label("total"))
            .where(Transaction.receiver_customer_id == customer_id).group_by(Transaction.sender_customer_id))
    agg: dict[str, dict] = {}
    for direction, q in (("out", out_q), ("in", in_q)):
        for cp, n, total in session.execute(q):
            d = agg.setdefault(cp, {"customer_id": cp, "out_count": 0, "out_total": 0.0, "in_count": 0, "in_total": 0.0})
            d[f"{direction}_count"] += n
            d[f"{direction}_total"] += float(total)
    names = dict(session.execute(select(Customer.customer_id, Customer.full_name).where(Customer.customer_id.in_(agg))).all())
    risk = dict(session.execute(select(CustomerRisk.customer_id, CustomerRisk.risk_level).where(CustomerRisk.customer_id.in_(agg))).all())
    rows = sorted(agg.values(), key=lambda d: -(d["out_total"] + d["in_total"]))[:limit]
    for d in rows:
        d["name"] = names.get(d["customer_id"])
        d["risk_level"] = risk.get(d["customer_id"])
        d["out_total"], d["in_total"] = round(d["out_total"], 2), round(d["in_total"], 2)
    return {"customer_id": customer_id, "counterparties": rows}
