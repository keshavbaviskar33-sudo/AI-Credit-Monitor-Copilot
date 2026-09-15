"""Application configuration, loaded from environment variables and `.env`.

See `.env.example` for the full list of settings and their defaults.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["text", "json"] = "text"

    # SEC EDGAR requires a descriptive User-Agent identifying the requester
    # (data_feasibility.md §3.3) and enforces <=10 requests/second per caller.
    sec_user_agent: str = Field(
        default="",
        description="Required by SEC EDGAR, e.g. 'Company Name contact@example.com'.",
    )
    sec_request_timeout_seconds: float = 10.0
    sec_max_requests_per_second: float = 8.0

    # Phase 4: ceiling on analyst-uploaded documents (FR-04). 25 MB comfortably
    # holds a full annual report PDF while bounding what a parser is handed.
    max_upload_bytes: int = 25 * 1024 * 1024

    # Phase 13/15: append-only SQLite persistence. Not yet used.
    database_url: str = "sqlite:///./data/credit_risk_copilot.db"

    # Phase 12: single grounded synthesis call. Not yet used.
    llm_provider: str = ""
    llm_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings, loaded once per process."""
    return Settings()
