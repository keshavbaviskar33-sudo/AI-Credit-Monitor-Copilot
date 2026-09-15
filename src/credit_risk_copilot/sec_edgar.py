"""Minimal rate-limited SEC EDGAR client with on-disk caching.

SEC EDGAR access rules (verified, docs/data_feasibility.md): at most 10
requests/second, and a descriptive `User-Agent` is required. This client
enforces `Settings.sec_max_requests_per_second` (default 8, below the limit)
and refuses to run without a configured User-Agent.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
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

#: Annual report forms. MVP assesses annual periods only (D-007). `10-K/A` is
#: an amendment to a 10-K and reports the same fiscal year, so it is kept and
#: distinguished by its own `filed` date rather than merged into the original.
ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "10-KSB", "10-K405"})


@dataclass(frozen=True)
class FilingRef:
    """One filing in a company's EDGAR history.

    `filed` is the date SEC received the filing and is what the point-in-time
    rule (D-008) filters on -- not `period`, the fiscal period it covers.
    """

    cik: int
    accession: str
    form: str
    filed: str
    period: str
    primary_document: str

    @property
    def accession_compact(self) -> str:
        """Accession number without dashes, as EDGAR's archive paths spell it."""
        return self.accession.replace("-", "")


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

    def _get(self, url: str, cache_path: Path | None) -> bytes:
        """Fetch `url`, serving from `cache_path` when it is already populated."""
        if cache_path is not None and cache_path.exists():
            return cache_path.read_bytes()

        self._throttle()
        response = self._session.get(url, timeout=self._timeout)
        response.raise_for_status()
        content = response.content

        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(content)
        return content

    def _get_json(self, url: str, cache_path: Path | None) -> Any:
        return json.loads(self._get(url, cache_path).decode("utf-8"))

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

    def submissions(self, cik: int) -> Any:
        """Company metadata and filing history (`submissions` API).

        Carries the name, SIC code and fiscal year end needed for scope
        filtering (FR-02, D-006), plus the filing index `annual_filings` reads.
        """
        padded = f"{cik:010d}"
        url = f"{_DATA_BASE}/submissions/CIK{padded}.json"
        cache_path = self.cache_dir / "submissions" / f"CIK{padded}.json"
        return self._get_json(url, cache_path)

    def _submission_pages(self, cik: int) -> list[Any]:
        """Every filing index for `cik`: the recent window plus its overflow files.

        `submissions` inlines only the most recent ~1000 filings under
        `filings.recent`; older history is split into separate JSON files
        listed in `filings.files`. Long-lived filers (including most of the
        distressed companies from the Phase 3 audit) spill past that window,
        so ignoring the overflow would silently truncate their 10-K history.
        """
        root = self.submissions(cik)
        filings = root.get("filings", {})
        pages = [filings.get("recent", {})]

        for overflow in filings.get("files", []):
            name = overflow.get("name")
            if not name:
                continue
            url = f"{_DATA_BASE}/submissions/{name}"
            pages.append(self._get_json(url, self.cache_dir / "submissions" / name))
        return pages

    def annual_filings(self, cik: int) -> list[FilingRef]:
        """Annual-report filings for `cik`, oldest first.

        Restricted to `ANNUAL_FORMS` (D-007). Filings without a primary
        document are dropped -- there is no document to extract from.
        """
        refs: list[FilingRef] = []
        for page in self._submission_pages(cik):
            forms = page.get("form", [])
            for i, form in enumerate(forms):
                if form not in ANNUAL_FORMS:
                    continue
                primary_document = page.get("primaryDocument", [])[i]
                if not primary_document:
                    continue
                refs.append(
                    FilingRef(
                        cik=cik,
                        accession=page.get("accessionNumber", [])[i],
                        form=form,
                        filed=page.get("filingDate", [])[i],
                        period=page.get("reportDate", [])[i],
                        primary_document=primary_document,
                    )
                )
        return sorted(refs, key=lambda ref: (ref.filed, ref.accession))

    def filing_document(self, filing: FilingRef) -> bytes:
        """The raw bytes of a filing's primary document (10-K HTML)."""
        url = (
            f"{_WWW_BASE}/Archives/edgar/data/{filing.cik}"
            f"/{filing.accession_compact}/{filing.primary_document}"
        )
        cache_path = self.cache_dir / "filings" / filing.accession_compact / filing.primary_document
        return self._get(url, cache_path)
