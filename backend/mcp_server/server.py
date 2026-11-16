"""FinGuard MCP server - exposes the permissioned tool registry to any MCP client
(Claude Desktop, Claude Code, an IDE, another agent framework).

Run (stdio transport):
    cd backend
    python -m mcp_server.server

Security model
* The server acts as ONE service identity: MCP_ACTOR_USERNAME / MCP_ACTOR_ROLE (default
  mcp-service / FRAUD_ANALYST). Every call is checked against that role and audit-logged
  as "mcp:<username>".
* Read-only by default (MCP_READ_ONLY=true): create_investigation_case,
  generate_investigation_report and submit_for_approval are refused until an operator
  sets MCP_READ_ONLY=false.
* There is deliberately no "approve" tool: decisions are made only by a human
  Investigation Manager through the authenticated API.
* Arguments are validated by the same Pydantic models the agents use.
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.security import Actor
from tools.registry import TOOLS, ToolDenied, ToolError, call_tool

mcp = FastMCP("finguard", instructions=(
    "FinGuard AI financial-crime investigation tools over synthetic banking data. Risk scores and "
    "patterns are investigative indicators, never proof of wrongdoing. Cite tool results when you use them."))


def _actor() -> Actor:
    s = get_settings()
    return Actor(f"mcp:{s.mcp_actor_username}", s.mcp_actor_role)


def _run(name: str, **args) -> str:
    try:
        out = call_tool(name, _actor(), {k: v for k, v in args.items() if v is not None},
                        read_only=get_settings().mcp_read_only)
        return json.dumps(out, default=str)
    except (ToolDenied, ToolError) as e:          # surfaced to the MCP client as a readable tool error
        return json.dumps({"error": str(e)})


@mcp.tool(description=TOOLS["get_customer_profile"].description)
def get_customer_profile(customer_id: str) -> str:
    return _run("get_customer_profile", customer_id=customer_id)


@mcp.tool(description=TOOLS["get_transaction_history"].description)
def get_transaction_history(customer_id: str, limit: int = 15) -> str:
    return _run("get_transaction_history", customer_id=customer_id, limit=limit)


@mcp.tool(description=TOOLS["get_fraud_prediction"].description)
def get_fraud_prediction(customer_id: str, min_band: str = "MEDIUM", limit: int = 10) -> str:
    return _run("get_fraud_prediction", customer_id=customer_id, min_band=min_band, limit=limit)


@mcp.tool(description=TOOLS["get_account_relationships"].description)
def get_account_relationships(customer_id: str) -> str:
    return _run("get_account_relationships", customer_id=customer_id)


@mcp.tool(description=TOOLS["search_compliance_policy"].description)
def search_compliance_policy(query: str, k: int = 3, doc_type: str | None = None) -> str:
    return _run("search_compliance_policy", query=query, k=k, doc_type=doc_type)


@mcp.tool(description=TOOLS["get_investigation_history"].description)
def get_investigation_history(customer_id: str) -> str:
    return _run("get_investigation_history", customer_id=customer_id)


@mcp.tool(description=TOOLS["create_investigation_case"].description + " (write - disabled in read-only mode)")
def create_investigation_case(request_text: str, customer_id: str | None = None) -> str:
    return _run("create_investigation_case", request_text=request_text, customer_id=customer_id)


@mcp.tool(description=TOOLS["generate_investigation_report"].description + " (write - disabled in read-only mode)")
def generate_investigation_report(investigation_id: int) -> str:
    return _run("generate_investigation_report", investigation_id=investigation_id)


@mcp.tool(description=TOOLS["submit_for_approval"].description + " (write - disabled in read-only mode)")
def submit_for_approval(investigation_id: int, comment: str | None = None) -> str:
    return _run("submit_for_approval", investigation_id=investigation_id, comment=comment)


if __name__ == "__main__":
    mcp.run()          # stdio transport
