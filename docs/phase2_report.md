# Phase 2 Report - Graph Intelligence & Compliance RAG

Run date: 2026-11-11 · all data synthetic · graph version `g20261111-132903`.

Phase 2 adds two new families of intelligent system on top of the Phase 1 detection engine:

1. **Graph intelligence** - treats accounts as a network and looks for *how money moves*, not just individual transactions.
2. **A knowledge system (RAG)** - answers AML/KYC policy questions with verifiable citations.

---

## Part A - Graph intelligence

### What was built

| Step | Technique | Code |
|---|---|---|
| Money-flow graph | Directed graph, one aggregated edge per account pair (count, value, first/last time, max ML risk) | `graph/builder.py` |
| Centrality | Degree centrality, value-weighted PageRank (where money accumulates), sampled betweenness (brokers) | `graph/analytics.py` |
| Communities | Louvain on the undirected graph weighted by transaction count | `graph/analytics.py` |
| Circular flows | Time-ordered search over *transactions*: A→B→…→A where each hop follows within 96h and keeps 70-110% of the value | `graph/patterns.py` |
| Layering chains | Same search for open paths of ≥3 hops, started only from chain origins, and only when hops are *unusual for the forwarding account* | `graph/patterns.py` |
| Suspicious networks | Connected groups in the *risk subgraph* (pattern edges + edges that carried a HIGH-risk transaction), recursively Louvain-split to a reviewable size, with hub roles and typology hints | `graph/analytics.py` |
| Shortest paths | NetworkX shortest path between any two accounts (API) | `app/api/routers/graph.py` |
| Integration | Graph metrics feed four new customer-risk indicators and three new alert types | `app/services/risk_scoring.py`, `alerting.py` |

Graph size: **2,382 accounts, 71,918 money-flow edges, 24 communities**. Full analysis runs in ~60 s.

### Why "time-ordered" matters

On the aggregated graph, cycles are everywhere - salaries, supplier payments and refunds create them constantly. Round-tripping is different: the *same money* moves forward in time and keeps most of its value. So the search follows individual transactions: from each payment it only considers the receiver's **next** outgoing payments inside a time window and an amount band.

### Results (evaluated against simulator ground truth, which is never used to *find* anything)

| Detector | Found | Precision (mostly laundering tx) | Notes |
|---|---|---|---|
| Circular flows | 20 | **75%** | Detects **100%** of simulated cycle patterns |
| Layering chains (v1: amount + timing only) | 4,074 | 1.5% | Busy businesses pass similar amounts along every day |
| Layering chains (v2: + "unusual for this account") | 856 | 6.5% | 4.3x more precise; alerts only on score ≥ 70 |
| Suspicious networks | 118 (10 HIGH, 19 MEDIUM, 89 LOW) | 22% of members are laundering accounts | Contain **99%** of all laundering accounts |

Share of each simulated typology touched by at least one flow pattern:

| Typology | cycle | gather-scatter | stack | fan-out | scatter-gather | fan-in | bipartite | structuring |
|---|---|---|---|---|---|---|---|---|
| Detected by flow patterns | **100%** | 47% | 33% | 20% | 20% | 13% | 0% | 0% |
| Mostly inside a suspicious network | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |

Flow patterns are built for *chains of value*; fan-in/fan-out, bipartite and structuring are not chains, so they are caught by the networks, ML features and the structuring rule instead. Each detector covers different typologies - that is the point of combining them.

### The headline: graph context makes customer risk far more useful

| Customer risk scoring | Flagged HIGH | Truly laundering | Precision | Recall |
|---|---|---|---|---|
| Phase 1 indicators only (ML + behaviour + KYC) | 42 | 37 | 88% | 17% |
| **+ Phase 2 graph indicators** | **202** | **184** | **91%** | **83%** |

Mule accounts often look ordinary one transaction at a time; their *connections* give them away. Adding four graph indicators (circular flow participation, layering-chain hop, member of a HIGH-risk network, high share of risky neighbours) lifted recall from 17% to 83% while precision also rose.

New alert types: `CIRCULAR_FLOW` (18), `LAYERING_CHAIN` (16), `SUSPICIOUS_NETWORK` (10), each with the exact route or member list as reasons.

