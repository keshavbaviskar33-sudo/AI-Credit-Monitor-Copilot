import json
import logging

from credit_risk_copilot.logging_config import JsonFormatter, configure_logging


def test_configure_logging_sets_up_a_handler() -> None:
    configure_logging()

    root = logging.getLogger()
    assert root.handlers, "configure_logging should attach at least one handler"


def test_json_formatter_produces_valid_json() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )

    output = JsonFormatter().format(record)
    parsed = json.loads(output)

    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test"
