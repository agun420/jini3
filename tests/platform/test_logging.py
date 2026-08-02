import json
import logging

from daybreak.core.logging import JsonFormatter


def test_json_formatter_redacts_secret_fields() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.context = {"api_key": "secret", "ticker": "AAPL"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["context"]["api_key"] == "[REDACTED]"
    assert payload["context"]["ticker"] == "AAPL"
