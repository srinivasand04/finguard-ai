"""The FinGuard tool registry.

Agents never query the database directly - they call these tools, exactly like an
external AI client calls them over MCP. Every call goes through `call_tool`, which:

1. validates arguments against a Pydantic model (bad input never reaches SQL),
2. checks the caller's role against the tool's permission,
3. blocks write tools when the caller is in read-only mode (the MCP default),
4. runs the tool and returns plain JSON-serialisable data,
5. writes an audit-log entry and a Prometheus counter - success, denial or error.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import String, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import (Account, AccountGraphMetrics, Alert, Approval, AuditLog, Customer, CustomerRisk,
                        FraudPrediction, GraphPattern, Investigation, ModelVersion, SuspiciousNetwork, Transaction)
from app.observability import TOOL_CALLS
from app.security import Actor
from app.services import cases


class ToolError(RuntimeError):
    pass


class ToolDenied(PermissionError):
    pass


@dataclass
class Tool:
    name: str
    description: str
    permission: str
    writes: bool
    args: type[BaseModel]
    fn: Callable[..., dict]


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
        return float(v)
    return v


def _js(v):
    return json.loads(v) if isinstance(v, str) else v


# --------------------------------------------------------------------------- argument models
CustomerId = Field(pattern=r"^CUST\d{4,8}$", description="Customer id, e.g. CUST10025")


class CustomerArgs(BaseModel):
    customer_id: str = CustomerId


class HistoryArgs(BaseModel):
    customer_id: str = CustomerId
    limit: int = Field(15, ge=1, le=100, description="How many of the riskiest transactions to return")


class PredictionArgs(BaseModel):
    customer_id: str = CustomerId
    min_band: str = Field("MEDIUM", pattern=r"^(LOW|MEDIUM|HIGH)$")
    limit: int = Field(10, ge=1, le=50)


class PolicyArgs(BaseModel):
    query: str = Field(min_length=3, max_length=300)
    k: int = Field(3, ge=1, le=8)
    doc_type: str | None = Field(None, max_length=40)


class CreateCaseArgs(BaseModel):
    request_text: str = Field(min_length=5, max_length=2000)
    customer_id: str | None = Field(None, pattern=r"^CUST\d{4,8}$")


class CaseArgs(BaseModel):
    investigation_id: int = Field(ge=1)


class SubmitArgs(BaseModel):
    investigation_id: int = Field(ge=1)
    comment: str | None = Field(None, max_length=2000)


# --------------------------------------------------------------------------- read tools
def get_customer_profile(session: Session, actor: Actor, a: CustomerArgs) -> dict:
    c = session.get(Customer, a.customer_id)
    if not c:
        raise ToolError(f"Customer {a.customer_id} not found")
    r = session.get(CustomerRisk, a.customer_id)
    accounts = session.scalars(select(Account).where(Account.customer_id == c.customer_id)).all()
    alerts = session.execute(select(Alert.alert_type, func.count()).where(Alert.customer_id == c.customer_id)
                             .group_by(Alert.alert_type)).all()
    return {
        "customer": {"customer_id": c.customer_id, "full_name": c.full_name, "segment": c.segment, "country": c.country,
                     "occupation": c.occupation, "kyc_level": c.kyc_level, "pep_flag": c.pep_flag,
                     "onboarding_date": c.onboarding_date,
                     "date_of_birth": c.date_of_birth if actor.can("view_pii") else None},
        "accounts": [{"account_id": x.account_id, "type": x.account_type, "country": x.country,
                      "opened_date": x.opened_date} for x in accounts],
        "risk": None if not r else {"score": r.risk_score, "level": r.risk_level, "indicators": _js(r.indicators),
                                    "profile": _js(r.profile), "scoring_version": r.scoring_version},
        "alerts_by_type": dict(alerts),
    }


def get_transaction_history(session: Session, actor: Actor, a: HistoryArgs) -> dict:
    cid = a.customer_id
    involve = or_(Transaction.sender_customer_id == cid, Transaction.receiver_customer_id == cid)
    stats = session.execute(select(func.count(), func.coalesce(func.sum(Transaction.amount), 0), func.min(Transaction.timestamp),
                                   func.max(Transaction.timestamp)).where(involve)).one()
    out_stats = session.execute(select(func.count(), func.coalesce(func.sum(Transaction.amount), 0))
                                .where(Transaction.sender_customer_id == cid)).one()
    xb = session.scalar(select(func.count()).where(involve, Transaction.is_cross_border.is_(True))) or 0
    near = session.scalar(select(func.count()).where(Transaction.sender_customer_id == cid,
                                                     Transaction.amount >= 9000, Transaction.amount < 10000)) or 0
    cats = dict(session.execute(select(Transaction.category, func.count()).where(involve).group_by(Transaction.category)).all())
    top = session.execute(select(Transaction, FraudPrediction).join(FraudPrediction, FraudPrediction.transaction_id == Transaction.transaction_id)
                          .where(involve).order_by(desc(FraudPrediction.risk_score)).limit(a.limit)).all()
    return {
        "customer_id": cid, "transaction_count": stats[0], "total_value": round(float(stats[1]), 2),
        "first_seen": stats[2], "last_seen": stats[3], "outgoing_count": out_stats[0],
        "outgoing_value": round(float(out_stats[1]), 2), "cross_border_count": xb,
        "near_threshold_outgoing": near, "categories": cats,
        "riskiest_transactions": [{
            "transaction_id": t.transaction_id, "timestamp": t.timestamp, "direction": "OUT" if t.sender_customer_id == cid else "IN",
            "counterparty": t.receiver_customer_id if t.sender_customer_id == cid else t.sender_customer_id,
            "sender_account_id": t.sender_account_id, "receiver_account_id": t.receiver_account_id,
            "amount": float(t.amount), "tx_type": t.tx_type, "is_cross_border": t.is_cross_border,
            "risk_score": p.risk_score, "risk_band": p.risk_band} for t, p in top],
    }


def get_fraud_prediction(session: Session, actor: Actor, a: PredictionArgs) -> dict:
    cid = a.customer_id
    bands = {"LOW": ["LOW", "MEDIUM", "HIGH"], "MEDIUM": ["MEDIUM", "HIGH"], "HIGH": ["HIGH"]}[a.min_band]
    involve = or_(Transaction.sender_customer_id == cid, Transaction.receiver_customer_id == cid)
    rows = session.execute(select(Transaction, FraudPrediction).join(FraudPrediction, FraudPrediction.transaction_id == Transaction.transaction_id)
                           .where(involve, FraudPrediction.risk_band.in_(bands))
                           .order_by(desc(FraudPrediction.fraud_probability)).limit(a.limit)).all()
    counts = dict(session.execute(select(FraudPrediction.risk_band, func.count())
                                  .join(Transaction, Transaction.transaction_id == FraudPrediction.transaction_id)
                                  .where(involve).group_by(FraudPrediction.risk_band)).all())
    model = session.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True), ModelVersion.model_name == "fraud_xgboost"))
    return {
        "customer_id": cid, "band_counts": counts,
        "model": None if not model else {"id": model.id, "name": model.model_name, "version": model.version,
                                         "pr_auc": model.metrics.get("pr_auc"), "roc_auc": model.metrics.get("roc_auc")},
        "predictions": [{"transaction_id": t.transaction_id, "timestamp": t.timestamp, "amount": float(t.amount),
                         "fraud_probability": p.fraud_probability, "anomaly_percentile": p.anomaly_score,
                         "risk_score": p.risk_score, "risk_band": p.risk_band, "model_version_id": p.model_version_id,
                         "top_factors": [f["description"] for f in _js(p.top_factors)][:3]} for t, p in rows],
        "note": "ML outputs are indicators for review, not proof of wrongdoing.",
    }


def get_account_relationships(session: Session, actor: Actor, a: CustomerArgs) -> dict:
    cid = a.customer_id
    metrics = session.scalars(select(AccountGraphMetrics).where(AccountGraphMetrics.customer_id == cid)).all()
    pats = session.scalars(select(GraphPattern).where(cast(GraphPattern.customer_ids, String).like(f'%"{cid}"%'))
                           .order_by(desc(GraphPattern.score)).limit(10)).all()
    net_ids = {m.network_id for m in metrics if m.network_id}
    nets = session.scalars(select(SuspiciousNetwork).where(SuspiciousNetwork.id.in_(net_ids))).all() if net_ids else []
    cps = session.execute(select(Transaction.receiver_customer_id, func.count(), func.sum(Transaction.amount))
                          .where(Transaction.sender_customer_id == cid).group_by(Transaction.receiver_customer_id)
                          .order_by(desc(func.sum(Transaction.amount))).limit(8)).all()
    return {
        "customer_id": cid,
        "accounts": [{"account_id": m.account_id, "in_degree": m.in_degree, "out_degree": m.out_degree,
                      "pagerank_percentile": m.pagerank_percentile, "betweenness": m.betweenness,
                      "community_id": m.community_id, "cycle_count": m.cycle_count, "chain_count": m.chain_count,
                      "network_id": m.network_id, "neighbour_high_risk_share": m.neighbour_high_risk_share} for m in metrics],
        "patterns": [{"id": p.id, "type": p.pattern_type, "route": _js(p.account_ids), "transaction_ids": _js(p.transaction_ids),
                      "hops": p.hops, "start_amount": p.start_amount, "end_amount": p.end_amount, "start_ts": p.start_ts,
                      "duration_hours": p.duration_hours, "score": p.score} for p in pats],
        "networks": [{"id": n.id, "size": n.size, "risk_level": n.risk_level, "risk_score": n.risk_score,
                      "typology_hints": _js(n.typology_hints), "hubs": _js(n.hubs)[:5], "total_value": n.total_value} for n in nets],
        "top_counterparties": [{"customer_id": c, "tx_count": n, "total_sent": round(float(t), 2)} for c, n, t in cps],
        "graph_built": bool(metrics),
    }


def search_compliance_policy(session: Session, actor: Actor, a: PolicyArgs) -> dict:
    from rag.retrieval import get_retriever

    try:
        r = get_retriever(session.get_bind())
    except Exception as e:
        raise ToolError(f"Compliance index unavailable: {e}") from e
    if r.size == 0:
        raise ToolError("Compliance index is empty - run `python -m app.cli rag-build`")
    hits = r.search(a.query, k=a.k, mode="hybrid", rerank=True, doc_type=a.doc_type)
    return {"query": a.query, "results": [{"chunk_id": h.chunk_id, "title": h.title, "doc_type": h.doc_type,
                                           "section": h.section, "page": h.page, "text": h.text,
                                           "score": round(h.score, 4)} for h in hits]}


def get_investigation_history(session: Session, actor: Actor, a: CustomerArgs) -> dict:
    invs = session.scalars(select(Investigation).where(Investigation.customer_id == a.customer_id)
                           .order_by(desc(Investigation.id)).limit(20)).all()
    out = []
    for i in invs:
        ap = session.scalar(select(Approval).where(Approval.investigation_id == i.id, Approval.decision != "PENDING")
                            .order_by(desc(Approval.id)))
        out.append({"investigation_id": i.id, "case_ref": i.case_ref, "status": i.status, "created_at": i.created_at,
                    "recommendation": i.recommendation, "assessment_score": i.assessment_score,
                    "human_decision": ap.decision if ap else None, "decided_by": ap.decided_by if ap else None})
    return {"customer_id": a.customer_id, "investigations": out}


# --------------------------------------------------------------------------- write tools
def create_investigation_case(session: Session, actor: Actor, a: CreateCaseArgs) -> dict:
    try:
        inv = cases.create_case(session, actor, a.request_text, a.customer_id)
    except cases.CaseError as e:
        raise ToolError(str(e)) from e
    return {"investigation_id": inv.id, "case_ref": inv.case_ref, "customer_id": inv.customer_id, "status": inv.status}


def generate_investigation_report(session: Session, actor: Actor, a: CaseArgs) -> dict:
    from agents.runner import run_investigation

    inv = session.get(Investigation, a.investigation_id)
    if not inv:
        raise ToolError(f"Investigation {a.investigation_id} not found")
    result = run_investigation(a.investigation_id, actor)
    return {"investigation_id": a.investigation_id, **{k: result.get(k) for k in
            ("status", "assessment_score", "recommendation", "report_id", "evidence_count", "run_id")}}


def submit_for_approval(session: Session, actor: Actor, a: SubmitArgs) -> dict:
    try:
        ap = cases.submit_for_approval(session, actor, a.investigation_id, a.comment)
    except cases.CaseError as e:
        raise ToolError(str(e)) from e
    return {"approval_id": ap.id, "investigation_id": ap.investigation_id, "decision": ap.decision,
            "note": "Submitted for human review. Only an Investigation Manager can decide."}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("get_customer_profile", "Customer KYC profile, accounts, explainable risk indicators and alert counts.",
         "view_customers", False, CustomerArgs, get_customer_profile),
    Tool("get_transaction_history", "Transaction statistics and the riskiest transactions involving a customer.",
         "view_customers", False, HistoryArgs, get_transaction_history),
    Tool("get_fraud_prediction", "ML suspicion probabilities, anomaly percentiles and explanations for a customer's transactions.",
         "view_customers", False, PredictionArgs, get_fraud_prediction),
    Tool("get_account_relationships", "Graph metrics, circular flows, layering chains and suspicious networks for a customer.",
         "view_customers", False, CustomerArgs, get_account_relationships),
    Tool("search_compliance_policy", "Hybrid search over AML/KYC policy documents; returns cited passages.",
         "ask_compliance", False, PolicyArgs, search_compliance_policy),
    Tool("get_investigation_history", "Previous investigations of a customer and their human decisions.",
         "view_investigations", False, CustomerArgs, get_investigation_history),
    Tool("create_investigation_case", "Open a new investigation case for a customer.",
         "run_investigation", True, CreateCaseArgs, create_investigation_case),
    Tool("generate_investigation_report", "Run the multi-agent investigation and produce an evidence-backed report.",
         "run_investigation", True, CaseArgs, generate_investigation_report),
    Tool("submit_for_approval", "Submit a case's report for human review (cannot approve it).",
         "submit_for_approval", True, SubmitArgs, submit_for_approval),
]}


def call_tool(name: str, actor: Actor, args: dict | None = None, session: Session | None = None,
              read_only: bool = False, audit: bool = True) -> dict:
    """Validate -> authorise -> execute -> audit. Raises ToolDenied / ToolError / ValidationError."""
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"Unknown tool {name}")
    own = session is None
    session = session or Session(get_engine())
    t0 = time.time()
    outcome, err = "ok", None
    try:
        try:
            parsed = tool.args(**(args or {}))
        except ValidationError as e:
            outcome = "invalid"
            raise ToolError(f"Invalid arguments for {name}: {e.errors(include_url=False)}") from e
        if tool.writes and read_only:
            outcome = "denied"
            raise ToolDenied(f"{name} is a write tool and this client is read-only")
        if not actor.can(tool.permission):
            outcome = "denied"
            raise ToolDenied(f"Role {actor.role} lacks '{tool.permission}' required by {name}")
        try:
            result = _jsonable(tool.fn(session, actor, parsed))
        except PermissionError as e:
            outcome = "denied"
            raise ToolDenied(str(e)) from e
        except ToolError:
            outcome = "error"
            raise
        return result
    except Exception as e:
        err = str(e)[:500]
        if outcome == "ok":
            outcome = "error"
        raise
    finally:
        TOOL_CALLS.labels(name, outcome).inc()
        if audit:
            try:
                if outcome != "ok":           # discard any half-done work before logging the failure
                    session.rollback()
                session.add(AuditLog(actor=actor.username, action="TOOL_CALL", entity_type="tool", entity_id=name,
                                     details={"args": _jsonable(args or {}), "outcome": outcome, "error": err,
                                              "role": actor.role, "ms": int((time.time() - t0) * 1000)}))
                session.commit()
            except Exception:
                session.rollback()
        if own:
            session.close()
