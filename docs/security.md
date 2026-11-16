# Security & governance (Phase 4)

| Control | Implementation | Code |
|---|---|---|
| Authentication | Username + password → HS256 JWT (8 h, `JWT_SECRET`); deactivated users are rejected on every request | `app/security.py`, `routers/auth.py` |
| Password storage | Salted PBKDF2-SHA256, 240k iterations (stdlib); policy: 10+ chars, upper-case letter, digit | `app/security.py` |
| Role-based access | 6 roles, 11 permissions in one table (`PERMISSIONS`); enforced on every API router and every agent/MCP tool | `app/security.py`, `app/main.py`, `tools/registry.py` |
| Least privilege | Operations managers see aggregates only; admins manage users but cannot investigate or decide | `PERMISSIONS` |
| Separation of duties | Analysts run and submit; only Investigation Managers decide; **four-eyes**: never on a case you created or submitted; a written rationale is required | `app/services/cases.py` |
| Human approval | Agents stop at REPORT_READY. Submission and decisions are human-only; MCP has no decide tool | `agents/runner.py`, `mcp_server/server.py` |
| Sensitive data | Date of birth masked (`YYYY-**-**`) for roles without `view_pii`; tools omit it too | `routers/customers.py`, `tools/registry.py` |
| Audit logging | Logins (success/failure), profile views (evidence-access history), every tool call (args, outcome, role), case creation/run/submit/decision, user changes, AI overrides, model/graph/RAG jobs | `audit_logs` table |
| AI recommendation history & overrides | Every case stores the AI recommendation; every decision records `overrides_ai` when the human chose differently | `approvals.overrides_ai`, Governance page |
| Agent execution history | One row per agent step: tools called, evidence produced, attempts, duration, model, errors | `agent_execution_logs` |
| Input validation | Pydantic models on every endpoint and tool; ids constrained by regex; length limits | routers, `tools/registry.py` |
| Prompt-injection safeguards | Retrieved text and evidence are wrapped and declared as data; injection phrasing in questions/requests is flagged; LLM outputs are constrained to a JSON schema; citations are validated; uncited findings dropped; guilt-stating language rejected → verified template | `rag/answer.py`, `agents/narrative.py` |
| MCP permission controls | Service identity + role, read-only default, same validation and audit as the agents | `mcp_server/server.py` |
| Data privacy | Synthetic data only; secrets in `.env` (git-ignored); tokens kept in `sessionStorage` (cleared when the tab closes) | `.gitignore`, `frontend/src/api.ts` |

## Known limitations (development build)

- Bearer tokens live in `sessionStorage`; a production build should use an HttpOnly cookie + CSRF protection.
- No refresh tokens or login rate limiting; failed logins are audited but not throttled.
- `/metrics` is unauthenticated - keep it on an internal network (Prometheus scrapes it).
- Retention controls are documented (5 years per the synthetic policy) but no automated purge job exists.
- Timestamps written by the database default (`created_at`) are UTC while synthetic transaction times are naive local times.
