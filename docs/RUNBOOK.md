# FinGuard AI - Runbook (all four phases)

Commands are for **Git Bash on Windows** (the paths use `.venv/Scripts/`). On macOS/Linux use `.venv/bin/` instead.

## 0. One-time setup

```bash
cp .env.example .env            # then edit .env: set JWT_SECRET to a long random value
```

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste the output into JWT_SECRET
```

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
cd ../frontend && npm install
```

Optional local LLM (for compliance answers and investigation narratives without an API key):

```bash
ollama pull qwen3:4b
```

## 1. Start the services

```bash
docker compose up -d postgres redis qdrant
```

## 2. Build the data, models, graph and knowledge base (first time, ~10 min)

```bash
cd backend
.venv/Scripts/python -m app.cli all
```

`all` = init-db (drops tables) → generate → ingest → EDA → train → score → graph → risk → alerts → rag-build → seed-users.

**Upgrading an existing database instead** (keeps your data, adds missing tables and demo users; `--reset-passwords` applies a changed `DEMO_USER_PASSWORD` to existing demo accounts):

```bash
.venv/Scripts/python -m app.cli init-db
.venv/Scripts/python -m app.cli seed-users
```

Demo accounts - the username is the role (password = `DEMO_USER_PASSWORD` in `.env`):

| Username | Role | Can do |
|---|---|---|
| `fraud_analyst` | Fraud analyst | investigate, submit for approval, score |
| `aml_analyst` | AML analyst | same as fraud analyst |
| `compliance_officer` | Compliance officer | view cases and evidence, audit, compliance assistant |
| `investigation_manager` | Investigation manager | **decide** on cases (approve / escalate / reject / more info) |
| `operations_manager` | Operations manager | dashboards and aggregates only (no customer data) |
| `admin` | Administrator | users & roles, audit, read access (cannot investigate or decide) |

## 3. Run the app

Terminal 1 - API:

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Terminal 2 - dashboard:

```bash
cd frontend && npm run dev
```

Open http://localhost:5173 and sign in. API docs: http://localhost:8000/docs (click *Authorize* and log in).

## 4. Try the Phase 3 workflow (human in the loop)

1. Sign in as `fraud_analyst` → **Investigations** → type *"Investigate suspicious transactions involving customer CUST11493"* → **Start investigation**. Watch the eight agents complete (≈1-3 min on CPU; the first run loads the search models).
2. Read the summary, click evidence chips (E1, E2…), download the Markdown report, then **Submit for approval**.
3. Sign out, sign in as `investigation_manager`, open the case, write a rationale and **Escalate / Approve / Request more info / Reject**. A decision that differs from the AI recommendation is recorded as an override.
4. Sign in as `compliance_officer` → **Audit & governance**: decisions, override rate, agent success rates, audit trail.

Same thing from the command line (no browser):

```bash
cd backend && .venv/Scripts/python -m app.cli investigate --customer CUST11493
```

## 5. Evaluations

```bash
cd backend
.venv/Scripts/python -m pytest -q                   # 73 tests, offline (SQLite, in-memory Qdrant)
.venv/Scripts/python -m app.cli agent-eval --n 12  # agent workflow vs ground truth (add --llm for LLM narratives)
.venv/Scripts/python -m app.cli rag-eval           # retrieval + answer quality (needs an LLM)
```

## 6. MCP server (use FinGuard tools from Claude Desktop / Claude Code / any MCP client)

```bash
cd backend && .venv/Scripts/python -m mcp_server.server
```

See [mcp.md](mcp.md) for the client configuration. It is **read-only** unless `MCP_READ_ONLY=false`.

## 7. Monitoring (Prometheus + Grafana)

```bash
docker compose --profile monitoring up -d
```

- Prometheus: http://localhost:9090 - scrapes the API's `/metrics` (works when the API runs on your machine or in Docker)
- Grafana: http://localhost:3000 - user `admin`, password `GRAFANA_ADMIN_PASSWORD` from `.env` (or `admin`, which Grafana asks you to change). Dashboard: *FinGuard AI → API, agents & LLM*.
- Langfuse (optional LLM tracing): set `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` in `.env` and restart the API.

## 8. Everything in Docker

```bash
docker compose --profile app up -d --build
docker compose exec backend python -m app.cli all
```

Dashboard on http://localhost:5173 (nginx), API on http://localhost:8000. Ollama on your machine is reached from the container via `host.docker.internal`.

## 9. Deploying to a cloud VM

**Full guide with HTTPS and a one-command deploy script: [DEPLOYMENT.md](DEPLOYMENT.md).** Outline:

1. Create a Linux VM (2 vCPU / 8 GB RAM is enough for the demo) with Docker installed; open only ports 80/443.
2. `git clone` the repo, create `.env` with a strong `JWT_SECRET`, a real `DEMO_USER_PASSWORD` (or create users with `app.cli create-user`), and an `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (a CPU VM is too slow for a local LLM).
3. `docker compose --profile app up -d --build`, then `docker compose exec backend python -m app.cli all`.
4. Put a TLS reverse proxy (Caddy / Traefik / cloud load balancer) in front of the frontend container; keep Postgres, Redis, Qdrant and `/metrics` off the public internet.
5. CI (GitHub Actions) already tests and builds both images on every push; add a push-to-registry + deploy step once you choose a cloud.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Login works but every page says "Not authenticated" | `JWT_SECRET` changed while the API was running - sign in again |
| Narrative always says `template` | No LLM reachable: start Ollama or set an API key. Check `GET /api/v1/compliance/status` |
| Ollama calls slow/time out on Windows | Use `OLLAMA_URL=http://127.0.0.1:11434` (not `localhost`, which tries IPv6 first) |
| Hugging Face 401 on first `rag-build` | An expired token in `~/.cache/huggingface/token`; FinGuard downloads public models without it |
| Port 5432/5433 busy | FinGuard's Postgres uses 55432 (`POSTGRES_HOST_PORT`) |
