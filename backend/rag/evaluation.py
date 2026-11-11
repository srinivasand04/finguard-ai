"""RAG evaluation on a hand-labelled question set.

Retrieval (deterministic, no LLM needed) - compares bm25 / dense / hybrid / hybrid+rerank:
  hit@1, hit@3, hit@5, MRR and context precision@5 (share of the top-5 that are relevant).
  A chunk is relevant when it comes from the expected document AND section.

Answers (needs an LLM; skipped in extractive mode) - RAGAS-style metrics computed
deterministically against labelled facts, so they are reproducible and free:
  * fact recall          - share of expected key facts (numbers/terms) present in the answer
  * citation validity    - every [n] points at a provided source
  * cited-source relevance - at least one cited source is a relevant chunk
  * faithfulness (proxy) - share of answer sentences whose content words are mostly
                           found in the sources they cite
  * refusal accuracy     - unanswerable questions get "not covered", answerable ones do not
A full RAGAS run with an LLM judge can be added on top; these labelled checks are the
regression baseline.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from statistics import mean

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog
from rag.answer import NOT_COVERED, answer_question
from rag.llm import resolve_provider
from rag.retrieval import Hit, get_retriever, tokenize

# (question, expected doc_type, expected section keyword, key facts that a correct answer contains)
EVAL_SET: list[dict] = [
    {"q": "Above what amount must CDD be done for an occasional transaction?", "doc": "KYC_POLICY", "section": "when customer due diligence", "facts": ["15,000"]},
    {"q": "What ownership percentage makes someone a beneficial owner of a company?", "doc": "KYC_POLICY", "section": "beneficial owner", "facts": ["25%"]},
    {"q": "How often are KYC files of high-risk customers reviewed?", "doc": "KYC_POLICY", "section": "periodic review", "facts": ["12 months"]},
    {"q": "How frequently should a medium risk customer's KYC be refreshed?", "doc": "KYC_POLICY", "section": "periodic review", "facts": ["24 months"]},
    {"q": "What happens if customer due diligence cannot be completed?", "doc": "KYC_POLICY", "section": "inability", "facts": ["not open", "terminat"]},
    {"q": "Who must approve a relationship with a politically exposed person?", "doc": "EDD_POLICY", "section": "politically exposed", "facts": ["senior management"]},
    {"q": "How long is someone treated as a PEP after leaving public office?", "doc": "EDD_POLICY", "section": "politically exposed", "facts": ["12 months"]},
    {"q": "When is enhanced due diligence mandatory?", "doc": "EDD_POLICY", "section": "when enhanced", "facts": ["high-risk", "PEP"]},
    {"q": "Which wire transfers to elevated-risk jurisdictions need Compliance review?", "doc": "EDD_POLICY", "section": "high-risk jurisdictions", "facts": ["10,000"]},
    {"q": "How quickly must staff report a suspicion to the MLRO?", "doc": "AML_POLICY", "section": "suspicious activity reporting", "facts": ["1 business day"]},
    {"q": "What is tipping-off?", "doc": "AML_POLICY", "section": "suspicious activity reporting", "facts": ["inform", "customer"]},
    {"q": "How long are customer due diligence records kept?", "doc": "AML_POLICY", "section": "record keeping", "facts": ["5 years"]},
    {"q": "How often do staff in high-risk roles get AML training?", "doc": "AML_POLICY", "section": "training", "facts": ["6 months"]},
    {"q": "Can a model risk score alone prove money laundering?", "doc": "AML_POLICY", "section": "transaction monitoring", "facts": ["never"]},
    {"q": "Within how many business days must a CRITICAL alert be reviewed?", "doc": "TRANSACTION_MONITORING", "section": "prioritisation", "facts": ["1 business day"]},
    {"q": "What pattern of transactions triggers a structuring alert?", "doc": "TRANSACTION_MONITORING", "section": "structuring", "facts": ["9,000", "10,000", "7 days"]},
    {"q": "What is a pass-through indicator?", "doc": "TRANSACTION_MONITORING", "section": "network and layering", "facts": ["72 hours"]},
    {"q": "What share of closed alerts does quality assurance sample?", "doc": "TRANSACTION_MONITORING", "section": "quality assurance", "facts": ["5%"]},
    {"q": "How fast must a potential sanctions match be reviewed?", "doc": "SANCTIONS", "section": "potential matches", "facts": ["4 business hours"]},
    {"q": "Within how many days is a SAR filed after the MLRO decides to report?", "doc": "INVESTIGATION_PROCEDURE", "section": "sar filing", "facts": ["5 business days"]},
    {"q": "What must every finding in an investigation reference?", "doc": "INVESTIGATION_PROCEDURE", "section": "evidence", "facts": ["transaction identifiers"]},
    {"q": "Which FATF recommendation covers wire transfer information?", "doc": "FATF_SUMMARY", "section": "wire transfers", "facts": ["16"]},
    {"q": "What is the EU cash payment limit under the AML Regulation?", "doc": "EU_AML", "section": "cash limit", "facts": ["10,000"]},
    {"q": "What is the capital of Australia?", "doc": None, "section": None, "facts": []},
    {"q": "What is FinGuard Bank's policy on cryptocurrency staking rewards?", "doc": None, "section": None, "facts": []},
]

MODES = [("bm25", False), ("dense", False), ("hybrid", False), ("hybrid", True)]


def is_relevant(h: Hit, item: dict) -> bool:
    return bool(item["doc"]) and h.doc_type == item["doc"] and item["section"] in (h.section or "").lower()


def retrieval_metrics(retriever, items: list[dict], mode: str, rerank: bool) -> dict:
    hits1, hits3, hits5, rr, prec = [], [], [], [], []
    for it in items:
        res = retriever.search(it["q"], k=5, mode=mode, rerank=rerank)
        rel = [is_relevant(h, it) for h in res]
        first = next((i for i, r in enumerate(rel) if r), None)
        hits1.append(first is not None and first < 1)
        hits3.append(first is not None and first < 3)
        hits5.append(first is not None)
        rr.append(0 if first is None else 1 / (first + 1))
        prec.append(sum(rel) / max(len(rel), 1))
    return {"hit@1": round(mean(hits1), 3), "hit@3": round(mean(hits3), 3), "hit@5": round(mean(hits5), 3),
            "mrr": round(mean(rr), 3), "context_precision@5": round(mean(prec), 3)}


def faithfulness_proxy(answer: str, sources: list[dict]) -> float | None:
    by_id = {s["id"]: set(tokenize(s["text"])) for s in sources}
    scores = []
    for sent in re.split(r"(?<=[.!?])\s+", answer):
        ids = [int(x) for x in re.findall(r"\[(\d{1,2})\]", sent) if int(x) in by_id]
        words = [w for w in tokenize(re.sub(r"\[\d+\]", "", sent)) if len(w) > 3]
        if not ids or not words:
            continue
        pool = set().union(*(by_id[i] for i in ids))
        scores.append(sum(w in pool for w in words) / len(words))
    return round(mean(scores), 3) if scores else None


def run_evaluation(engine: Engine, with_answers: bool = True, provider: str | None = None) -> dict:
    retriever = get_retriever(engine, refresh=True)
    answerable = [i for i in EVAL_SET if i["doc"]]
    out = {"evaluated_at": datetime.now().isoformat(timespec="seconds"), "questions": len(EVAL_SET),
           "answerable": len(answerable), "chunks_indexed": retriever.size,
           "embedding_model": get_settings().embedding_model, "reranker": get_settings().reranker_model or None,
           "retrieval": {}}
    for mode, rr in MODES:
        if rr and retriever.reranker is None:
            continue
        out["retrieval"][f"{mode}{'+rerank' if rr else ''}"] = retrieval_metrics(retriever, answerable, mode, rr)

    resolved = resolve_provider(provider)
    out["answer_provider"] = resolved
    if with_answers and resolved != "extractive":
        per_q = []
        for it in EVAL_SET:
            r = answer_question(retriever, it["q"], provider=resolved)
            ans = r["answer"]
            refused = NOT_COVERED.lower().rstrip(".") in ans.lower()
            cited_rel = any(is_relevant_payload(s, it) for s in r["sources"] if s["id"] in r["cited"])
            per_q.append({
                "question": it["q"], "answerable": bool(it["doc"]), "answer": ans, "cited": r["cited"],
                "refused": refused, "latency_ms": r["latency_ms"],
                "fact_recall": (sum(f.lower() in ans.lower() for f in it["facts"]) / len(it["facts"])) if it["facts"] else None,
                "citation_valid": not any("invalid" in w for w in r["warnings"]),
                "cited_source_relevant": cited_rel if it["doc"] else None,
                "faithfulness": faithfulness_proxy(ans, r["sources"]) if it["doc"] else None,
            })
        ans_q = [p for p in per_q if p["answerable"]]
        out["answers"] = {
            "model": get_settings().ollama_model if resolved == "ollama" else resolved,
            "fact_recall": round(mean(p["fact_recall"] for p in ans_q), 3),
            "citation_validity": round(mean(p["citation_valid"] for p in per_q), 3),
            "cited_source_relevance": round(mean(bool(p["cited_source_relevant"]) for p in ans_q), 3),
            "faithfulness_proxy": round(mean(p["faithfulness"] for p in ans_q if p["faithfulness"] is not None), 3)
            if any(p["faithfulness"] is not None for p in ans_q) else None,
            "refusal_accuracy": round(mean(p["refused"] != p["answerable"] for p in per_q), 3),
            "median_latency_ms": sorted(p["latency_ms"] for p in per_q)[len(per_q) // 2],
            "per_question": per_q,
        }
    path = get_settings().models_dir / "rag"
    path.mkdir(parents=True, exist_ok=True)
    (path / "rag_evaluation_latest.json").write_text(json.dumps(out, indent=2, default=str))
    with Session(engine) as s:
        s.add(AuditLog(actor="system:rag", action="RAG_EVALUATED", entity_type="collection",
                       entity_id=get_settings().qdrant_collection,
                       details={k: v for k, v in out.items() if k != "answers"} |
                               {"answers": {k: v for k, v in out.get("answers", {}).items() if k != "per_question"}}))
        s.commit()
    return {k: v for k, v in out.items() if k != "answers"} | (
        {"answers": {k: v for k, v in out["answers"].items() if k != "per_question"}} if "answers" in out else {})


def is_relevant_payload(src: dict, item: dict) -> bool:
    return bool(item["doc"]) and src["doc_type"] == item["doc"] and item["section"] in (src["section"] or "").lower()
