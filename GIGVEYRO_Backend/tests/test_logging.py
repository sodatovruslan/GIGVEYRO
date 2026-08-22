import json
import logging

from app.infra.logging_config import _JSONFormatter


def test_json_logging_redacts_nested_security_and_financial_fields():
    formatter = _JSONFormatter()
    record = logging.LogRecord(
        name="security.audit",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="security event",
        args=(),
        exc_info=None,
    )
    record.payload = {
        "password": "plain-password",
        "challenge_token": "challenge-value",
        "totp_code": "123456",
        "recovery_codes": ["code-one", "code-two"],
        "card_number": "4111111111111111",
        "nested": {"provider_api_key": "provider-value"},
        "safe_status": "accepted",
    }

    payload = json.loads(formatter.format(record))

    assert payload["payload"]["password"] == "***REDACTED***"
    assert payload["payload"]["challenge_token"] == "***REDACTED***"
    assert payload["payload"]["totp_code"] == "***REDACTED***"
    assert payload["payload"]["recovery_codes"] == "***REDACTED***"
    assert payload["payload"]["card_number"] == "***REDACTED***"
    assert payload["payload"]["nested"]["provider_api_key"] == "***REDACTED***"
    assert payload["payload"]["safe_status"] == "accepted"


def test_json_logging_does_not_expose_connection_urls():
    formatter = _JSONFormatter()
    record = logging.LogRecord(
        name="startup",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="startup",
        args=(),
        exc_info=None,
    )
    record.database_url = "postgresql://user:password@database/app"
    record.redis_url = "redis://:password@redis/0"

    serialized = formatter.format(record)

    assert "user:password" not in serialized
    assert ":password@" not in serialized
