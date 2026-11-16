"""Multi-agent investigation workflow (Phase 3), orchestrated with LangGraph.

Supervisor -> Transaction -> Fraud Detection -> Customer Risk -> [Graph Intelligence] ->
Compliance -> Investigation -> Reporting -> human review.

Agents only see data through the permissioned tool registry (tools/registry.py) - the
same tools the MCP server exposes - so every fact in a report traces back to a tool
call, an evidence record and a database row.
"""
