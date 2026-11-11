from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import accounts, alerts, customers, system, transactions
from app.config import get_settings

DESCRIPTION = """
FinGuard AI - Phase 1: financial data intelligence and ML detection.

All data is synthetic. Scores, bands and alerts are **investigative indicators**, never
determinations of fraud. Alerts are read-only in Phase 1; case management and approvals
arrive in Phase 3, authentication/RBAC in Phase 4.
"""


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="0.1.0-phase1", description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["*"])
    for r in (system.router, customers.router, accounts.router, transactions.router, alerts.router):
        app.include_router(r)
    return app


app = create_app()
