"""Agent workflow evaluation.

Runs complete investigations for a balanced sample of customers - some that took part in
simulated laundering, some that did not - and measures the *workflow*, not just a model:

* completion rate and per-agent success rate
* evidence produced per case, and whether every key finding cites evidence
* recommendation quality vs simulator ground truth (never shown to the agents):
  "needs attention" = ESCALATE_TO_MLRO or FURTHER_INVESTIGATION
* narrative source (LLM vs template) and latency

Cases are created with the title prefix [EVAL] and the actor system:agent-eval.
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.runner import run_investigation
from app.config import get_settings
from app.db import get_engine
from app.models import Account, AgentExecutionLog, AuditLog, Investigation
from app.security import Actor
from app.services import cases

EVAL_ACTOR = Actor("system:agent-eval", "FRAUD_ANALYST")
REF_RE = re.compile(r"\[E\d+\]")


def run_agent_evaluation(n: int = 12, seed: int = 7, use_llm: bool | None = None) -> dict:
    s = get_settings()
    if use_llm is not None:
        s.agent_use_llm = use_llm
    with Session(get_engine()) as session:
        rows = session.execute(select(Account.customer_id, Account.sim_is_sar)).all()
    labels: dict[str, bool] = {}
    for cid, sar in rows:
        labels[cid] = labels.get(cid, False) or bool(sar)
    rng = random.Random(seed)
    pos = sorted(c for c, v in labels.items() if v)
    neg = sorted(c for c, v in labels.items() if not v)
    sample = rng.sample(pos, min(n // 2, len(pos))) + rng.sample(neg, min(n - n // 2, len(neg)))

    results = []
    for cid in sample:
        t0 = time.time()
        with Session(get_engine()) as session:
            inv = cases.create_case(session, EVAL_ACTOR, f"[EVAL] Investigate customer {cid}", cid, f"[EVAL] {cid}")
            inv_id = inv.id
        out = run_investigation(inv_id, EVAL_ACTOR)
        with Session(get_engine()) as session:
            inv = session.get(Investigation, inv_id)
            steps = session.scalars(select(AgentExecutionLog).where(AgentExecutionLog.run_id == out["run_id"])).all()
            kf = ((inv.state or {}).get("findings", {}).get("investigation", {}) or {}).get("key_findings", [])
            src = ((inv.state or {}).get("findings", {}).get("investigation", {}) or {}).get("narrative_source")
        results.append({
            "customer_id": cid, "sim_label_sar": labels[cid], "status": out["status"],
            "recommendation": out["recommendation"], "assessment_score": out["assessment_score"],
            "evidence_count": out["evidence_count"], "steps": len(steps),
            "failed_steps": [x.agent for x in steps if x.status != "SUCCEEDED"],
            "findings_all_cited": all(REF_RE.search(k) for k in kf) if kf else True,
            "narrative_source": src, "seconds": round(time.time() - t0, 1),
        })

    done = [r for r in results if r["status"] == "REPORT_READY"]
    attn = lambda r: r["recommendation"] in ("ESCALATE_TO_MLRO", "FURTHER_INVESTIGATION")  # noqa: E731
    tp = sum(attn(r) and r["sim_label_sar"] for r in done)
    fp = sum(attn(r) and not r["sim_label_sar"] for r in done)
    fn = sum((not attn(r)) and r["sim_label_sar"] for r in done)
    tn = sum((not attn(r)) and not r["sim_label_sar"] for r in done)
    all_steps = [len(r["failed_steps"]) for r in results]
    summary = {
        "evaluated_at": datetime.now().isoformat(timespec="seconds"), "case_count": len(results),
        "llm_narratives": s.agent_use_llm,
        "completion_rate": round(len(done) / len(results), 3) if results else None,
        "cases_with_failed_steps": sum(1 for x in all_steps if x),
        "avg_evidence_per_case": round(mean(r["evidence_count"] for r in results), 1) if results else None,
        "findings_fully_cited_rate": round(mean(r["findings_all_cited"] for r in done), 3) if done else None,
        "needs_attention_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "needs_attention_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "recommendations": {k: sum(r["recommendation"] == k for r in done)
                            for k in ("ESCALATE_TO_MLRO", "FURTHER_INVESTIGATION", "CLOSE_NO_FURTHER_ACTION")},
        "narrative_sources": {k: sum(r["narrative_source"] == k for r in done) for k in {r["narrative_source"] for r in done}},
        "median_seconds_per_case": median(r["seconds"] for r in results) if results else None,
        "note": "Ground-truth labels come from the simulator and are used only for this evaluation.",
        "cases": results,
    }
    out_dir = s.models_dir / "agents"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "agent_evaluation_latest.json").write_text(json.dumps(summary, indent=2, default=str))
    with Session(get_engine()) as session:
        session.add(AuditLog(actor=EVAL_ACTOR.username, action="AGENT_EVALUATED", entity_type="agents", entity_id=None,
                             details={k: v for k, v in summary.items() if k != "cases"}))
        session.commit()
    return summary
