"""Logging setup.

Call `configure_logging()` once at process start (CLI entrypoint, Streamlit
app, or test session). Level and format are controlled by `Settings.log_level`
/ `Settings.log_format` (env vars `LOG_LEVEL`, `LOG_FORMAT`).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from credit_risk_copilot.config import get_settings

_RESERVED_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)


class JsonFormatter(logging.Formatter):
    """Minimal structured formatter: one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_ATTRS
        }
        if extras:
            payload.update(extras)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_TEXT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False


def configure_logging() -> None:
    """Configure the root logger. Safe to call more than once; no-op after the first call."""
    global _configured
    if _configured:
        return

    settings = get_settings()
    handler = logging.StreamHandler()
    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_format == "json" else logging.Formatter(_TEXT_FORMAT)
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers = [handler]

    _configured = True
