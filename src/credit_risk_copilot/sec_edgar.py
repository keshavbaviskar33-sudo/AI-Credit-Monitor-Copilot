"""Minimal rate-limited SEC EDGAR client with on-disk JSON caching.

SEC EDGAR access rules (verified, docs/data_feasibility.md): at most 10
requests/second, and a descriptive `User-Agent` is required. This client
enforces `Settings.sec_max_requests_per_second` (default 8, below the limit)
and refuses to run without a configured User-Agent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
import truststore

from credit_risk_copilot.config import get_settings

# Some environments (e.g. antivirus TLS interception) present certificates
# that aren't in the certifi bundle `requests` uses by default, even though
# they're trusted by the OS. Verify against the OS trust store instead.
truststore.inject_into_ssl()

_DATA_BASE = "https://data.sec.gov"
_WWW_BASE = "https://www.sec.gov"


class SecEdgarClient:
    def __init__(self, cache_dir: Path | str = "data/raw") -> None:
        settings = get_settings()
        if not settings.sec_user_agent:
            raise ValueError(
                "SEC_USER_AGENT must be set (see .env.example) before calling SEC EDGAR."
            )
        self._timeout = settings.sec_request_timeout_seconds
        self._min_interval = 1.0 / settings.sec_max_requests_per_second
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers["User-Agent"] = settings.sec_user_agent
        self.cache_dir = Path(cache_dir)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def _get_json(self, url: str, cache_path: Path | None) -> Any:
        if cache_path is not None and cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        self._throttle()
        response = self._session.get(url, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()

        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def company_facts(self, cik: int) -> Any:
        """All XBRL facts SEC has for one filer (`companyfacts` API)."""
        padded = f"{cik:010d}"
        url = f"{_DATA_BASE}/api/xbrl/companyfacts/CIK{padded}.json"
        cache_path = self.cache_dir / "companyfacts" / f"CIK{padded}.json"
        return self._get_json(url, cache_path)

    def company_tickers(self) -> Any:
        """The full list of SEC filers that have a ticker."""
        url = f"{_WWW_BASE}/files/company_tickers.json"
        cache_path = self.cache_dir / "company_tickers.json"
        return self._get_json(url, cache_path)
