"""Governance & AI oversight: agent execution history, override tracking, evaluation results."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import AgentExecutionLog, Approval, AuditLog, Investigation, ModelVersion
from app.observability import langfuse_enabled
from app.security import Actor, require

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])
SessionDep = Annotated[Session, Depends(get_session)]
Auditor = Annotated[Actor, Depends(require("view_audit"))]


def _latest_json(sub: str, pattern: str) -> dict | None:
    d = get_settings().models_dir / sub
    files = sorted(d.glob(pattern)) if d.exists() else []
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text())
    except (OSError, ValueError):
        return None


@router.get("/agent-runs", summary="Agent execution statistics and recent steps")
def agent_runs(session: SessionDep, actor: Auditor, limit: int = 50):
    per_agent = session.execute(
        select(AgentExecutionLog.agent, func.count(), func.sum(case((AgentExecutionLog.status == "SUCCEEDED", 1), else_=0)),
               func.avg(AgentExecutionLog.duration_ms), func.max(AgentExecutionLog.duration_ms),
               func.sum(AgentExecutionLog.attempts))
        .group_by(AgentExecutionLog.agent)).all()
    recent = session.scalars(select(AgentExecutionLog).order_by(desc(AgentExecutionLog.id)).limit(min(limit, 200))).all()
    return {
        "per_agent": [{"agent": a, "steps": n, "success_rate": round((ok or 0) / n, 3) if n else None,
                       "avg_ms": round(float(avg or 0)), "max_ms": mx, "retries": int((att or 0) - n)}
                      for a, n, ok, avg, mx, att in per_agent],
        "recent": [{"investigation_id": r.investigation_id, "run_id": r.run_id, "step": r.step, "agent": r.agent,
                    "status": r.status, "attempts": r.attempts, "duration_ms": r.duration_ms, "llm_model": r.llm_model,
                    "tools": [t.get("tool") for t in (r.tool_calls or [])], "error": r.error, "started_at": r.started_at}
                   for r in recent],
    }


@router.get("/ai-metrics", summary="AI oversight dashboard: outcomes, human overrides, model and RAG evaluation")
def ai_metrics(session: SessionDep, actor: Auditor):
    status = dict(session.execute(select(Investigation.status, func.count()).group_by(Investigation.status)).all())
    recs = dict(session.execute(select(Investigation.recommendation, func.count())
                                .where(Investigation.recommendation.is_not(None)).group_by(Investigation.recommendation)).all())
    decided = session.execute(select(Approval.decision, func.count(), func.sum(case((Approval.overrides_ai.is_(True), 1), else_=0)))
                              .where(Approval.decision != "PENDING").group_by(Approval.decision)).all()
    n_dec = sum(n for _, n, _ in decided)
    n_override = sum(int(o or 0) for _, _, o in decided)
    llm_steps = session.scalar(select(func.count()).select_from(AgentExecutionLog)
                               .where(AgentExecutionLog.agent == "investigation", AgentExecutionLog.llm_model.is_not(None))) or 0
    inv_steps = session.scalar(select(func.count()).select_from(AgentExecutionLog)
                               .where(AgentExecutionLog.agent == "investigation")) or 0
    tool_calls = dict(session.execute(select(AuditLog.entity_id, func.count()).where(AuditLog.action == "TOOL_CALL")
                                      .group_by(AuditLog.entity_id)).all())
    models = session.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))).all()
    rag = _latest_json("rag", "rag_evaluation_latest.json")
    graph = _latest_json("graph", "graph_evaluation_*.json")
    agents = _latest_json("agents", "agent_evaluation_latest.json")
    return {
        "investigations_by_status": status,
        "ai_recommendations": recs,
        "human_decisions": {d: n for d, n, _ in decided},
        "override_rate": round(n_override / n_dec, 3) if n_dec else None,
        "decisions_total": n_dec,
        "narratives_by_llm_share": round(llm_steps / inv_steps, 3) if inv_steps else None,
        "tool_calls": tool_calls,
        "active_models": [{"name": m.model_name, "version": m.version,
                           "pr_auc": m.metrics.get("pr_auc", m.metrics.get("pr_auc_vs_sar_labels"))} for m in models],
        "rag_evaluation": None if not rag else {"retrieval": rag.get("retrieval"),
                                                "answers": {k: v for k, v in (rag.get("answers") or {}).items()
                                                            if k != "per_question"}},
        "graph_evaluation": None if not graph else graph.get("evaluation"),
        "agent_evaluation": None if not agents else {k: v for k, v in agents.items() if k != "cases"},
        "langfuse_enabled": langfuse_enabled(),
    }
