from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import accounts, alerts, compliance, customers, graph, system, transactions
from app.config import get_settings

DESCRIPTION = """
FinGuard AI - Phase 1: financial data intelligence and ML detection.
Phase 2: graph intelligence (money-flow networks, cycles, layering chains) and a
compliance knowledge assistant (hybrid RAG with citations).

All data is synthetic. Scores, bands and alerts are **investigative indicators**, never
determinations of fraud. Alerts are read-only in Phase 1; case management and approvals
arrive in Phase 3, authentication/RBAC in Phase 4.
"""


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="0.2.0-phase2", description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["*"])
    for r in (system.router, customers.router, accounts.router, transactions.router, alerts.router, graph.router,
              compliance.router):
        app.include_router(r)
    return app


app = create_app()
