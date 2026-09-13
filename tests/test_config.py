from credit_risk_copilot.config import Settings, get_settings


def test_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.sec_max_requests_per_second <= 10, "must respect SEC's rate limit"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_settings_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SEC_USER_AGENT", "Test Suite test@example.com")

    settings = Settings(_env_file=None)

    assert settings.log_level == "DEBUG"
    assert settings.sec_user_agent == "Test Suite test@example.com"
