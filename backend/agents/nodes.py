"""The eight agents. Each is a plain function `(state, ctx) -> findings`; `agent_node`
wraps it with retries, timing, evidence persistence, an execution-log row, a Langfuse span
and Prometheus metrics, and turns failures into recorded errors instead of crashes."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session

from agents.state import InvestigationState, RunContext, context
from app.config import get_settings
from app.db import get_engine
from app.models import AgentExecutionLog, InvestigationEvidence
from app.observability import AGENT_LATENCY, AGENT_STEPS
from tools.registry import ToolDenied, ToolError


def agent_node(name: str, fn: Callable[[InvestigationState, RunContext], dict]):
    def node(state: InvestigationState) -> dict:
        ctx = context(state["run_id"])
        ctx.step += 1
        ctx.tool_log, ctx.new_evidence, ctx.llm_model = [], [], None
        start_ref = ctx.next_ref
        span = ctx.trace.span(name=name, input={"customer_id": state.get("customer_id")})
        started, t0 = datetime.now(), time.time()
        attempts, findings, error = 0, None, None
        retries = get_settings().agent_max_retries
        while attempts <= retries:
            attempts += 1
            ctx.new_evidence, ctx.next_ref = [], start_ref   # a retry starts clean
            try:
                findings = fn(state, ctx)
                error = None
                break
            except ToolDenied as e:                           # permissions don't fix themselves - no retry
                error = f"Denied: {e}"
                break
            except Exception as e:                            # transient (DB, LLM, index) - retry with backoff
                error = f"{type(e).__name__}: {e}"
                time.sleep(0.2 * attempts)
        status = "SUCCEEDED" if error is None else "FAILED"
        ms = int((time.time() - t0) * 1000)
        evidence = ctx.new_evidence if error is None else []
        _persist(ctx, name, status, attempts, findings, evidence, error, started, ms)
        AGENT_STEPS.labels(name, status).inc()
        AGENT_LATENCY.labels(name).observe(ms / 1000)
        span.end(output={"status": status, "evidence": [e["ref"] for e in evidence], "error": error})
        update: dict = {"completed": [name], "evidence": [_light(e) for e in evidence],
                        "findings": {name: findings or {"error": error}}}
        if error:
            update["errors"] = [{"agent": name, "error": error}]
        if name == "supervisor" and (error or (findings or {}).get("halt")):
            update["halt"] = True
        return update
    node.__name__ = name
    return node


def _light(e: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in e.items()}


def _persist(ctx: RunContext, agent: str, status: str, attempts: int, findings: dict | None, evidence: list,
             error: str | None, started: datetime, ms: int) -> None:
    with Session(get_engine()) as s:
        for e in evidence:
            s.add(InvestigationEvidence(investigation_id=ctx.investigation_id, run_id=ctx.run_id, evidence_ref=e["ref"],
                                        evidence_type=e["evidence_type"], source_agent=e["source_agent"],
                                        source_table=e["source_table"], source_id=e["source_id"], title=e["title"],
                                        details=_light(e["details"]), ai_generated=e["ai_generated"],
                                        observed_at=e["observed_at"]))
        summary = {k: v for k, v in (findings or {}).items() if not isinstance(v, (list, dict)) or len(str(v)) < 600}
        s.add(AgentExecutionLog(investigation_id=ctx.investigation_id, run_id=ctx.run_id, step=ctx.step, agent=agent,
                                status=status, attempts=attempts, tool_calls=ctx.tool_log, output_summary=_light(summary),
                                evidence_refs=[e["ref"] for e in evidence], llm_model=ctx.llm_model, error=error,
                                started_at=started, duration_ms=ms))
        s.commit()


def _ts(v):
    return str(v)[:16].replace("T", " ") if v else "-"


# =========================================================================== 1. Supervisor
def supervisor(state: InvestigationState, ctx: RunContext) -> dict:
    """Understands the request, checks scope/safety, loads case memory and plans the route."""
    from rag.answer import sanitize_question

    text, warnings = sanitize_question(state["request_text"])
    history = ctx.tool("get_investigation_history", customer_id=state["customer_id"])
    previous = [h for h in history["investigations"] if h["investigation_id"] != state["investigation_id"]]
    if previous:
        ctx.evidence("INVESTIGATION_HISTORY", "supervisor", f"{len(previous)} previous investigation(s) of this customer",
                     {"previous": previous[:5]}, "investigations", previous[0]["investigation_id"])
    return {"subject": state["customer_id"], "request": text, "warnings": warnings,
            "previous_investigations": previous[:5],
            "plan": ["transaction", "fraud_detection", "customer_risk", "graph_intelligence (if graph built)",
                     "compliance", "investigation", "reporting"],
            "halt": False}


# =========================================================================== 2. Transaction agent
def transaction_agent(state: InvestigationState, ctx: RunContext) -> dict:
    h = ctx.tool("get_transaction_history", customer_id=state["customer_id"], limit=10)
    ref = ctx.evidence("TRANSACTION_SUMMARY", "transaction",
                       f"{h['transaction_count']} transactions, total {h['total_value']:,.2f} "
                       f"({_ts(h['first_seen'])[:10]} to {_ts(h['last_seen'])[:10]})",
                       {k: h[k] for k in ("transaction_count", "total_value", "outgoing_count", "outgoing_value",
                                          "cross_border_count", "near_threshold_outgoing", "categories")},
                       "transactions", state["customer_id"])
    tx_refs = []
    for t in [t for t in h["riskiest_transactions"] if t["risk_band"] in ("HIGH", "MEDIUM")][:5]:
        tx_refs.append(ctx.evidence(
            "TRANSACTION", "transaction",
            f"Tx {t['transaction_id']}: {t['direction']} {t['amount']:,.2f} {t['tx_type']} "
            f"{'cross-border ' if t['is_cross_border'] else ''}with {t['counterparty']} on {_ts(t['timestamp'])} "
            f"(risk {t['risk_score']:.0f}, {t['risk_band']})",
            t, "transactions", t["transaction_id"], t["timestamp"]))
    n = max(h["transaction_count"], 1)
    return {"transaction_count": h["transaction_count"], "total_value": h["total_value"],
            "cross_border_share": round(h["cross_border_count"] / n, 3), "near_threshold_outgoing": h["near_threshold_outgoing"],
            "summary_ref": ref, "flagged_transaction_refs": tx_refs}


# =========================================================================== 3. Fraud detection agent
def fraud_agent(state: InvestigationState, ctx: RunContext) -> dict:
    p = ctx.tool("get_fraud_prediction", customer_id=state["customer_id"], min_band="MEDIUM", limit=8)
    refs = []
    for x in p["predictions"][:5]:
        refs.append(ctx.evidence(
            "ML_PREDICTION", "fraud_detection",
            f"Tx {x['transaction_id']}: ML suspicion probability {x['fraud_probability']:.2f}, anomaly percentile "
            f"{(x['anomaly_percentile'] or 0) * 100:.1f}% - {'; '.join(x['top_factors'][:2])}",
            {**x, "model": p["model"]}, "fraud_predictions", x["transaction_id"], x["timestamp"]))
    probs = [x["fraud_probability"] for x in p["predictions"]]
    return {"band_counts": p["band_counts"], "high_risk_count": p["band_counts"].get("HIGH", 0),
            "max_probability": max(probs) if probs else 0.0, "model": p["model"], "prediction_refs": refs}


# =========================================================================== 4. Customer risk agent
def customer_risk_agent(state: InvestigationState, ctx: RunContext) -> dict:
    prof = ctx.tool("get_customer_profile", customer_id=state["customer_id"])
    c, r = prof["customer"], prof["risk"] or {}
    kyc = ctx.evidence("KYC_PROFILE", "customer_risk",
                       f"{c['segment']} customer in {c['country']}, KYC {c['kyc_level']}, onboarded {c['onboarding_date']}"
                       f"{', politically exposed person' if c['pep_flag'] else ''}",
                       {**c, "accounts": prof["accounts"], "alerts_by_type": prof["alerts_by_type"]},
                       "customers", c["customer_id"])
    ind_refs = []
    for ind in r.get("indicators", []):
        val = ind["value"]
        ind_refs.append(ctx.evidence(
            "RISK_INDICATOR", "customer_risk",
            f"{ind['label']} (observed {round(val, 3) if isinstance(val, float) else val}, threshold {ind['threshold']}, +{ind['weight']})",
            ind, "customer_risk", c["customer_id"]))
    profile = r.get("profile", {})
    return {"risk_score": r.get("score"), "risk_level": r.get("level"), "pep": c["pep_flag"],
            "indicator_codes": [i["code"] for i in r.get("indicators", [])], "kyc_ref": kyc, "indicator_refs": ind_refs,
            "alerts_by_type": prof["alerts_by_type"], "high_risk_geography_share": profile.get("high_risk_country_share"),
            "graph_available": "graph_cycle_count" in profile}


# =========================================================================== 5. Graph intelligence agent
def graph_agent(state: InvestigationState, ctx: RunContext) -> dict:
    g = ctx.tool("get_account_relationships", customer_id=state["customer_id"])
    p_refs, n_refs = [], []
    for p in g["patterns"][:5]:
        kind = "Circular flow" if p["type"] == "CYCLE" else "Layering chain"
        p_refs.append(ctx.evidence(
            "GRAPH_PATTERN", "graph_intelligence",
            f"{kind} #{p['id']}: {' -> '.join(p['route'])}, {p['hops']} hops in {p['duration_hours']:.0f}h, "
            f"{p['start_amount']:,.0f} -> {p['end_amount']:,.0f} (score {p['score']})",
            p, "graph_patterns", p["id"], p["start_ts"]))
    for n in g["networks"]:
        n_refs.append(ctx.evidence(
            "NETWORK", "graph_intelligence",
            f"Member of suspicious network #{n['id']} ({n['size']} accounts, {n['risk_level']}): "
            f"{', '.join(n['typology_hints']) or 'no typology hints'}",
            n, "suspicious_networks", n["id"]))
    acc = g["accounts"]
    return {"cycle_count": sum(p["type"] == "CYCLE" for p in g["patterns"]),
            "chain_count": sum(p["type"] == "LAYERING_CHAIN" for p in g["patterns"]),
            "network_levels": [n["risk_level"] for n in g["networks"]],
            "max_pagerank_percentile": max((a["pagerank_percentile"] for a in acc), default=None),
            "max_neighbour_high_risk_share": max((a["neighbour_high_risk_share"] for a in acc), default=None),
            "top_counterparties": g["top_counterparties"][:5], "pattern_refs": p_refs, "network_refs": n_refs}


# =========================================================================== 6. Compliance agent
def compliance_agent(state: InvestigationState, ctx: RunContext) -> dict:
    """Turns what the other agents found into policy questions and retrieves cited passages."""
    f = state.get("findings", {})
    tx, risk, graph = f.get("transaction", {}), f.get("customer_risk", {}), f.get("graph_intelligence", {})
    queries = ["When must suspicious activity be reported to the MLRO and a SAR filed?",
               "What evidence must every finding in an investigation reference?"]
    if (tx.get("near_threshold_outgoing") or 0) >= 3 or "NEAR_THRESHOLD" in risk.get("indicator_codes", []):
        queries.append("structuring indicators transactions just below 10,000 threshold")
    if graph.get("cycle_count") or graph.get("chain_count") or "PASS_THROUGH" in risk.get("indicator_codes", []):
        queries.append("layering round-tripping pass-through indicators funds leave soon after arriving")
    if graph.get("network_levels"):
        queries.append("fan-in fan-out network of connected accounts typologies")
    if risk.get("pep"):
        queries.append("politically exposed person enhanced due diligence senior management approval")
    if (risk.get("high_risk_geography_share") or 0) >= 0.2 or "HIGH_RISK_GEOGRAPHY" in risk.get("indicator_codes", []):
        queries.append("high-risk jurisdictions wire transfers enhanced due diligence review")
    seen, refs, used = set(), [], []
    for q in queries:
        res = ctx.tool("search_compliance_policy", query=q, k=2)
        for h in res["results"][:1]:                     # best passage per question
            if h["chunk_id"] in seen:
                continue
            seen.add(h["chunk_id"])
            loc = f"{h['title']} - {h['section'] or 'n/a'}" + (f", p.{h['page']}" if h["page"] else "")
            refs.append(ctx.evidence("POLICY_REFERENCE", "compliance", loc,
                                     {**h, "query": q}, "compliance_chunks", h["chunk_id"]))
            used.append({"query": q, "ref": refs[-1], "source": loc})
    return {"queries": queries, "policy_refs": refs, "references": used}


# =========================================================================== 7. Investigation agent
RECOMMENDATIONS = [(60, "ESCALATE_TO_MLRO"), (30, "FURTHER_INVESTIGATION"), (0, "CLOSE_NO_FURTHER_ACTION")]


def assess(findings: dict) -> tuple[float, str, list[dict]]:
    """Transparent, rule-based correlation of the agents' findings. Every signal cites evidence."""
    tx, fr = findings.get("transaction", {}), findings.get("fraud_detection", {})
    rk, gr = findings.get("customer_risk", {}), findings.get("graph_intelligence", {})
    sup = findings.get("supervisor", {})
    signals: list[dict] = []

    def add(points: float, text: str, refs: list[str]):
        signals.append({"points": points, "signal": text, "evidence": [r for r in refs if r]})

    if rk.get("risk_level") == "HIGH":
        add(25, f"Customer risk level HIGH (score {rk.get('risk_score')})", rk.get("indicator_refs", [])[:4])
    elif rk.get("risk_level") == "MEDIUM":
        add(10, f"Customer risk level MEDIUM (score {rk.get('risk_score')})", rk.get("indicator_refs", [])[:3])
    hi = fr.get("high_risk_count", 0)
    if hi >= 3:
        add(20, f"{hi} transactions in the HIGH ML risk band", fr.get("prediction_refs", [])[:3])
    elif hi >= 1:
        add(10, f"{hi} transaction(s) in the HIGH ML risk band", fr.get("prediction_refs", [])[:2])
    if fr.get("max_probability", 0) >= 0.9:
        add(10, f"Peak ML suspicion probability {fr['max_probability']:.2f}", fr.get("prediction_refs", [])[:1])
    if gr.get("cycle_count"):
        add(15, f"Takes part in {gr['cycle_count']} time-ordered circular flow(s)", gr.get("pattern_refs", []))
    if gr.get("chain_count"):
        add(10, f"Hop in {gr['chain_count']} layering chain(s)", gr.get("pattern_refs", []))
    levels = gr.get("network_levels", [])
    if "HIGH" in levels:
        add(15, "Member of a HIGH-risk suspicious network", gr.get("network_refs", []))
    elif "MEDIUM" in levels:
        add(5, "Member of a MEDIUM-risk suspicious network", gr.get("network_refs", []))
    if (tx.get("near_threshold_outgoing") or 0) >= 3:
        add(10, f"{tx['near_threshold_outgoing']} outgoing amounts just below 10,000 (structuring indicator)",
            [tx.get("summary_ref")])
    if any((p.get("human_decision") == "ESCALATE") for p in sup.get("previous_investigations", [])):
        add(5, "A previous investigation of this customer was escalated", [])
    score = min(100.0, sum(s["points"] for s in signals))
    rec = next(r for t, r in RECOMMENDATIONS if score >= t)
    return score, rec, signals


def investigation_agent(state: InvestigationState, ctx: RunContext) -> dict:
    from agents.narrative import write_narrative

    findings = state.get("findings", {})
    score, rec, signals = assess(findings)
    narrative = write_narrative(state, ctx, score, rec, signals)
    obs_ref = ctx.evidence("AGENT_OBSERVATION", "investigation", f"Investigation summary ({narrative['source']})",
                           {"summary": narrative["summary"], "key_findings": narrative["key_findings"],
                            "validation": narrative["validation"]},
                           ai_generated=narrative["source"].startswith("llm"))
    failed = [e["agent"] for e in state.get("errors", [])]
    return {"assessment_score": score, "recommendation": rec, "signals": signals, "summary": narrative["summary"],
            "key_findings": narrative["key_findings"], "narrative_source": narrative["source"],
            "narrative_validation": narrative["validation"], "observation_ref": obs_ref, "agents_failed": failed,
            "limitations": ([f"Agents that failed and are missing from this assessment: {', '.join(failed)}"] if failed else [])}


# =========================================================================== 8. Reporting agent
def reporting_agent(state: InvestigationState, ctx: RunContext) -> dict:
    from agents.report import build_report

    report_id, version = build_report(state, ctx)
    return {"report_id": report_id, "version": version}
