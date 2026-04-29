# ─────────────────────────────────────────────────────
# Module   : app/core/config.py
# Layer    : Infrastructure
# Pillar   : P0 (Bootstrap), P2 (Security), P5 (Scalability)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Centralized configuration management via pydantic-settings.
    All values are loaded from environment variables or .env file.
    """
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Discord ────────────────────────────────────────────────────
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_WATCH_CHANNEL_ID: Optional[str] = None

    # ── FastAPI ────────────────────────────────────────────────────
    API_BASE_URL: str = "http://localhost:8000"
    API_SECRET_KEY: str = ""
    MAX_CONCURRENT_EXTRACTIONS: int = 5
    MAX_IMAGE_SIZE_BYTES: int = 5242880  # 5 MB

    # ── LLM Providers ──────────────────────────────────────────────
    DEFAULT_PROVIDER: str = "openai"
    DEFAULT_MODEL: str = "gpt-4o"

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_DEFAULT_MODEL: str = "gpt-4o"

    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_DEFAULT_MODEL: str = "claude-opus-4-20250514"

    GOOGLE_GEMINI_API_KEY: Optional[str] = None
    GEMINI_DEFAULT_MODEL: str = "gemini-2.0-flash"

    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_DEFAULT_MODEL: str = "llava:13b"
    OLLAMA_TIMEOUT_SECONDS: int = 120

    # ── Google Sheets ──────────────────────────────────────────────
    GOOGLE_SERVICE_ACCOUNT_B64: Optional[str] = None
    GOOGLE_SPREADSHEET_ID: Optional[str] = None
    SHEET_CACHE_TTL_SECONDS: int = 300

    # ── OCR ────────────────────────────────────────────────────────
    DEFAULT_OCR_ENGINE: Literal["none", "local", "local_high"] = "none"

    # ── Observability ──────────────────────────────────────────────
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARN", "ERROR"] = "INFO"
    ENABLE_PROMETHEUS: bool = True

    @property
    def is_production(self) -> bool:
        return self.LOG_LEVEL != "DEBUG"

settings = Settings()