"""Run one investigation end to end and persist the outcome.

The workflow stops at the human-in-the-loop checkpoint: the report is written and the
case becomes REPORT_READY. Nothing after that is automated - an analyst submits it and an
Investigation Manager decides (app/services/cases.py).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.graph import build_graph
from agents.state import RunContext, register, release
from app.db import get_engine
from app.models import AuditLog, Investigation, InvestigationEvidence
from app.observability import INVESTIGATIONS, flush, start_trace
from app.security import Actor

log = logging.getLogger(__name__)


def _jsonable(o):
    return json.loads(json.dumps(o, default=lambda v: v.isoformat() if isinstance(v, (date, datetime)) else str(v)))


def run_investigation(investigation_id: int, actor: Actor) -> dict:
    if not actor.can("run_investigation"):
        raise PermissionError(f"Role {actor.role} cannot run investigations")
    run_id = uuid.uuid4().hex[:12]
    with Session(get_engine()) as s:
        inv = s.get(Investigation, investigation_id)
        if inv is None:
            raise ValueError(f"Investigation {investigation_id} not found")
        if inv.status in ("RUNNING", "PENDING_APPROVAL", "APPROVED_CLOSED", "ESCALATED", "REJECTED"):
            raise ValueError(f"Investigation is {inv.status}; it cannot be re-run now")
        inv.status, inv.run_count, inv.error = "RUNNING", (inv.run_count or 0) + 1, None
        customer_id, request_text, case_ref = inv.customer_id, inv.request_text, inv.case_ref
        # evidence refs continue across re-runs so E-numbers stay unique within a case
        first_ref = (s.scalar(select(func.count()).select_from(InvestigationEvidence)
                              .where(InvestigationEvidence.investigation_id == investigation_id)) or 0) + 1
        s.add(AuditLog(actor=actor.username, action="INVESTIGATION_RUN_STARTED", entity_type="investigation",
                       entity_id=case_ref, details={"run_id": run_id}))
        s.commit()

    trace = start_trace(name="investigation", user_id=actor.username, session_id=case_ref,
                        input={"customer_id": customer_id, "request": request_text}, metadata={"run_id": run_id})
    ctx = RunContext(run_id=run_id, investigation_id=investigation_id, actor=actor, trace=trace, next_ref=first_ref)
    register(ctx)
    final: dict = {}
    try:
        final = build_graph().invoke({"investigation_id": investigation_id, "run_id": run_id, "customer_id": customer_id,
                                      "request_text": request_text, "findings": {}, "evidence": [], "errors": [],
                                      "completed": []})
        error = None
    except Exception as e:                       # a bug in the workflow itself - record it, never crash the API
        log.exception("Investigation %s failed", investigation_id)
        error = f"{type(e).__name__}: {e}"
    finally:
        release(run_id)

    findings = final.get("findings", {})
    inv_f, rep_f = findings.get("investigation", {}), findings.get("reporting", {})
    status = "REPORT_READY" if (error is None and rep_f.get("report_id")) else "FAILED"
    if status == "FAILED" and error is None:
        error = "; ".join(f"{e['agent']}: {e['error']}" for e in final.get("errors", [])) or "workflow halted"
    with Session(get_engine()) as s:
        inv = s.get(Investigation, investigation_id)
        inv.status, inv.error = status, error
        inv.assessment_score = inv_f.get("assessment_score")
        inv.recommendation = inv_f.get("recommendation")
        inv.state = _jsonable({"run_id": run_id, "completed": final.get("completed", []), "errors": final.get("errors", []),
                               "findings": findings})
        s.add(AuditLog(actor=actor.username, action="INVESTIGATION_RUN_FINISHED", entity_type="investigation",
                       entity_id=inv.case_ref, details={"run_id": run_id, "status": status, "error": error,
                                                        "recommendation": inv.recommendation,
                                                        "evidence": len(final.get("evidence", []))}))
        s.commit()
    INVESTIGATIONS.labels(status).inc()
    trace.update(output={"status": status, "recommendation": inv_f.get("recommendation"),
                         "score": inv_f.get("assessment_score")})
    flush()
    return {"investigation_id": investigation_id, "run_id": run_id, "status": status, "error": error,
            "assessment_score": inv_f.get("assessment_score"), "recommendation": inv_f.get("recommendation"),
            "report_id": rep_f.get("report_id"), "evidence_count": len(final.get("evidence", [])),
            "completed": final.get("completed", []), "errors": final.get("errors", [])}
