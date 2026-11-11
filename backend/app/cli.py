"""FinGuard pipeline CLI.

    python -m app.cli init-db [--drop]
    python -m app.cli generate [--customers N --days D]
    python -m app.cli ingest [--source DIR]
    python -m app.cli eda
    python -m app.cli train
    python -m app.cli score
    python -m app.cli graph        # Phase 2: graph intelligence
    python -m app.cli risk
    python -m app.cli alerts
    python -m app.cli rag-build    # Phase 2: compliance corpus -> chunks -> embeddings -> Qdrant
    python -m app.cli rag-eval     # Phase 2: retrieval + answer evaluation
    python -m app.cli all          # init-db --drop, generate, ingest, eda, train, score, graph, risk, alerts, rag-build
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from app.config import get_settings
from app.db import get_engine, init_db


def _print(title: str, payload: dict, t0: float) -> None:
    print(f"\n=== {title} ({time.time() - t0:.1f}s) ===")
    print(json.dumps(payload, indent=2, default=str))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = get_settings()
    p = argparse.ArgumentParser(prog="finguard")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("init-db"); d.add_argument("--drop", action="store_true")
    g = sub.add_parser("generate"); g.add_argument("--customers", type=int, default=1500); g.add_argument("--days", type=int, default=180)
    i = sub.add_parser("ingest"); i.add_argument("--source", default=str(s.data_dir / "raw" / "amlsim"))
    for name in ["eda", "train", "score", "graph", "risk", "alerts", "rag-build", "rag-eval", "all"]:
        sub.add_parser(name)
    a = p.parse_args()
    engine = get_engine()
    steps = ["init-db", "generate", "ingest", "eda", "train", "score", "graph", "risk", "alerts", "rag-build"] if a.cmd == "all" else [a.cmd]
    source = Path(getattr(a, "source", s.data_dir / "raw" / "amlsim"))

    for step in steps:
        t0 = time.time()
        if step == "init-db":
            init_db(drop=getattr(a, "drop", False) or a.cmd == "all")
            _print("init-db", {"tables": "created"}, t0)
        elif step == "generate":
            from data_gen.amlsim_synth import GenConfig, Generator
            cfg = GenConfig(customers=getattr(a, "customers", 1500), days=getattr(a, "days", 180))
            _print("generate", Generator(cfg).run(s.data_dir / "raw" / "amlsim"), t0)
        elif step == "ingest":
            from app.services.ingestion import run_ingestion
            _print("ingest", run_ingestion(source, engine, s.data_dir / "processed"), t0)
        elif step == "eda":
            from ml.eda import run_eda
            _print("eda", run_eda(engine, Path(__file__).resolve().parents[2] / "docs"), t0)
        elif step == "train":
            from ml.train import train_all
            _print("train", train_all(engine), t0)
        elif step == "score":
            from ml.scoring import score_all
            _print("score", score_all(engine), t0)
        elif step == "graph":
            from graph.pipeline import run_graph_analysis
            _print("graph", run_graph_analysis(engine), t0)
        elif step == "rag-build":
            from rag.pipeline import build_index
            _print("rag-build", build_index(engine), t0)
        elif step == "rag-eval":
            from rag.evaluation import run_evaluation
            _print("rag-eval", run_evaluation(engine), t0)
        elif step == "risk":
            from app.services.risk_scoring import run_customer_risk
            _print("risk", run_customer_risk(engine), t0)
        elif step == "alerts":
            from app.services.alerting import generate_alerts
            _print("alerts", generate_alerts(engine), t0)


if __name__ == "__main__":
    main()