### What I learned

- **Aggregation destroys the signal.** Cycles on an aggregated graph are noise; time-ordering and value retention turn them into a 75%-precision detector.
- **"Unusual for whom?" is the key question.** The first chain detector flagged thousands of normal business flows. Comparing each hop with the forwarding account's *own* typical payment cut false positives 4.7x - the same behavioural-baseline idea as the Phase 1 `amount_vs_sender_mean` feature.
- **Networks need to stay human-sized.** A single connected component swallowed 70% of all accounts; recursive Louvain splitting produced 118 reviewable groups.
- **Different detectors cover different typologies.** No single method found everything; the combination does.

---

## Part B - Compliance RAG

### Corpus

8 documents, 4 file formats, 64 section-aware chunks:

| Document | Type | Format |
|---|---|---|
| FinGuard Bank Anti-Money Laundering Policy | AML_POLICY | PDF (3 pages) |
| Transaction Monitoring and Alert Handling Guideline | TRANSACTION_MONITORING | DOCX |
| Sanctions Screening Procedure | SANCTIONS | TXT |
| FATF Recommendations - study notes (paraphrased) | FATF_SUMMARY | MD |
| EU AML Framework - study notes (paraphrased) | EU_AML | MD |
| KYC and Customer Due Diligence Procedure | KYC_POLICY | DOCX |
| Enhanced Due Diligence Standard | EDD_POLICY | PDF |
| Financial Crime Investigation and SAR Escalation Procedure | INVESTIGATION_PROCEDURE | PDF |

FinGuard Bank policies are fictional and contain concrete thresholds and deadlines so answers can be checked. The FATF/EU documents are paraphrased study notes, not official texts. Real PDFs dropped into `documents/` are ingested the same way.

### Pipeline

| Stage | Choice | Why |
|---|---|---|
| Extraction | pypdf (keeps page numbers), python-docx (heading styles), Markdown/TXT heading rules | Every chunk can cite *document, section, page* |
| Chunking | LangChain `RecursiveCharacterTextSplitter` (900 chars, 150 overlap) **inside** each section | A chunk never mixes two sections |
| Embeddings | Sentence Transformers `all-MiniLM-L6-v2` (384-d), title + section prepended | Small, CPU-friendly, good general retrieval |
| Vector store | Qdrant (cosine) with `doc_type` payload filter; Postgres keeps the text | Swappable store, single source of truth |
| Keyword search | BM25 with a tokenizer that keeps amounts (`15,000` → `15000`, `25%`) | Exact thresholds matter in compliance |
| Fusion | Reciprocal Rank Fusion (k = 60) | Combines rankings without calibrating score scales |
| Reranking | Cross-encoder `ms-marco-MiniLM-L-6-v2` over the top 20 | Reads query and passage together |
| Generation | Claude / OpenAI / **local Ollama (qwen3:4b)** / extractive fallback | Works offline with no API key |

Example: the query *"splitting deposits to avoid reporting"* never uses the word "structuring", but hybrid retrieval + reranking returns the **Structuring indicators** section first (dense 0.49, BM25 9.0, rerank 4.6).

### Grounding and safety

1. The model sees only numbered sources wrapped in `<source>` tags and must cite every claim.
2. It must answer exactly "The provided policy documents do not cover this question." when the sources don't.
3. Sources are declared as data; injection phrasing in the question is flagged.
4. Every `[n]` citation is validated after generation; invalid ones are removed and reported.
5. If the LLM fails or none is configured, an extractive answer quotes the top passages with citations - it never invents text.
6. Every question is written to the audit log with the sources used.

### Evaluation

A hand-labelled set of 25 questions (23 answerable with an expected document + section + key facts, 2 deliberately unanswerable). Retrieval metrics are deterministic; answer metrics follow RAGAS concepts (faithfulness, context precision, answer correctness) but are computed against labelled facts so they are free and reproducible.

**Retrieval** (23 answerable questions; a hit = a chunk from the expected document *and* section):

