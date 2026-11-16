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
    python -m app.cli seed-users [--reset-passwords]   # Phase 4: one demo user per role (DEMO_USER_PASSWORD)
    python -m app.cli create-user --username U --role ROLE [--full-name N]   (password prompted)
    python -m app.cli investigate --customer CUST10025 [--username U]       # Phase 3: run the agents from CLI
    python -m app.cli agent-eval [--n 12] [--llm]                            # Phase 3: agent workflow evaluation
    python -m app.cli all          # init-db --drop, generate, ingest, eda, train, score, graph, risk, alerts,
                                   # rag-build, seed-users
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
    su = sub.add_parser("seed-users")
    su.add_argument("--reset-passwords", action="store_true",
                    help="also set DEMO_USER_PASSWORD on demo accounts that already exist")
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--role", required=True)
    cu.add_argument("--full-name", default=None)
    iv = sub.add_parser("investigate")
    iv.add_argument("--customer", required=True)
    iv.add_argument("--request", default=None)
    iv.add_argument("--username", default="fraud_analyst", help="analyst account the case is attributed to")
    ae = sub.add_parser("agent-eval")
    ae.add_argument("--n", type=int, default=12)
    ae.add_argument("--llm", action="store_true", help="use the LLM for narratives (slower)")
    a = p.parse_args()
    engine = get_engine()
    steps = (["init-db", "generate", "ingest", "eda", "train", "score", "graph", "risk", "alerts", "rag-build",
              "seed-users"] if a.cmd == "all" else [a.cmd])
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
        elif step == "seed-users":
            from app.services.users import seed_demo_users
            _print("seed-users", seed_demo_users(engine, reset_passwords=getattr(a, "reset_passwords", False)), t0)
        elif step == "create-user":
            import getpass

            from app.services.users import create_user
            pw = getpass.getpass(f"Password for {a.username}: ")
            _print("create-user", create_user(engine, a.username, a.role, pw, a.full_name), t0)
        elif step == "investigate":
            from sqlalchemy.orm import Session

            from agents.runner import run_investigation
            from app.models import User
            from app.security import Actor
            from app.services import cases
            with Session(engine) as session:
                u = session.query(User).filter(User.username == a.username).one_or_none()
                if u is None:
                    raise SystemExit(f"User {a.username} not found - run `python -m app.cli seed-users` first")
                actor = Actor(u.username, u.role)
                inv = cases.create_case(session, actor, a.request or f"Investigate suspicious transactions involving customer {a.customer}", a.customer)
                inv_id, ref = inv.id, inv.case_ref
            print(f"Case {ref} (id {inv_id}) created - running agents...")
            _print("investigate", run_investigation(inv_id, actor), t0)
        elif step == "agent-eval":
            from agents.evaluation import run_agent_evaluation
            out = run_agent_evaluation(n=a.n, use_llm=a.llm)
            _print("agent-eval", {k: v for k, v in out.items() if k != "cases"}, t0)
        elif step == "risk":
            from app.services.risk_scoring import run_customer_risk
            _print("risk", run_customer_risk(engine), t0)
        elif step == "alerts":
            from app.services.alerting import generate_alerts
            _print("alerts", generate_alerts(engine), t0)


if __name__ == "__main__":
    main()
