"""Test fixtures: a small synthetic dataset run through the full pipeline into a throwaway SQLite DB.

No Docker needed for the test suite - SQLite stands in for Postgres and Redis is disabled.
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

    tmp = tmp_path_factory.mktemp("finguard")
    cache.disable_for_tests()
    settings = get_settings()
    settings.models_dir = tmp / "models"
    settings.data_dir = tmp / "data"
    engine = create_engine(f"sqlite:///{tmp / 'test.db'}")
    set_engine(engine)
    init_db()

    raw = tmp / "data" / "raw" / "amlsim"
    gen = Generator(GenConfig(customers=250, days=90, alerts=40, seed=7)).run(raw)
    results = {"generation": gen}
    results["ingest"] = run_ingestion(raw, engine, tmp / "data" / "processed")
    results["train"] = train_all(engine)
    results["score"] = score_all(engine)
    results["risk"] = run_customer_risk(engine)
    results["alerts"] = generate_alerts(engine)
    results["engine"] = engine
    return results


@pytest.fixture(scope="session")
def client(pipeline):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
