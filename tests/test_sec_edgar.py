import json
from dataclasses import dataclass

import pytest

import credit_risk_copilot.sec_edgar as sec_edgar_module
from credit_risk_copilot.sec_edgar import SecEdgarClient


@dataclass
class _FakeSettings:
    sec_user_agent: str
    sec_request_timeout_seconds: float = 10.0
    sec_max_requests_per_second: float = 8.0


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
