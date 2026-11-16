"""Test fixtures: a small synthetic dataset run through the full pipeline into a throwaway SQLite DB.

No Docker needed for the test suite - SQLite stands in for Postgres, Redis is disabled and
Qdrant runs in-process.
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cache  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import set_engine, init_db  # noqa: E402


@pytest.fixture(scope="session")
def pipeline(tmp_path_factory):
    from app.services.alerting import generate_alerts
    from app.services.ingestion import run_ingestion
    from app.services.risk_scoring import run_customer_risk
    from data_gen.amlsim_synth import GenConfig, Generator
    from ml.scoring import score_all
    from ml.train import train_all
    from graph.pipeline import run_graph_analysis
    from rag.pipeline import build_index

    tmp = tmp_path_factory.mktemp("finguard")
    cache.disable_for_tests()
    settings = get_settings()
    settings.models_dir = tmp / "models"
    settings.data_dir = tmp / "data"
    # Phase 2: offline RAG stack - in-memory Qdrant, hashing embedder, no reranker, no LLM
    settings.documents_dir = tmp / "documents"
    settings.qdrant_url = ":memory:"
    settings.embedding_model = "hashing"
    settings.reranker_model = ""
    settings.llm_provider = "extractive"
    engine = create_engine(f"sqlite:///{tmp / 'test.db'}")
    set_engine(engine)
    init_db()

    raw = tmp / "data" / "raw" / "amlsim"
    gen = Generator(GenConfig(customers=250, days=120, alerts=48, seed=7)).run(raw)
    results = {"generation": gen}
    results["ingest"] = run_ingestion(raw, engine, tmp / "data" / "processed")
    results["train"] = train_all(engine)
    results["score"] = score_all(engine)
    results["graph"] = run_graph_analysis(engine)
    results["risk"] = run_customer_risk(engine)
    results["alerts"] = generate_alerts(engine)
    results["rag"] = build_index(engine)
    results["engine"] = engine
    _create_test_users(engine)
    return results


# Phase 4: one throwaway test account per role (test-only password, never used outside this suite)
TEST_PASSWORD = "Test-Only-Passw0rd"
TEST_USERS = {"FRAUD_ANALYST": "t.fraud", "AML_ANALYST": "t.aml", "COMPLIANCE_OFFICER": "t.compliance",
              "INVESTIGATION_MANAGER": "t.manager", "OPERATIONS_MANAGER": "t.ops", "ADMIN": "t.admin"}


def _create_test_users(engine):
    from sqlalchemy.orm import Session

    from app.models import User
    from app.security import hash_password

    with Session(engine) as s:
        for role, username in TEST_USERS.items():
            s.add(User(username=username, full_name=f"Test {role}", role=role, password_hash=hash_password(TEST_PASSWORD)))
        s.commit()


def auth_headers(client, role: str) -> dict:
    r = client.post("/api/v1/auth/login", data={"username": TEST_USERS[role], "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def client(pipeline):
    """Default client is logged in as ADMIN, so the Phase 1-2 tests run behind authentication unchanged."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.headers.update(auth_headers(c, "ADMIN"))
        yield c


@pytest.fixture(scope="session")
def as_role(client):
    """as_role("FRAUD_ANALYST") -> auth headers for that role (cached)."""
    cache: dict[str, dict] = {}

    def get(role: str) -> dict:
        if role not in cache:
            cache[role] = auth_headers(client, role)
        return cache[role]
    return get
