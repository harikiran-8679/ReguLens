"""Application configuration loaded from environment / .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = (
        "postgresql+psycopg://lm_app:lm_secret_dev@localhost:5433/lm_inspection"
    )

    # Auth
    JWT_SECRET: str = "dev-only-change-me-please-0123456789abcdef"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # AI pipeline selection. PaddleOCR is the PRIMARY engine; Tesseract is the
    # fallback (see services/ocr.run_ocr_with_fallback). 'demo' runs the simulated
    # primary, labelled "PaddleOCR (simulated)" in the UI.
    OCR_ENGINE: str = "paddle"        # paddle (primary) | tesseract | demo
    FIELD_MATCHER: str = "demo"       # demo (deterministic) | ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b"
    LLM_TIMEOUT_SECONDS: float = 20.0

    # Storage
    STORAGE_DIR: Path = BACKEND_DIR / "data" / "storage"
    UPLOAD_MAX_MB: int = 15

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Demo bootstrap
    SEED_DEMO_DATA: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def storage_dir(self) -> Path:
        p = self.STORAGE_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
