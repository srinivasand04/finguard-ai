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
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # relative paths in .env are resolved against the backend folder
    if not s.models_dir.is_absolute():
        s.models_dir = (BACKEND_DIR / s.models_dir).resolve()
    if not s.data_dir.is_absolute():
        s.data_dir = (BACKEND_DIR / s.data_dir).resolve()
    return s
