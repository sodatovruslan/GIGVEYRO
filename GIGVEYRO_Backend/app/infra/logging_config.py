"""
Structured JSON logging configuration for GIGVEYRO.

Features:
  - JSON output in production (APP_ENV=production)
  - Human-readable format in development
  - Request ID propagated via contextvars (set by RequestIDMiddleware)
  - Sensitive field masking (passwords, tokens, keys)
  - Safe metadata on every log record

Usage (call once at startup):
    from app.infra.logging_config import configure_logging
    configure_logging()

Request ID injection (call from middleware):
    from app.infra.logging_config import set_request_id
    set_request_id(request_id)
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# ContextVar for request-scoped ID propagation (set by RequestIDMiddleware)
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    """Set the request ID for the current async context."""
    _request_id_var.set(request_id)


def get_request_id() -> str:
    """Get the current request ID (or '-' if not set)."""
    return _request_id_var.get()


# Fields that must NEVER appear in logs
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "api_key",
        "apikey",
        "private_key",
        "seed_phrase",
        "mnemonic",
        "totp_secret",
        "totp_code",
        "recovery_code",
        "recovery_codes",
        "challenge_token",
        "setup_token",
        "card_number",
        "requisite_number",
        "cvv",
        "pin",
        "authorization",
        "database_url",
        "redis_url",
    }
)

_SENSITIVE_KEY_SUFFIXES = (
    "_password",
    "_secret",
    "_token",
    "_api_key",
    "_private_key",
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower()
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def _mask_sensitive(obj: Any, depth: int = 0) -> Any:
    """Recursively mask sensitive keys in dicts (max depth 5)."""
    if depth > 5:
        return obj
    if isinstance(obj, dict):
        return {
            k: "***REDACTED***" if _is_sensitive_key(k) else _mask_sensitive(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask_sensitive(i, depth + 1) for i in obj]
    return obj


class _JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A002
        message = record.getMessage()
        log_obj: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": get_request_id(),
            "event": message,
        }

        # Attach extra metadata (e.g. kwargs passed to logger.info("...", extra={...}))
        extra_keys = set(record.__dict__) - {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
        for key in extra_keys:
            val = getattr(record, key)
            log_obj[key] = "***REDACTED***" if _is_sensitive_key(key) else _mask_sensitive(val)

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_obj["stack"] = record.stack_info

        try:
            return json.dumps(log_obj, default=str, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            return json.dumps({"event": "log_serialisation_error", "raw": str(log_obj)})


class _DevFormatter(logging.Formatter):
    """Human-readable coloured-style formatter for development."""

    _LEVEL_COLOURS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:  # noqa: A002
        colour = self._LEVEL_COLOURS.get(record.levelname, "")
        rid = get_request_id()
        prefix = f"{colour}{record.levelname:8s}{self._RESET} [{record.name}] [req:{rid}]"
        msg = record.getMessage()
        result = f"{prefix} {msg}"
        if record.exc_info:
            result += "\n" + "".join(traceback.format_exception(*record.exc_info))
        return result


def configure_logging(app_env: str = "development", log_level: str = "INFO") -> None:
    """Configure root logger with appropriate formatter.

    Call once at application startup before any log statements.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)

    if app_env == "production":
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(_DevFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicate output
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Quieten noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
