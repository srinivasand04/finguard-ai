"""Investigation case management and the human approval workflow.

Status lifecycle:
    CREATED -> RUNNING -> REPORT_READY -> PENDING_APPROVAL -> APPROVED_CLOSED | ESCALATED | REJECTED
                    \\-> FAILED                     \\-> MORE_INFO_REQUESTED -> (re-run) -> REPORT_READY ...

Rules enforced here (not only in the UI):
* only analysts create, run and submit cases; only an Investigation Manager decides;
* four-eyes: the decider can be neither the case creator nor the person who submitted it;
* a decision is only possible on a case that is PENDING_APPROVAL;
* every transition is audit-logged, and a human decision that differs from the AI
  recommendation is recorded as an override.
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Approval, AuditLog, Customer, Investigation, InvestigationReport
from app.security import Actor

CUSTOMER_RE = re.compile(r"\bCUST\d{4,8}\b", re.IGNORECASE)
ACCOUNT_RE = re.compile(r"\bACC\d{4,8}\b", re.IGNORECASE)

DECISIONS = {"APPROVE": "APPROVED_CLOSED", "ESCALATE": "ESCALATED", "REJECT": "REJECTED",
             "REQUEST_MORE_INFO": "MORE_INFO_REQUESTED"}
# what the AI recommendation would map to, for override tracking
AI_TO_DECISION = {"ESCALATE_TO_MLRO": "ESCALATE", "FURTHER_INVESTIGATION": "REQUEST_MORE_INFO",
                  "CLOSE_NO_FURTHER_ACTION": "APPROVE"}


class CaseError(ValueError):
    """Business-rule violation (maps to HTTP 409/422)."""


def resolve_subject(session: Session, request_text: str, customer_id: str | None = None) -> str:
    """Find the customer an investigation request is about (explicit id, CUST id or ACC id in the text)."""
    if customer_id:
        cid = customer_id.strip().upper()
    elif m := CUSTOMER_RE.search(request_text or ""):
        cid = m.group(0).upper()
    elif m := ACCOUNT_RE.search(request_text or ""):
        acc = session.get(Account, m.group(0).upper())
        if not acc:
            raise CaseError(f"Account {m.group(0).upper()} not found")
        cid = acc.customer_id
    else:
        raise CaseError("Request must name a customer (e.g. CUST10025) or an account (e.g. ACC100446)")
    if not session.get(Customer, cid):
        raise CaseError(f"Customer {cid} not found")
    return cid


def create_case(session: Session, actor: Actor, request_text: str, customer_id: str | None = None,
                title: str | None = None) -> Investigation:
    if not actor.can("run_investigation"):
        raise PermissionError(f"Role {actor.role} cannot create investigations")
    cid = resolve_subject(session, request_text, customer_id)
    n = (session.scalar(select(func.count()).select_from(Investigation)) or 0) + 1
    inv = Investigation(case_ref=f"FG-{datetime.now():%Y%m%d}-{n:04d}", customer_id=cid,
                        title=title or f"Investigation of {cid}", request_text=request_text.strip()[:2000],
                        status="CREATED", created_by=actor.username, state={})
    session.add(inv)
    session.flush()
    session.add(AuditLog(actor=actor.username, action="INVESTIGATION_CREATED", entity_type="investigation",
                         entity_id=inv.case_ref, details={"customer_id": cid, "request": inv.request_text}))
    session.commit()
    return inv


def submit_for_approval(session: Session, actor: Actor, investigation_id: int, comment: str | None = None) -> Approval:
    if not actor.can("submit_for_approval"):
        raise PermissionError(f"Role {actor.role} cannot submit cases for approval")
    inv = session.get(Investigation, investigation_id)
    if not inv:
        raise CaseError(f"Investigation {investigation_id} not found")
    if inv.status not in ("REPORT_READY", "MORE_INFO_REQUESTED"):
        raise CaseError(f"Case is {inv.status}; only a case with a ready report can be submitted")
    report_id = session.scalar(select(InvestigationReport.id).where(InvestigationReport.investigation_id == inv.id)
                               .order_by(InvestigationReport.version.desc()).limit(1))
    if report_id is None:
        raise CaseError("No report to submit - run the investigation first")
    ap = Approval(investigation_id=inv.id, report_id=report_id, requested_by=actor.username,
                  request_comment=(comment or "")[:2000], decision="PENDING")
    session.add(ap)
    inv.status = "PENDING_APPROVAL"
    session.add(AuditLog(actor=actor.username, action="SUBMITTED_FOR_APPROVAL", entity_type="investigation",
                         entity_id=inv.case_ref, details={"report_id": report_id, "comment": comment}))
    session.commit()
    return ap


def decide(session: Session, actor: Actor, investigation_id: int, decision: str, comment: str) -> Approval:
    if not actor.can("decide_investigation"):
        raise PermissionError(f"Role {actor.role} cannot decide on investigations")
    if decision not in DECISIONS:
        raise CaseError(f"Decision must be one of {sorted(DECISIONS)}")
    if not comment or len(comment.strip()) < 5:
        raise CaseError("A decision needs a written rationale (at least 5 characters)")
    inv = session.get(Investigation, investigation_id)
    if not inv:
        raise CaseError(f"Investigation {investigation_id} not found")
    ap = session.scalar(select(Approval).where(Approval.investigation_id == inv.id, Approval.decision == "PENDING")
                        .order_by(Approval.id.desc()))
    if inv.status != "PENDING_APPROVAL" or ap is None:
        raise CaseError(f"Case is {inv.status}; there is no pending approval")
    if actor.username in (inv.created_by, ap.requested_by):
        raise CaseError("Four-eyes rule: you cannot decide on a case you created or submitted")
    ap.decision = decision
    ap.decided_by = actor.username
    ap.decision_comment = comment.strip()[:2000]
    ap.decided_at = datetime.now()
    ap.overrides_ai = AI_TO_DECISION.get(inv.recommendation or "") not in (None, decision)
    inv.status = DECISIONS[decision]
    session.add(AuditLog(actor=actor.username, action=f"INVESTIGATION_{decision}", entity_type="investigation",
                         entity_id=inv.case_ref,
                         details={"comment": ap.decision_comment, "ai_recommendation": inv.recommendation,
                                  "human_override": ap.overrides_ai}))
    session.commit()
    return ap
