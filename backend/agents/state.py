"""Shared workflow state and the per-run context every agent works through."""
from __future__ import annotations

import operator
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, TypedDict

from app.security import Actor
from tools.registry import call_tool


def merge_dicts(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


class InvestigationState(TypedDict, total=False):
    """LangGraph state. Reducers say how each agent's partial update is merged in."""
    investigation_id: int
    run_id: str
    customer_id: str
    request_text: str
    findings: Annotated[dict, merge_dicts]          # agent name -> that agent's structured findings
    evidence: Annotated[list, operator.add]         # every evidence item, in order (E1, E2, ...)
    errors: Annotated[list, operator.add]           # {"agent", "error"} for steps that failed after retries
    completed: Annotated[list, operator.add]        # agents that ran, in order
    halt: bool                                       # supervisor sets this when the request cannot proceed


@dataclass
class RunContext:
    """Per-run services handed to agents: identity, tool access, evidence numbering, tracing."""
    run_id: str
    investigation_id: int
    actor: Actor
    trace: Any
    step: int = 0
    next_ref: int = 1
    tool_log: list = field(default_factory=list)       # tool calls of the agent currently running
    new_evidence: list = field(default_factory=list)   # evidence created by the agent currently running
    llm_model: str | None = None

    def tool(self, name: str, **args) -> dict:
        """Call a registry tool as this run's actor and record it for the agent execution log."""
        t0 = time.time()
        try:
            out = call_tool(name, self.actor, args)
            self.tool_log.append({"tool": name, "args": args, "outcome": "ok", "ms": int((time.time() - t0) * 1000)})
            return out
        except Exception as e:
            self.tool_log.append({"tool": name, "args": args, "outcome": type(e).__name__, "error": str(e)[:300],
                                  "ms": int((time.time() - t0) * 1000)})
            raise

    def evidence(self, evidence_type: str, agent: str, title: str, details: dict | None = None,
                 source_table: str | None = None, source_id: Any = None, observed_at: Any = None,
                 ai_generated: bool = False) -> str:
        """Register an evidence item and return its reference (E1, E2, ...)."""
        ref = f"E{self.next_ref}"
        self.next_ref += 1
        if isinstance(observed_at, str):
            try:
                observed_at = datetime.fromisoformat(observed_at)
            except ValueError:
                observed_at = None
        self.new_evidence.append({"ref": ref, "evidence_type": evidence_type, "source_agent": agent, "title": title[:300],
                                  "details": details or {}, "source_table": source_table,
                                  "source_id": None if source_id is None else str(source_id),
                                  "observed_at": observed_at, "ai_generated": ai_generated})
        return ref


_RUNS: dict[str, RunContext] = {}


def register(ctx: RunContext) -> None:
    _RUNS[ctx.run_id] = ctx


def context(run_id: str) -> RunContext:
    return _RUNS[run_id]


def release(run_id: str) -> None:
    _RUNS.pop(run_id, None)
