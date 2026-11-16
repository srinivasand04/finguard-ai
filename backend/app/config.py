from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    app_name: str = "FinGuard AI"
    database_url: str = "postgresql+psycopg://finguard:finguard_dev@localhost:55432/finguard"
    redis_url: str = "redis://localhost:6380/0"
    models_dir: Path = ROOT_DIR / "models"
    data_dir: Path = ROOT_DIR / "data"
    risk_config_path: Path = BACKEND_DIR / "config" / "risk_config.json"
    cache_ttl_seconds: int = 60

    # --- Phase 2: compliance RAG ---
    documents_dir: Path = ROOT_DIR / "documents"
    qdrant_url: str = "http://localhost:6333"          # ":memory:" for an in-process store (tests)
    qdrant_collection: str = "compliance_chunks"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"   # "hashing" = offline test embedder
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"      # "" disables reranking
    # LLM provider: auto | anthropic | openai | ollama | extractive (no LLM, quotes sources)
    llm_provider: str = "auto"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    ollama_url: str = "http://127.0.0.1:11434"      # 127.0.0.1, not localhost: on Windows localhost tries IPv6 first
    ollama_model: str = "qwen3:4b"
    ollama_num_ctx: int = 4096      # 5 passages + question fit in ~1.5k tokens; smaller context = less RAM
    llm_max_tokens: int = 300       # answers are capped at ~6 sentences anyway; bounds latency on CPU
    llm_timeout_seconds: float = 120.0
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Phase 4: security ---
    jwt_secret: str = "dev-only-change-me"          # override with JWT_SECRET in .env for anything shared
    jwt_expire_minutes: int = 480
    demo_user_password: str = ""                    # used only by `app.cli seed-users`

    # --- Phase 3: agents / MCP ---
    agent_use_llm: bool = True                      # narrative synthesis by LLM; deterministic template otherwise
    agent_max_retries: int = 2
    agent_llm_timeout_seconds: float = 240.0       # narrative prompts are long; local CPU models need time
    mcp_actor_username: str = "mcp-service"         # identity the MCP server acts as
    mcp_actor_role: str = "FRAUD_ANALYST"
    mcp_read_only: bool = True                      # MCP write tools are disabled unless explicitly enabled

    # --- Phase 4: observability (Langfuse is optional - enabled only when keys are set) ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # relative paths in .env are resolved against the backend folder
    if not s.models_dir.is_absolute():
        s.models_dir = (BACKEND_DIR / s.models_dir).resolve()
    if not s.data_dir.is_absolute():
        s.data_dir = (BACKEND_DIR / s.data_dir).resolve()
    return s
