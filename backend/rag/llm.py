"""LLM providers behind one interface: Claude (Anthropic), OpenAI, local Ollama.

`auto` picks the first available: Anthropic key -> OpenAI key -> running Ollama ->
none (the caller then falls back to an extractive, quote-only answer).
"""
from __future__ import annotations

import json
import re

import httpx

from app.config import get_settings

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


# Structured output: generation is constrained to this JSON schema from the first token, so a
# reasoning-style model cannot "think out loud" in the answer (observed with qwen3:4b, which ignores
# think=false and /no_think and otherwise returns its reasoning transcript instead of an answer).
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


class LLMUnavailable(RuntimeError):
    pass


def parse_structured_answer(content: str) -> str:
    """Extract the "answer" field from a JSON response; fall back to the raw text if it is not JSON."""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("answer"), str):
            return data["answer"].strip()
    except json.JSONDecodeError:
        pass
    return content.strip()


def _ollama_up(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/tags", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        return False


def resolve_provider(requested: str | None = None) -> str:
    s = get_settings()
    p = (requested or s.llm_provider or "auto").lower()
    if p != "auto":
        return p
    if s.anthropic_api_key:
        return "anthropic"
    if s.openai_api_key:
        return "openai"
    if _ollama_up(s.ollama_url):
        return "ollama"
    return "extractive"


def provider_status() -> dict:
    s = get_settings()
    return {"configured": s.llm_provider, "resolved": resolve_provider(),
            "anthropic": bool(s.anthropic_api_key), "openai": bool(s.openai_api_key),
            "ollama": _ollama_up(s.ollama_url), "ollama_model": s.ollama_model}


def complete(system: str, user: str, provider: str) -> tuple[str, str]:
    """Return (text, model_name). Temperature is kept low: this is grounded Q&A, not creative writing."""
    s = get_settings()
    if provider == "anthropic":
        if not s.anthropic_api_key:
            raise LLMUnavailable("ANTHROPIC_API_KEY not set")
        import anthropic

        client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds)
        msg = client.messages.create(model=s.anthropic_model, max_tokens=s.llm_max_tokens, temperature=0.1, system=system,
                                     messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if b.type == "text"), s.anthropic_model
    if provider == "openai":
        if not s.openai_api_key:
            raise LLMUnavailable("OPENAI_API_KEY not set")
        r = httpx.post("https://api.openai.com/v1/chat/completions", timeout=s.llm_timeout_seconds,
                       headers={"Authorization": f"Bearer {s.openai_api_key}"},
                       json={"model": s.openai_model, "temperature": 0.1, "max_tokens": s.llm_max_tokens,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"], s.openai_model
    if provider == "ollama":
        try:
            r = httpx.post(f"{s.ollama_url}/api/chat", timeout=s.llm_timeout_seconds,
                           json={"model": s.ollama_model, "stream": False, "think": False, "format": ANSWER_SCHEMA,
                                 "options": {"temperature": 0.1, "num_ctx": s.ollama_num_ctx, "num_predict": s.llm_max_tokens},
                                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Ollama call failed: {e}") from e
        return parse_structured_answer(THINK_RE.sub("", r.json()["message"]["content"])), s.ollama_model
    raise LLMUnavailable(f"Unknown provider {provider}")