| Strategy | hit@1 | hit@3 | hit@5 | MRR | context precision@5 |
|---|---|---|---|---|---|
| BM25 only | 0.70 | 1.00 | 1.00 | 0.82 | 0.21 |
| Dense only | 0.74 | 0.91 | 1.00 | 0.82 | 0.20 |
| Hybrid (RRF) | 0.65 | 1.00 | 1.00 | 0.81 | 0.20 |
| **Hybrid + cross-encoder rerank** | **0.87** | 0.96 | 1.00 | **0.92** | 0.20 |

What this shows:
- Every strategy finds the right section within the top 3-5, so the LLM almost always *receives* the evidence.
- **Fusion alone slightly lowered top-1 accuracy** - RRF averages two rankings and can blur the winner. The cross-encoder reranker fixes that: top-1 jumps from 0.65 to 0.87 and MRR to 0.92. Hybrid + rerank is the default.
- Context precision@5 is capped near 0.2 by design: most answers live in a single short section, so at most one or two of five passages can be "relevant".

**Answers** (local `qwen3:4b` via Ollama, 25 questions, every answer generated by the LLM - zero fallbacks). The three runs below are the actual iteration history; the first one is kept because it is the most instructive.

| Run | Fact recall | Refusal accuracy | Faithfulness (proxy) | Well-formed | Median latency |
|---|---|---|---|---|---|
| 1. Plain-text output | *0.98 - misleading* | *0.92 - misleading* | 0.25 | **0%** | 93 s |
| 2. JSON-schema output, strict prompt | 0.57 | 0.60 | 0.90 | 100% | 12 s |
| 3. JSON-schema output, refusal as last resort | **0.78** | **0.84** | **0.88** | 96% | 34 s* |

\*Run 3 shared the CPU with other heavy jobs on the machine; run 2 shows the real speed.

What happened:
1. **The model "thought out loud".** This `qwen3:4b` build ignores both `think: false` and the `/no_think` switch and returned its reasoning transcript ("First, I need to answer the question...") cut off at the token limit. The summary metrics looked excellent - the reasoning *mentions* the right facts, and it *quotes* the refusal rule - while not one of the 25 outputs was actually an answer. Reading the per-question outputs exposed it.
2. **Fix: constrained decoding.** Ollama's `format` parameter restricts generation to a JSON schema (`{"answer": string}`) from the first token, so there is nowhere for reasoning to go. Every output became a clean answer, 7x faster. Two guards were added so the evaluation cannot be fooled again: a refusal only counts when the answer *is* the refusal sentence, and answers that open like reasoning are flagged as `reasoning_leak` and never counted as grounded.
3. **Then the opposite problem: over-refusal.** Without room to reason, the small model refused 10 of 23 answerable questions even though retrieval had handed it the right passage. Rewording the prompt so refusal is the last resort ("if any source answers the question, even partly, answer from it") raised fact recall from 0.57 to 0.78 and refusal accuracy from 0.60 to 0.84. Both out-of-scope questions are still refused.

Remaining gap: 4 of 23 answerable questions are still refused by the 4B model. Retrieval is not the bottleneck (the right passage is in the top 5 every time), so a larger model (Claude / OpenAI via `.env`) is the expected fix; the same evaluation runs against any provider with `python -m app.cli rag-eval`.

---

## Model refresh note

The data generator now produces **time-ordered** laundering hops (A pays B, then B pays C), which real laundering does and the graph engine relies on. Pattern start dates moved earlier to leave room for multi-week patterns, so the chronological test window now holds only 41 laundering transactions (was 141). Re-trained XGBoost: PR-AUC 0.69, ROC-AUC 0.99, recall at top 1% 0.83. With so few test positives this number is noisier than in Phase 1 and should not be read as a regression of the method.

## Known limitations / next steps

- Graph metrics use the whole period, so they feed customer risk (a review-time view), not the transaction model - adding point-in-time graph features to the ML model is a Phase 3+ item.
- Chain precision (6.5%) is still low; alerts only fire for high-scoring chains. A learned pattern scorer could replace the hand-set score.
- The local 4B model still over-refuses 4 of 23 answerable questions; Claude or OpenAI can be enabled with an API key in `.env` and evaluated with the same command.
- A full RAGAS run with an LLM judge can be layered on top of the labelled evaluation.
