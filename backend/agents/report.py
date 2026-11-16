"""Investigation report: the ten sections from the project brief, as JSON and Markdown."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.state import InvestigationState, RunContext
from app.db import get_engine
from app.models import Customer, InvestigationReport

NEXT_STEPS = {
    "ESCALATE_TO_MLRO": ["Investigation Manager to review the evidence and decide whether to escalate to the MLRO "
                         "for SAR consideration.", "Do not inform the customer (tipping-off prohibition).",
                         "Review connected accounts in the listed network/patterns for related cases."],
    "FURTHER_INVESTIGATION": ["Analyst to verify the flagged transactions against source records.",
                              "Request business rationale from the relationship manager (without tipping off).",
                              "Re-run the investigation after new information is added."],
    "CLOSE_NO_FURTHER_ACTION": ["Investigation Manager to confirm closure with a documented rationale.",
                                "Keep monitoring under the standard alert process."],
}


def _ev(state: InvestigationState, refs: list[str]) -> list[dict]:
    by = {e["ref"]: e for e in state.get("evidence", [])}
    return [by[r] for r in refs if r in by]


def build_report(state: InvestigationState, ctx: RunContext) -> tuple[int, int]:
    f = state.get("findings", {})
    sup, tx, fr = f.get("supervisor", {}), f.get("transaction", {}), f.get("fraud_detection", {})
    rk, gr, co, inv = f.get("customer_risk", {}), f.get("graph_intelligence", {}), f.get("compliance", {}), f.get("investigation", {})
    with Session(get_engine()) as s:
        c = s.get(Customer, state["customer_id"])
        version = (s.scalar(select(func.count()).select_from(InvestigationReport)
                            .where(InvestigationReport.investigation_id == ctx.investigation_id)) or 0) + 1
        content = {
            "case": {"investigation_id": ctx.investigation_id, "run_id": ctx.run_id, "customer_id": state["customer_id"],
                     "request": state["request_text"], "requested_by": ctx.actor.username},
            "1_summary": {"text": inv.get("summary"), "key_findings": inv.get("key_findings", []),
                          "assessment_score": inv.get("assessment_score"), "recommendation": inv.get("recommendation"),
                          "narrative_source": inv.get("narrative_source"), "limitations": inv.get("limitations", [])},
            "2_customer": {"customer_id": c.customer_id, "name": c.full_name, "segment": c.segment, "country": c.country,
                           "kyc_level": c.kyc_level, "pep": c.pep_flag, "onboarding_date": str(c.onboarding_date),
                           "risk_score": rk.get("risk_score"), "risk_level": rk.get("risk_level"),
                           "previous_investigations": sup.get("previous_investigations", [])},
            "3_transaction_patterns": {"transaction_count": tx.get("transaction_count"), "total_value": tx.get("total_value"),
                                       "cross_border_share": tx.get("cross_border_share"),
                                       "near_threshold_outgoing": tx.get("near_threshold_outgoing"),
                                       "flagged": _ev(state, tx.get("flagged_transaction_refs", []))},
            "4_ml_findings": {"model": fr.get("model"), "band_counts": fr.get("band_counts"),
                              "max_probability": fr.get("max_probability"),
                              "predictions": _ev(state, fr.get("prediction_refs", []))},
            "5_graph_analysis": ({"skipped": "graph not built"} if "graph_intelligence" not in f else
                                 {"cycles": gr.get("cycle_count"), "chains": gr.get("chain_count"),
                                  "networks": gr.get("network_levels"), "pagerank_percentile": gr.get("max_pagerank_percentile"),
                                  "risky_neighbour_share": gr.get("max_neighbour_high_risk_share"),
                                  "patterns": _ev(state, gr.get("pattern_refs", [])),
                                  "network_evidence": _ev(state, gr.get("network_refs", []))}),
            "6_compliance_references": _ev(state, co.get("policy_refs", [])),
            "7_supporting_evidence": [{k: e[k] for k in ("ref", "evidence_type", "source_agent", "title", "source_table",
                                                          "source_id", "ai_generated")} for e in state.get("evidence", [])],
            "8_recommended_next_steps": NEXT_STEPS.get(inv.get("recommendation"), []),
            "9_human_reviewer_decision": {"status": "PENDING", "note": "To be completed by an Investigation Manager."},
            "10_final_status": "AWAITING_HUMAN_REVIEW",
            "assessment_signals": inv.get("signals", []),
            "agent_errors": state.get("errors", []),
        }
        rep = InvestigationReport(investigation_id=ctx.investigation_id, run_id=ctx.run_id, version=version, content=content,
                                  content_markdown=to_markdown(content), narrative_source=inv.get("narrative_source") or "template")
        s.add(rep)
        s.commit()
        return rep.id, version


def to_markdown(r: dict) -> str:
    def evl(items):
        return "\n".join(f"- **[{e['ref']}]** {e['title']}" for e in items) or "- none"

    c, sm = r["2_customer"], r["1_summary"]
    md = [f"# Investigation report - {r['case']['customer_id']}",
          f"_Run {r['case']['run_id']} - requested by {r['case']['requested_by']}: \"{r['case']['request']}\"_",
          "", "> Indicators for human review only. This report does not determine that any offence occurred.", "",
          "## 1. Investigation summary", sm["text"] or "-", "",
          f"**Assessment score:** {(sm['assessment_score'] or 0):.0f}/100 - **AI recommendation:** "
          f"{(sm['recommendation'] or '-').replace('_', ' ')} _(narrative: {sm['narrative_source']})_", ""]
    md += [f"- {k}" for k in sm["key_findings"]] + [""]
    md += [f"_Limitation: {x}_" for x in sm["limitations"]]
    md += ["## 2. Customer information",
           f"{c['name']} ({c['customer_id']}) - {c['segment']}, {c['country']}, KYC {c['kyc_level']}, onboarded "
           f"{c['onboarding_date']}{', PEP' if c['pep'] else ''}. Customer risk: {c['risk_level']} ({c['risk_score']}).",
           f"Previous investigations: {len(c['previous_investigations'])}", "",
           "## 3. Suspicious transaction patterns",
           f"{r['3_transaction_patterns']['transaction_count']} transactions, total "
           f"{(r['3_transaction_patterns']['total_value'] or 0):,.2f}; cross-border share "
           f"{(r['3_transaction_patterns']['cross_border_share'] or 0):.0%}; near-threshold outgoing: "
           f"{r['3_transaction_patterns']['near_threshold_outgoing']}.", evl(r["3_transaction_patterns"]["flagged"]), "",
           "## 4. ML findings",
           f"Model: {(r['4_ml_findings']['model'] or {}).get('name', '-')} {(r['4_ml_findings']['model'] or {}).get('version', '')}; "
           f"bands: {r['4_ml_findings']['band_counts']}.", evl(r["4_ml_findings"]["predictions"]), "",
           "## 5. Graph analysis"]
    g = r["5_graph_analysis"]
    md += (["Graph not built for this dataset."] if "skipped" in g else
           [f"Circular flows: {g['cycles']}, layering chains: {g['chains']}, networks: {g['networks'] or 'none'}.",
            evl(g["patterns"] + g["network_evidence"])])
    md += ["", "## 6. Compliance references", evl(r["6_compliance_references"]), "",
           "## 7. Supporting evidence"]
    md += [f"| Ref | Type | Agent | Source | AI-generated |", "|---|---|---|---|---|"]
    md += [f"| {e['ref']} | {e['evidence_type']} | {e['source_agent']} | {e['source_table'] or '-'}:{e['source_id'] or '-'} | "
           f"{'yes' if e['ai_generated'] else 'no'} |" for e in r["7_supporting_evidence"]]
    md += ["", "## 8. Recommended next steps"] + [f"1. {x}" for x in r["8_recommended_next_steps"]]
    md += ["", "## 9. Human reviewer decision", "_Pending - an Investigation Manager decides._", "",
           "## 10. Final investigation status", r["10_final_status"]]
    return "\n".join(md)
