"""Observability: Prometheus metrics + optional Langfuse tracing.

Prometheus (always on) - scraped from GET /metrics:
  finguard_http_requests_total / _duration_seconds   per route + status
  finguard_tool_calls_total                          per tool + outcome (ok / denied / error)
  finguard_agent_steps_total / _step_seconds         per agent + status
  finguard_investigations_total                      per final status
  finguard_llm_requests_total / _latency_seconds     per provider + purpose + outcome

Langfuse (only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set): one trace per
investigation run, one span per agent, one generation per LLM call. Without keys every
call is a no-op, so nothing else in the code has to care.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import lru_cache

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config import get_settings

log = logging.getLogger(__name__)

HTTP_REQUESTS = Counter("finguard_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("finguard_http_request_duration_seconds", "HTTP latency", ["method", "route"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
TOOL_CALLS = Counter("finguard_tool_calls_total", "Agent/MCP tool calls", ["tool", "outcome"])
AGENT_STEPS = Counter("finguard_agent_steps_total", "Agent steps", ["agent", "status"])
AGENT_LATENCY = Histogram("finguard_agent_step_seconds", "Agent step duration", ["agent"],
                          buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120))
INVESTIGATIONS = Counter("finguard_investigations_total", "Investigation runs finished", ["status"])
LLM_REQUESTS = Counter("finguard_llm_requests_total", "LLM requests", ["provider", "purpose", "outcome"])
LLM_LATENCY = Histogram("finguard_llm_latency_seconds", "LLM latency", ["provider", "purpose"],
                        buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160))


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


@contextmanager
def track_llm(provider: str, purpose: str):
    t0 = time.time()
    try:
        yield
        LLM_REQUESTS.labels(provider, purpose, "ok").inc()
    except Exception:
        LLM_REQUESTS.labels(provider, purpose, "error").inc()
        raise
    finally:
        LLM_LATENCY.labels(provider, purpose).observe(time.time() - t0)


# --------------------------------------------------------------------------- Langfuse (optional)
class _NoOp:
    """Stands in for a Langfuse trace/span when tracing is disabled."""

    def span(self, **_):
        return self

    def generation(self, **_):
        return self

    def end(self, **_):
        return None

    def update(self, **_):
        return None


@lru_cache
def _langfuse():
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(public_key=s.langfuse_public_key, secret_key=s.langfuse_secret_key, host=s.langfuse_host)
    except Exception as e:  # never let tracing break the product
        log.warning("Langfuse disabled: %s", e)
        return None


def langfuse_enabled() -> bool:
    return _langfuse() is not None


def start_trace(name: str, **kw):
    lf = _langfuse()
    if lf is None:
        return _NoOp()
    try:
        return lf.trace(name=name, **kw)
    except Exception as e:
        log.warning("Langfuse trace failed: %s", e)
        return _NoOp()


def flush() -> None:
    lf = _langfuse()
    if lf is not None:
        try:
            lf.flush()
        except Exception as e:
            log.warning("Langfuse flush failed: %s", e)
