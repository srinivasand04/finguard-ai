from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db import get_session
from app.models import AuditLog, Customer, FraudPrediction, Transaction
from app.schemas import Page, PredictionOut, ScoreRequest, ScoreResponse, TransactionDetail, TransactionOut

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])
SessionDep = Annotated[Session, Depends(get_session)]

SORTS = {
    "timestamp_desc": Transaction.timestamp.desc(),
    "timestamp_asc": Transaction.timestamp.asc(),
    "amount_desc": Transaction.amount.desc(),
    "risk_desc": FraudPrediction.risk_score.desc().nulls_last(),
}


def base_query() -> Select:
    return select(Transaction, FraudPrediction).outerjoin(
        FraudPrediction, FraudPrediction.transaction_id == Transaction.transaction_id)


def to_out(t: Transaction, p: FraudPrediction | None) -> TransactionOut:
    return TransactionOut(
        transaction_id=t.transaction_id, sender_account_id=t.sender_account_id,
        receiver_account_id=t.receiver_account_id, sender_customer_id=t.sender_customer_id,
        receiver_customer_id=t.receiver_customer_id, tx_type=t.tx_type, category=t.category,
        amount=float(t.amount), currency=t.currency, timestamp=t.timestamp, is_cross_border=t.is_cross_border,
        risk_score=p.risk_score if p else None, risk_band=p.risk_band if p else None,
        fraud_probability=p.fraud_probability if p else None, anomaly_score=p.anomaly_score if p else None)


def list_transactions(session: Session, *, customer_id=None, account_id=None, tx_type=None, category=None,
                      min_amount=None, max_amount=None, date_from=None, date_to=None, risk_band=None,
                      cross_border=None, sort="timestamp_desc", page=1, size=50) -> Page[TransactionOut]:
    q = base_query()
    conds = []
    if customer_id:
        conds.append(or_(Transaction.sender_customer_id == customer_id, Transaction.receiver_customer_id == customer_id))
    if account_id:
        conds.append(or_(Transaction.sender_account_id == account_id, Transaction.receiver_account_id == account_id))
    if tx_type:
        conds.append(Transaction.tx_type == tx_type.upper())
    if category:
        conds.append(Transaction.category == category.upper())
    if min_amount is not None:
        conds.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        conds.append(Transaction.amount <= max_amount)
    if date_from:
        conds.append(Transaction.timestamp >= date_from)
    if date_to:
        conds.append(Transaction.timestamp <= date_to)
    if risk_band:
        conds.append(FraudPrediction.risk_band == risk_band.upper())
    if cross_border is not None:
        conds.append(Transaction.is_cross_border.is_(cross_border))
    if conds:
        q = q.where(*conds)
    total = session.scalar(select(func.count()).select_from(q.subquery()))
    rows = session.execute(q.order_by(SORTS[sort], Transaction.transaction_id).offset((page - 1) * size).limit(size)).all()
    return Page(items=[to_out(t, p) for t, p in rows], total=total or 0, page=page, size=size)


@router.get("", response_model=Page[TransactionOut], summary="Search and filter transactions")
def search(session: SessionDep,
           customer_id: str | None = None, account_id: str | None = None,
           tx_type: str | None = Query(None, description="TRANSFER / PAYMENT / WIRE"),
           category: str | None = None,
           min_amount: float | None = Query(None, ge=0), max_amount: float | None = Query(None, ge=0),
           date_from: datetime | None = None, date_to: datetime | None = None,
           risk_band: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
           cross_border: bool | None = None,
           sort: Literal["timestamp_desc", "timestamp_asc", "amount_desc", "risk_desc"] = "timestamp_desc",
           page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200)):
    return list_transactions(session, customer_id=customer_id, account_id=account_id, tx_type=tx_type,
                             category=category, min_amount=min_amount, max_amount=max_amount, date_from=date_from,
                             date_to=date_to, risk_band=risk_band, cross_border=cross_border, sort=sort,
                             page=page, size=size)


@router.get("/{transaction_id}", response_model=TransactionDetail, summary="Transaction with ML prediction and explanation")
def get_transaction(transaction_id: int, session: SessionDep):
    row = session.execute(base_query().where(Transaction.transaction_id == transaction_id)).first()
    if not row:
        raise HTTPException(404, f"Transaction {transaction_id} not found")
    t, p = row
    s_name = session.get(Customer, t.sender_customer_id)
    r_name = session.get(Customer, t.receiver_customer_id)
    out = TransactionDetail(**to_out(t, p).model_dump(),
                            sender_name=s_name.full_name if s_name else None,
                            receiver_name=r_name.full_name if r_name else None)
    if p:
        out.prediction = PredictionOut(fraud_probability=p.fraud_probability, anomaly_score=p.anomaly_score,
                                       risk_score=p.risk_score, risk_band=p.risk_band, top_factors=p.top_factors,
                                       model_version_id=p.model_version_id)
    return out


@router.post("/score", response_model=ScoreResponse, summary="Near-real-time scoring of a new transaction (not stored)")
def score(req: ScoreRequest, session: SessionDep):
    from ml.scoring import score_single

    if req.sender_account_id == req.receiver_account_id:
        raise HTTPException(422, "Sender and receiver must differ")
    try:
        result = score_single(session.get_bind(), req.model_dump())
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    session.add(AuditLog(actor="api:anonymous", action="TRANSACTION_SCORED", entity_type="account",
                         entity_id=req.sender_account_id,
                         details={"request": req.model_dump(mode="json"), "risk_score": result["risk_score"],
                                  "model_version_id": result["model_version_id"]}))
    session.commit()
    return ScoreResponse(**result)
