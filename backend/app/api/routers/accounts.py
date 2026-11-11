from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Account, FraudPrediction, Transaction
from app.schemas import AccountOut

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: str, session: SessionDep):
    a = session.get(Account, account_id)
    if not a:
        raise HTTPException(404, f"Account {account_id} not found")
    return a


@router.get("/{account_id}/velocity", summary="Transaction velocity: windowed counts/values and daily series")
def velocity(account_id: str, session: SessionDep, days: int = Query(30, ge=1, le=365)):
    if not session.get(Account, account_id):
        raise HTTPException(404, f"Account {account_id} not found")
    # data is historical/synthetic, so windows are anchored on the latest transaction in the dataset
    as_of = session.scalar(select(func.max(Transaction.timestamp)))
    if as_of is None:
        return {"account_id": account_id, "as_of": None, "windows": {}, "daily": []}

    def window(direction_col, hours):
        since = as_of - timedelta(hours=hours)
        n, total = session.execute(select(func.count(), func.coalesce(func.sum(Transaction.amount), 0))
                                   .where(direction_col == account_id, Transaction.timestamp > since)).one()
        return {"count": n, "total": round(float(total), 2)}

    windows = {}
    for label, hours in (("24h", 24), ("7d", 24 * 7), ("30d", 24 * 30), ("90d", 24 * 90)):
        windows[label] = {"outgoing": window(Transaction.sender_account_id, hours),
                          "incoming": window(Transaction.receiver_account_id, hours)}

    since = as_of - timedelta(days=days)
    day = func.date(Transaction.timestamp)
    daily = {}
    for col, key in ((Transaction.sender_account_id, "out"), (Transaction.receiver_account_id, "in")):
        q = (select(day.label("d"), func.count(), func.sum(Transaction.amount),
                    func.sum(case((FraudPrediction.risk_band == "HIGH", 1), else_=0)))
             .outerjoin(FraudPrediction, FraudPrediction.transaction_id == Transaction.transaction_id)
             .where(col == account_id, Transaction.timestamp > since).group_by(day))
        for d, n, total, high in session.execute(q):
            row = daily.setdefault(str(d), {"date": str(d), "out_count": 0, "out_total": 0.0, "in_count": 0,
                                            "in_total": 0.0, "high_risk": 0})
            row[f"{key}_count"] = n
            row[f"{key}_total"] = round(float(total or 0), 2)
            row["high_risk"] += int(high or 0)
    return {"account_id": account_id, "as_of": as_of, "windows": windows,
            "daily": sorted(daily.values(), key=lambda r: r["date"])}
