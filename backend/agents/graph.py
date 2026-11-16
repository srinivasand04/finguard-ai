"""LangGraph wiring: nodes, conditional routing and the compiled workflow."""
from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, StateGraph

from agents.nodes import (agent_node, compliance_agent, customer_risk_agent, fraud_agent, graph_agent,
                          investigation_agent, reporting_agent, supervisor, transaction_agent)
from agents.state import InvestigationState


def route_after_supervisor(state: InvestigationState) -> str:
    """Stop early if the supervisor could not establish a valid, safe subject."""
    return END if state.get("halt") else "transaction"


def route_after_customer_risk(state: InvestigationState) -> str:
    """Skip graph intelligence when no graph has been built for this dataset."""
    risk = state.get("findings", {}).get("customer_risk", {})
    return "graph_intelligence" if risk.get("graph_available", True) else "compliance"


@lru_cache
def build_graph():
    g = StateGraph(InvestigationState)
    for name, fn in [("supervisor", supervisor), ("transaction", transaction_agent), ("fraud_detection", fraud_agent),
                     ("customer_risk", customer_risk_agent), ("graph_intelligence", graph_agent),
                     ("compliance", compliance_agent), ("investigation", investigation_agent),
                     ("reporting", reporting_agent)]:
        g.add_node(name, agent_node(name, fn))
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", route_after_supervisor, {"transaction": "transaction", END: END})
    g.add_edge("transaction", "fraud_detection")
    g.add_edge("fraud_detection", "customer_risk")
    g.add_conditional_edges("customer_risk", route_after_customer_risk,
                            {"graph_intelligence": "graph_intelligence", "compliance": "compliance"})
    g.add_edge("graph_intelligence", "compliance")
    g.add_edge("compliance", "investigation")
    g.add_edge("investigation", "reporting")
    g.add_edge("reporting", END)
    return g.compile()


def mermaid() -> str:
    """Diagram of the compiled workflow (rendered in the docs)."""
    return build_graph().get_graph().draw_mermaid()
