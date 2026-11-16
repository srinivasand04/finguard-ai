"""Investigation case API: create + run (background), timeline, evidence, report, approval workflow."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (AgentExecutionLog, Approval, Customer, Investigation, InvestigationEvidence,
                        InvestigationReport)
from app.security import Actor, require
from app.services import cases

router = APIRouter(prefix="/api/v1", tags=["investigations"])
SessionDep = Annotated[Session, Depends(get_session)]
Viewer = Annotated[Actor, Depends(require("view_investigations"))]
Runner = Annotated[Actor, Depends(require("run_investigation"))]


class NewInvestigation(BaseModel):
    request_text: str = Field(min_length=5, max_length=2000,
                              examples=["Investigate suspicious transactions involving customer CUST10025"])
    customer_id: str | None = Field(None, pattern=r"^CUST\d{4,8}$")
    title: str | None = Field(None, max_length=200)


class SubmitBody(BaseModel):
    comment: str | None = Field(None, max_length=2000)


class DecisionBody(BaseModel):
    decision: Literal["APPROVE", "ESCALATE", "REJECT", "REQUEST_MORE_INFO"]
    comment: str = Field(min_length=5, max_length=2000)


def _run_in_background(investigation_id: int, actor: Actor) -> None:
    from agents.runner import run_investigation

    run_investigation(investigation_id, actor)


def _case_out(i: Investigation, name: str | None = None) -> dict:
    return {"id": i.id, "case_ref": i.case_ref, "customer_id": i.customer_id, "customer_name": name, "title": i.title,
            "request_text": i.request_text, "status": i.status, "assessment_score": i.assessment_score,
            "recommendation": i.recommendation, "created_by": i.created_by, "run_count": i.run_count,
            "error": i.error, "created_at": i.created_at, "updated_at": i.updated_at}


@router.post("/investigations", status_code=202, summary="Open a case and start the multi-agent investigation")
def create(body: NewInvestigation, bg: BackgroundTasks, session: SessionDep, actor: Runner):
    try:
        inv = cases.create_case(session, actor, body.request_text, body.customer_id, body.title)
    except cases.CaseError as e:
        raise HTTPException(422, str(e)) from e
    bg.add_task(_run_in_background, inv.id, actor)
    return _case_out(inv)


@router.post("/investigations/{inv_id}/run", status_code=202, summary="Re-run the agents (e.g. after more info was requested)")
def rerun(inv_id: int, bg: BackgroundTasks, session: SessionDep, actor: Runner):
    inv = session.get(Investigation, inv_id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    if inv.status not in ("CREATED", "REPORT_READY", "FAILED", "MORE_INFO_REQUESTED"):
        raise HTTPException(409, f"Case is {inv.status}; it cannot be re-run now")
    bg.add_task(_run_in_background, inv.id, actor)
    return _case_out(inv)


@router.get("/investigations", summary="List cases")
def list_cases(session: SessionDep, actor: Viewer, status: str | None = None, customer_id: str | None = None,
               page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100)):
    q = select(Investigation, Customer.full_name).join(Customer, Customer.customer_id == Investigation.customer_id)
    if status:
        q = q.where(Investigation.status == status)
    if customer_id:
        q = q.where(Investigation.customer_id == customer_id)
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.execute(q.order_by(desc(Investigation.id)).offset((page - 1) * size).limit(size)).all()
    return {"items": [_case_out(i, n) for i, n in rows], "total": total, "page": page, "size": size}


@router.get("/investigations/{inv_id}", summary="Case with latest report, evidence, agent timeline and approvals")
def get_case(inv_id: int, session: SessionDep, actor: Viewer):
    inv = session.get(Investigation, inv_id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    run_id = (inv.state or {}).get("run_id") or session.scalar(
        select(AgentExecutionLog.run_id).where(AgentExecutionLog.investigation_id == inv_id).order_by(desc(AgentExecutionLog.id)))
    steps = session.scalars(select(AgentExecutionLog).where(AgentExecutionLog.investigation_id == inv_id,
                                                            AgentExecutionLog.run_id == run_id)
                            .order_by(AgentExecutionLog.step)).all() if run_id else []
    if inv.status == "RUNNING":       # live view: newest run, even before the case row is updated
        latest = session.scalar(select(AgentExecutionLog.run_id).where(AgentExecutionLog.investigation_id == inv_id)
                                .order_by(desc(AgentExecutionLog.id)))
        if latest and latest != run_id:
            run_id = latest
            steps = session.scalars(select(AgentExecutionLog).where(AgentExecutionLog.run_id == latest)
                                    .order_by(AgentExecutionLog.step)).all()
    evidence = session.scalars(select(InvestigationEvidence).where(InvestigationEvidence.investigation_id == inv_id,
                                                                   InvestigationEvidence.run_id == run_id)
                               .order_by(InvestigationEvidence.id)).all() if run_id else []
    report = session.scalar(select(InvestigationReport).where(InvestigationReport.investigation_id == inv_id)
                            .order_by(desc(InvestigationReport.version)))
    approvals = session.scalars(select(Approval).where(Approval.investigation_id == inv_id).order_by(Approval.id)).all()
    name = session.scalar(select(Customer.full_name).where(Customer.customer_id == inv.customer_id))
    return {
        **_case_out(inv, name), "run_id": run_id,
        "steps": [{"step": s.step, "agent": s.agent, "status": s.status, "attempts": s.attempts, "duration_ms": s.duration_ms,
                   "tool_calls": s.tool_calls, "evidence_refs": s.evidence_refs, "llm_model": s.llm_model, "error": s.error,
                   "output_summary": s.output_summary, "started_at": s.started_at} for s in steps],
        "evidence": [{"ref": e.evidence_ref, "type": e.evidence_type, "agent": e.source_agent, "title": e.title,
                      "source_table": e.source_table, "source_id": e.source_id, "ai_generated": e.ai_generated,
                      "observed_at": e.observed_at, "details": e.details} for e in evidence],
        "report": None if not report else {"id": report.id, "version": report.version, "run_id": report.run_id,
                                           "narrative_source": report.narrative_source, "content": report.content,
                                           "markdown": report.content_markdown, "created_at": report.created_at},
        "approvals": [{"id": a.id, "requested_by": a.requested_by, "request_comment": a.request_comment,
                       "requested_at": a.requested_at, "decision": a.decision, "decided_by": a.decided_by,
                       "decision_comment": a.decision_comment, "decided_at": a.decided_at,
                       "overrides_ai": a.overrides_ai} for a in approvals],
    }


@router.post("/investigations/{inv_id}/submit", summary="Submit the report for human approval (analyst)")
def submit(inv_id: int, body: SubmitBody, session: SessionDep,
           actor: Annotated[Actor, Depends(require("submit_for_approval"))]):
    try:
        ap = cases.submit_for_approval(session, actor, inv_id, body.comment)
    except cases.CaseError as e:
        raise HTTPException(409, str(e)) from e
    return {"approval_id": ap.id, "status": "PENDING_APPROVAL"}


@router.post("/investigations/{inv_id}/decision", summary="Approve / escalate / reject / request more info (manager)")
def decision(inv_id: int, body: DecisionBody, session: SessionDep,
             actor: Annotated[Actor, Depends(require("decide_investigation"))]):
    try:
        ap = cases.decide(session, actor, inv_id, body.decision, body.comment)
    except cases.CaseError as e:
        raise HTTPException(409, str(e)) from e
    inv = session.get(Investigation, inv_id)
    return {"approval_id": ap.id, "decision": ap.decision, "status": inv.status, "overrides_ai": ap.overrides_ai}


@router.get("/approvals", summary="Approval queue")
def approvals(session: SessionDep, actor: Viewer, decision: str | None = "PENDING"):
    q = select(Approval, Investigation).join(Investigation, Investigation.id == Approval.investigation_id)
    if decision:
        q = q.where(Approval.decision == decision)
    rows = session.execute(q.order_by(desc(Approval.id)).limit(200)).all()
    return [{"approval_id": a.id, "investigation_id": i.id, "case_ref": i.case_ref, "customer_id": i.customer_id,
             "recommendation": i.recommendation, "assessment_score": i.assessment_score, "requested_by": a.requested_by,
             "requested_at": a.requested_at, "decision": a.decision, "decided_by": a.decided_by,
             "decided_at": a.decided_at, "overrides_ai": a.overrides_ai} for a, i in rows]
