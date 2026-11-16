import logging
import time

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (accounts, alerts, auth, compliance, customers, governance, graph, investigations, system,
                             transactions)
from app.config import get_settings
from app.observability import HTTP_LATENCY, HTTP_REQUESTS, metrics_payload
from app.security import require

DESCRIPTION = """
FinGuard AI - financial crime detection, investigation and compliance intelligence.

* Phase 1: transaction intelligence and ML detection
* Phase 2: graph intelligence and a compliance knowledge assistant (hybrid RAG with citations)
* Phase 3: multi-agent investigations (LangGraph), MCP tools, evidence and case management
* Phase 4: authentication, role-based access, audit, observability

All data is synthetic. Scores, patterns and AI findings are **investigative indicators**, never
determinations of wrongdoing. Every case ends with a human decision.

**Authentication:** `POST /api/v1/auth/login` (form fields `username`, `password`) returns a bearer
token; click *Authorize* above to use it in these docs.
"""


def create_app() -> FastAPI:
    s = get_settings()
    if s.jwt_secret == "dev-only-change-me":
        logging.getLogger("finguard").warning("JWT_SECRET is the development default - set a random value in .env")
    app = FastAPI(title=s.app_name, version="0.4.0-phase4", description=DESCRIPTION)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["*"])

    @app.middleware("http")
    async def metrics_mw(request: Request, call_next):
        t0 = time.time()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")          # template path keeps label cardinality low
        if path != "/metrics":
            HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(time.time() - t0)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        body, ctype = metrics_payload()
        return Response(body, media_type=ctype)

    customer_data = [Depends(require("view_customers"))]
    app.include_router(system.router)            # per-endpoint permissions inside; /health is public
    app.include_router(auth.router)
    app.include_router(customers.router, dependencies=customer_data)
    app.include_router(accounts.router, dependencies=customer_data)
    app.include_router(transactions.router, dependencies=customer_data)
    app.include_router(alerts.router, dependencies=customer_data)
    app.include_router(graph.router, dependencies=customer_data)
    app.include_router(compliance.router, dependencies=[Depends(require("ask_compliance"))])
    app.include_router(investigations.router)    # per-endpoint permissions inside
    app.include_router(governance.router)
    return app


app = create_app()
