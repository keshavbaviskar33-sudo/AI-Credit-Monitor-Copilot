import json
from dataclasses import dataclass

import pytest

import credit_risk_copilot.sec_edgar as sec_edgar_module
from credit_risk_copilot.sec_edgar import FilingRef, SecEdgarClient


@dataclass
class _FakeSettings:
    sec_user_agent: str
    sec_request_timeout_seconds: float = 10.0
    sec_max_requests_per_second: float = 8.0
    max_upload_bytes: int = 25 * 1024 * 1024


def _patch_settings(monkeypatch, **overrides) -> None:
    defaults = {"sec_user_agent": "Test Suite test@example.com"}
    defaults.update(overrides)
    fake = _FakeSettings(**defaults)
    monkeypatch.setattr(sec_edgar_module, "get_settings", lambda: fake)


def test_requires_user_agent(monkeypatch, tmp_path) -> None:
    _patch_settings(monkeypatch, sec_user_agent="")

    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        SecEdgarClient(cache_dir=tmp_path)


def test_company_facts_uses_cache_without_network(monkeypatch, tmp_path) -> None:
    _patch_settings(monkeypatch)
    client = SecEdgarClient(cache_dir=tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not hit the network when the cache is warm")

    monkeypatch.setattr(client._session, "get", fail_if_called)

    cache_path = tmp_path / "companyfacts" / "CIK0000320193.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps({"entityName": "Apple Inc."}), encoding="utf-8")

    result = client.company_facts(320193)

    assert result["entityName"] == "Apple Inc."


def test_throttle_enforces_minimum_interval(monkeypatch, tmp_path) -> None:
    _patch_settings(monkeypatch, sec_max_requests_per_second=5)

    client = SecEdgarClient(cache_dir=tmp_path)

    assert client._min_interval == pytest.approx(0.2)


# --- Filing history (Phase 4) ---------------------------------------------


def _filing_page(*rows: tuple[str, str, str, str, str]) -> dict[str, list[str]]:
    """Build a submissions-style column-oriented filing index."""
    keys = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument")
    return {key: [row[i] for row in rows] for i, key in enumerate(keys)}


def _seed(client: SecEdgarClient, relative: str, payload: object) -> None:
    path = client.cache_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _offline_client(monkeypatch, tmp_path) -> SecEdgarClient:
    _patch_settings(monkeypatch)
    client = SecEdgarClient(cache_dir=tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not hit the network when the cache is warm")

    monkeypatch.setattr(client._session, "get", fail_if_called)
    return client


def test_annual_filings_keeps_only_annual_forms(monkeypatch, tmp_path) -> None:
    """MVP assesses annual periods only (D-007)."""
    client = _offline_client(monkeypatch, tmp_path)
    _seed(
        client,
        "submissions/CIK0000000123.json",
        {
            "name": "Test Corp",
            "filings": {
                "recent": _filing_page(
                    ("0000000123-23-000001", "10-K", "2023-02-01", "2022-12-31", "a.htm"),
                    ("0000000123-23-000002", "10-Q", "2023-05-01", "2023-03-31", "b.htm"),
                    ("0000000123-23-000003", "8-K", "2023-06-01", "2023-06-01", "c.htm"),
                )
            },
        },
    )

    filings = client.annual_filings(123)

    assert [f.form for f in filings] == ["10-K"]
    assert filings[0].accession == "0000000123-23-000001"
    assert filings[0].filed == "2023-02-01"
    assert filings[0].period == "2022-12-31"


def test_annual_filings_follows_the_overflow_files(monkeypatch, tmp_path) -> None:
    """`filings.recent` holds only ~1000 filings; older history lives in
    `filings.files`. Long-lived filers would otherwise lose their early 10-Ks."""
    client = _offline_client(monkeypatch, tmp_path)
    _seed(
        client,
        "submissions/CIK0000000123.json",
        {
            "filings": {
                "recent": _filing_page(
                    ("0000000123-23-000001", "10-K", "2023-02-01", "2022-12-31", "new.htm")
                ),
                "files": [{"name": "CIK0000000123-submissions-001.json"}],
            }
        },
    )
    _seed(
        client,
        "submissions/CIK0000000123-submissions-001.json",
        _filing_page(("0000000123-11-000001", "10-K", "2011-02-01", "2010-12-31", "old.htm")),
    )

    filings = client.annual_filings(123)

    assert [f.filed for f in filings] == ["2011-02-01", "2023-02-01"], "oldest first"


def test_annual_filings_drops_entries_with_no_primary_document(monkeypatch, tmp_path) -> None:
    client = _offline_client(monkeypatch, tmp_path)
    _seed(
        client,
        "submissions/CIK0000000123.json",
        {
            "filings": {
                "recent": _filing_page(
                    ("0000000123-23-000001", "10-K", "2023-02-01", "2022-12-31", ""),
                    ("0000000123-23-000002", "10-K", "2023-03-01", "2022-12-31", "ok.htm"),
                )
            }
        },
    )

    filings = client.annual_filings(123)

    assert [f.primary_document for f in filings] == ["ok.htm"]


def test_filing_document_is_cached_by_accession(monkeypatch, tmp_path) -> None:
    client = _offline_client(monkeypatch, tmp_path)
    filing = FilingRef(
        cik=123,
        accession="0000000123-23-000001",
        form="10-K",
        filed="2023-02-01",
        period="2022-12-31",
        primary_document="a.htm",
    )
    cache_path = tmp_path / "filings" / "000000012323000001" / "a.htm"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"<html><body>10-K</body></html>")

    assert client.filing_document(filing) == b"<html><body>10-K</body></html>"


def test_accession_compact_strips_dashes() -> None:
    filing = FilingRef(
        cik=123,
        accession="0000320193-23-000106",
        form="10-K",
        filed="2023-11-03",
        period="2023-09-30",
        primary_document="aapl.htm",
    )

    assert filing.accession_compact == "000032019323000106"
