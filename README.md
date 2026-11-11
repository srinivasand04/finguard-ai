# FinGuard AI

**A hands-on learning project: building an intelligent financial-crime investigation platform, one type of intelligent system at a time.**

FinGuard AI helps (simulated) bank analysts find suspicious money movement, understand customer risk, trace money through networks of accounts, and ask cited questions of AML/KYC policy - and, in later phases, investigate cases with collaborating AI agents. Each phase adds a different family of intelligent system on top of the last, so the repository doubles as a worked example of how they fit together in one production-style application.

> All data is synthetic. Scores, risk bands and alerts are **investigative indicators for human review - never determinations of fraud**.

![Phase](https://img.shields.io/badge/phase-2%20of%204%20complete-2563eb) ![Python](https://img.shields.io/badge/python-3.12-3776ab) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![React](https://img.shields.io/badge/React-19-61dafb) ![Tests](https://img.shields.io/badge/tests-58%20passing-16a34a)

## Intelligent system types covered

| # | System type | What it does in FinGuard | Key techniques | Phase | Status |
|---|---|---|---|---|---|
| 1 | **Predictive ML (supervised)** | Probability that a transaction belongs to a laundering pattern | XGBoost, Random Forest, chronological validation, PR-AUC, top-k recall | 1 | Done |
| 2 | **Anomaly detection (unsupervised)** | Flags behaviour unlike anything seen before, no labels needed | Isolation Forest, percentile calibration | 1 | Done |
| 3 | **Rule-based / expert system** | Encodes analyst knowledge as transparent, configurable rules | Structuring rule, weighted risk indicators in JSON config | 1 | Done |
| 4 | **Explainable AI (XAI)** | Shows *why* each score is what it is | Per-transaction TreeSHAP contributions, indicator-level reasons | 1 | Done |
| 5 | **Real-time decisioning** | Scores a new transaction against live history | Shared point-in-time feature pipeline for batch + online | 1 | Done |
| 6 | **Graph intelligence** | Finds round-tripping, layering chains and mule networks | NetworkX PageRank, betweenness, Louvain communities, time-ordered cycle/chain search, shortest paths | 2 | Done |
| 7 | **Knowledge system (RAG)** | Answers AML/KYC policy questions with verified citations | PDF/DOCX extraction, section-aware chunking, Sentence Transformers, Qdrant, BM25 + RRF hybrid search, cross-encoder reranking, Claude / OpenAI / local Ollama, labelled evaluation | 2 | Done |
| 8 | **Multi-agent system** | Specialist agents collaborate on an investigation | LangGraph supervisor, shared state, routing, retries | 3 | Planned |
| 9 | **Tool-using AI (MCP)** | Agents act only through approved, permissioned tools | Python MCP SDK, validation, audit | 3 | Planned |
| 10 | **Human-in-the-loop governance** | People approve, reject or escalate - AI never decides alone | Approvals, audit trails, RBAC, observability (Langfuse) | 3-4 | Started (audit log) |

## Architecture

```mermaid
flowchart TB
    subgraph Data["Data layer"]
        G[AMLSim-format generator] --> V[Validate & clean] --> PG[(PostgreSQL)]
        DOCS[Policy PDFs / DOCX / TXT / MD]
    end
    subgraph Detect["Detection engine - Phase 1"]
        F[Point-in-time features] --> XGB[XGBoost<br/>supervised]
        F --> IF[Isolation Forest<br/>unsupervised]
        XGB --> RS[Transaction risk score<br/>+ explanations]
        IF --> RS
    end
    subgraph Graph["Graph intelligence - Phase 2"]
        GE[Money-flow graph] --> GM[PageRank, betweenness,<br/>Louvain communities]
        GE --> GP[Time-ordered cycles<br/>& layering chains]
        GP --> GN[Suspicious networks]
    end
    subgraph Know["Knowledge engine - Phase 2"]
        CH[Extract & section-aware chunks] --> EMB[Embeddings in Qdrant]
        CH --> BM[BM25]
        EMB --> HY[Hybrid RRF + rerank]
        BM --> HY
        HY --> LLM[LLM answer with<br/>verified citations]
    end
    PG --> F
    RS --> GE
    RS --> CR[Customer risk<br/>indicator rules]
    GM --> CR
    GN --> CR
    RS --> AL[Alerts]
    GP --> AL
    GN --> AL
    CR --> AL
    DOCS --> CH
    AL --> API[FastAPI + Redis] --> UI[React dashboard]
    LLM --> API
    subgraph Later["Phases 3-4"]
        AG[LangGraph agents + MCP tools] --> HR[Human review & approvals]
    end
    AL -.-> AG
    GN -.-> AG
    LLM -.-> AG
```

## What I learned building Phase 1

- **Accuracy and ROC-AUC mislead on rare events.** At a 0.25% laundering rate, PR-AUC and recall within an analyst's review budget (top 1%) are the honest metrics.
- **Leakage hides in features and in the data generator.** All behavioural features use only events strictly before each transaction, and the data is split by time. A generator quirk briefly made "payment type" the best predictor (PR-AUC 0.86). It was found from feature importance and removed, which lowered the real result to 0.78.
- **Supervised and unsupervised models do different jobs.** The anomaly model is weak at finding *known* patterns but surfaces *unknown* ones, so it gets a small, thresholded weight in the blended score.
- **Explainability shapes the design.** Exact explanations for all 226k rows took 8 minutes, so they are now exact for flagged rows and approximate for the rest (71 seconds).
- **One feature function for batch and real-time** prevents the training/serving skew common in production ML.

Full write-up: [docs/phase1_report.md](docs/phase1_report.md).

## What I learned building Phase 2

- **Graph context is what exposes mule accounts.** Adding four graph indicators to customer risk raised recall of laundering customers from **17% to 83%**, and precision also rose (88% → 91%). Mule accounts look ordinary one transaction at a time; their connections give them away.
- **Aggregation destroys the signal.** Cycles on an aggregated account graph are everywhere (payroll, suppliers, refunds). Following individual transactions *forward in time* while they keep their value turned cycle detection into a 75%-precision detector that finds 100% of simulated round-tripping.
- **"Unusual for whom?"** The first layering-chain detector flagged 4,074 chains at 1.5% precision, because busy businesses forward similar amounts every day. Requiring each hop to be large *for that account's own baseline* cut the noise 4.7x.
- **Fusion is not enough; reranking is.** Dense vectors match paraphrases ("splitting deposits" → *structuring*) and BM25 matches exact thresholds ("EUR 15,000", "25%"). Fusing them with RRF made the right passage appear in the top 3 every time, but slightly *lowered* top-1 accuracy (0.65). A cross-encoder reranker lifted top-1 to **0.87** and MRR to **0.92** on a labelled question set.
- **Read the outputs, not just the metrics.** The first answer evaluation scored 98% fact recall - yet every output was the model's reasoning transcript, which merely *mentioned* the facts. Constraining generation to a JSON schema produced real answers 7x faster; rewording the prompt so refusal is the last resort then lifted fact recall from 0.57 to 0.78 with faithfulness 0.88. The evaluation now checks answer *format* so it cannot be fooled the same way again.
- **Grounding needs guardrails, not just a prompt.** Citations are validated after generation, unsupported questions must be refused, and with no LLM the system quotes sources instead of inventing text.
- **Design for the machine you have.** The whole stack runs locally: Qdrant in Docker, CPU embeddings, and a 4B model in Ollama. Claude or OpenAI can be switched on with an API key.

Full write-up: [docs/phase2_report.md](docs/phase2_report.md).

## What Phase 1 contains

| Area | What is built | Where |
|---|---|---|
| Data | AMLSim-format synthetic generator (8 laundering typologies, injected dirty rows) | `backend/data_gen/amlsim_synth.py` |
| Ingestion | Read → validate/clean (rejections with reasons) → categorise → bulk `COPY` into Postgres | `backend/app/services/ingestion.py`, `validation.py` |
| Database | 8 tables in PostgreSQL 16, Redis cache | `backend/app/models.py`, `docs/database_design.md` |
| EDA | Markdown report + charts | `docs/eda_report.md`, `docs/eda/` |
| Features | 28 point-in-time features (velocity, new counterparties, fan-in, pass-through, structuring, geography) | `backend/ml/features.py` |
| Models | XGBoost (active), Random Forest (benchmark), Isolation Forest (anomaly); chronological split; registry with metrics | `backend/ml/train.py`, `models/` |
| Scoring | Batch + near-real-time, with per-transaction explanations (XGBoost contributions) | `backend/ml/scoring.py` |
| Customer risk | Behavioural profiles + configurable, explainable indicator scoring | `backend/app/services/risk_scoring.py`, `backend/config/risk_config.json` |
| Alerts | ML, anomaly, structuring rule, high-risk customer | `backend/app/services/alerting.py` |
| API | FastAPI, 19 endpoints, OpenAPI docs | `backend/app/api/routers/`, `docs/api_documentation.md` |
| Dashboard | React + TypeScript + Tailwind: dashboard, transactions, customers, alerts, models, live scoring | `frontend/src/` |
| Tests | 33 pytest tests (unit + full-pipeline integration + every endpoint) | `backend/tests/` |
| Results | Model evaluation and design decisions | `docs/phase1_report.md` |

## What Phase 2 adds

| Area | What is built | Where |
|---|---|---|
| Money-flow graph | Aggregated account graph, PageRank, betweenness, Louvain communities | `backend/graph/builder.py`, `analytics.py` |
| Flow patterns | Time-ordered circular flows and layering chains, each tied to its exact transactions | `backend/graph/patterns.py` |
| Suspicious networks | Risk subgraph → reviewable groups with hub roles and typology hints | `backend/graph/analytics.py` |
| Risk integration | 4 graph indicators in customer risk, 3 graph alert types | `backend/config/risk_config.json`, `app/services/` |
| Compliance corpus | 8 policy documents in PDF / DOCX / TXT / MD | `backend/rag/corpus.py` → `documents/` |
| RAG pipeline | Section-aware extraction + chunking, Sentence Transformers, Qdrant, BM25, RRF, cross-encoder rerank | `backend/rag/` |
| Answers | Claude / OpenAI / local Ollama / extractive fallback, verified citations, injection guard | `backend/rag/answer.py`, `llm.py` |
| Evaluation | Graph detection vs ground truth; labelled 25-question RAG set (retrieval + answer metrics) | `backend/graph/pipeline.py`, `backend/rag/evaluation.py` |
| API | 8 graph + 6 compliance endpoints | `backend/app/api/routers/graph.py`, `compliance.py` |
| Dashboard | Network explorer (Cytoscape.js: ego networks, patterns, networks, shortest path) and Compliance assistant | `frontend/src/pages/Network.tsx`, `Compliance.tsx` |
| CI | GitHub Actions: 58 backend tests + frontend build on every push | `.github/workflows/ci.yml` |

## Quick start (Windows / macOS / Linux)

Prerequisites: Docker Desktop, Python 3.12, Node 20+.

```bash
cp .env.example .env
docker compose up -d postgres redis qdrant   # Postgres :55432, Redis :6380, Qdrant :6333
```

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m app.cli all               # data, ML, graph, risk, alerts, RAG index (~10 min; downloads 2 small models)
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev                                   # http://localhost:5173  (proxies /api to :8000)
```

- Dashboard: http://localhost:5173
- API docs (Swagger): http://localhost:8000/docs

Ports 5432/5433 are often used by a local Postgres install, so the container is published on **55432**. Change `POSTGRES_HOST_PORT` / `DATABASE_URL` in `.env` if needed.

### Individual pipeline steps

```bash
python -m app.cli init-db --drop
python -m app.cli generate --customers 1500 --days 180
python -m app.cli ingest --source ../data/raw/amlsim     # works with real AMLSim output too
python -m app.cli eda
python -m app.cli train
python -m app.cli score
python -m app.cli graph       # Phase 2: graph intelligence
python -m app.cli risk
python -m app.cli alerts
python -m app.cli rag-build   # Phase 2: compliance corpus -> chunks -> Qdrant
python -m app.cli rag-eval    # Phase 2: retrieval + answer evaluation
```

### LLM for the compliance assistant

`LLM_PROVIDER=auto` (default) uses the first that is available: `ANTHROPIC_API_KEY` → `OPENAI_API_KEY` → a running [Ollama](https://ollama.com) (`ollama pull qwen3:4b`) → extractive mode (quotes the best passages, no LLM). Set these in `.env`.

### Run everything in Docker (optional)

```bash
docker compose --profile app up -d --build
docker compose exec backend python -m app.cli all
```

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest -q
```

The test suite (58 tests) generates a small dataset, runs the **whole pipeline** - ML, graph and RAG - into a throwaway SQLite database with an in-process Qdrant and an offline embedder, and calls every API endpoint. No Docker or model downloads needed; the same suite runs in GitHub Actions.

## Reviewing Phase 1 - suggested checklist

1. **Data**: `data/raw/amlsim/generation_summary.json`, `data/processed/ingestion_report.json`, `data/processed/rejected_transactions.csv` (every rejected row has a reason).
2. **Tables**: `docker compose exec postgres psql -U finguard -d finguard` then e.g. `\dt`, `SELECT risk_level, COUNT(*) FROM customer_risk GROUP BY 1;`
3. **EDA**: `docs/eda_report.md`.
4. **Models**: `docs/phase1_report.md`, `models/evaluation_*.json`, or the Models page.
5. **API**: http://localhost:8000/docs - try `GET /api/v1/customers?risk_level=HIGH` and `POST /api/v1/transactions/score`.
6. **UI**: open a high-risk customer → indicators, profile, velocity, counterparties, transactions → click a transaction → explanation.
7. **Audit**: `GET /api/v1/audit-logs` shows ingestion, training, scoring, graph, RAG and question events.
8. **Graph (Phase 2)**: Network page → open the top suspicious network, a circular flow (hops listed in time order), and a customer's ego network; `docs/phase2_report.md` for detection metrics.
9. **RAG (Phase 2)**: Compliance assistant → ask an example question, click the citation chips, compare hybrid vs BM25 vs dense.

## Repository layout

```
backend/   app/ (API, services, models)  ml/ (features, training, scoring, EDA)  graph/  rag/  data_gen/  config/  tests/
documents/ compliance corpus (generated by rag-build; real PDFs can be added)
frontend/  React + TypeScript + Tailwind dashboard
data/      raw/ processed/ synthetic/        (generated, git-ignored)
models/    fraud/ anomaly/ evaluation_*.json (generated, git-ignored)
docs/      phase1_report.md  phase2_report.md  database_design.md  api_documentation.md  eda_report.md
infrastructure/postgres/init.sql
docker-compose.yml  .env.example
```

## Roadmap

- ~~Phase 1~~ - Data, ML detection, customer risk, API, dashboard - **done**
- ~~Phase 2~~ - Graph intelligence + compliance RAG - **done**
- **Phase 3** - LangGraph multi-agent investigations, MCP server, evidence & case management, approvals
- **Phase 4** - Full frontend, auth/RBAC, Langfuse observability, CI/CD, deployment
