# FinGuard MCP server

The MCP server exposes the same permissioned tool registry the LangGraph agents use (`backend/tools/registry.py`), so an external AI assistant gets exactly the same data access, validation and audit trail as FinGuard's own agents.

## Tools

| Tool | Kind | Permission | What it returns |
|---|---|---|---|
| `get_customer_profile` | read | view_customers | KYC profile, accounts, explainable risk indicators, alert counts |
| `get_transaction_history` | read | view_customers | statistics + riskiest transactions |
| `get_fraud_prediction` | read | view_customers | ML probabilities, anomaly percentiles, explanations, model version |
| `get_account_relationships` | read | view_customers | graph metrics, cycles, layering chains, networks, counterparties |
| `search_compliance_policy` | read | ask_compliance | cited policy passages (hybrid search + rerank) |
| `get_investigation_history` | read | view_investigations | previous cases and human decisions |
| `create_investigation_case` | **write** | run_investigation | opens a case |
| `generate_investigation_report` | **write** | run_investigation | runs the eight-agent workflow |
| `submit_for_approval` | **write** | submit_for_approval | queues the report for a human |

There is deliberately **no approve/decide tool**: decisions are made only by an Investigation Manager through the authenticated API, and never by the person who submitted the case.

## Security model

- The server acts as one service identity: `MCP_ACTOR_USERNAME` / `MCP_ACTOR_ROLE` (default `mcp-service` / `FRAUD_ANALYST`). Every call is permission-checked against that role and written to `audit_logs` as `mcp:<username>` with its arguments and outcome.
- **Read-only by default** (`MCP_READ_ONLY=true`): write tools return an error until an operator sets `MCP_READ_ONLY=false`.
- Arguments are validated by Pydantic models before any query (e.g. customer ids must match `CUST\d{4,8}`).
- Tool results contain only what the role may see (e.g. date of birth is omitted without `view_pii`).

## Run it

```bash
cd backend
.venv/Scripts/python -m mcp_server.server
```

It speaks MCP over **stdio**, so normally the client starts it for you.

## Claude Desktop / Claude Code configuration

Add to `claude_desktop_config.json` (Claude Desktop) or `.mcp.json` (Claude Code), adjusting the paths:

```json
{
  "mcpServers": {
    "finguard": {
      "command": "D:/Study/FinGuard_AI/backend/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "D:/Study/FinGuard_AI/backend",
      "env": { "MCP_READ_ONLY": "true" }
    }
  }
}
```

The server reads the rest of its settings (database, Qdrant) from the project's `.env`, so Postgres and Qdrant must be running (`docker compose up -d postgres qdrant`).

Example prompts once connected: *"Use FinGuard to summarise the risk indicators for CUST11493 and cite the policy sections that apply."*
