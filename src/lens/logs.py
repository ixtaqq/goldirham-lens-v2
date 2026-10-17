"""Structured JSON logging with secret redaction on every line and every traceback."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

import structlog

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),  # Anthropic key
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(postgres(?:ql)?(?:\+asyncpg)?://[^:/\s]+:)[^@\s]+(@)"),  # DSN password
    re.compile(r"https://hc-ping\.com/[A-Za-z0-9/_-]+"),  # Healthchecks ping URL
    re.compile(r"(api\.telegram\.org/bot)[^/\s]+"),
)


class Redactor:
    """Replaces configured secret values and known secret shapes in any string."""

    def __init__(self, secret_values: Iterable[str] = ()) -> None:
        values = sorted({value for value in secret_values if len(value) >= 6}, key=len)
        self._values = tuple(reversed(values))

    def redact(self, text: str) -> str:
        for value in self._values:
            if value in text:
                text = text.replace(value, REDACTED)
        for pattern in _PATTERNS:
            if pattern.groups == 2:
                text = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}{m.group(2)}", text)
            elif pattern.groups == 1:
                text = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
            else:
                text = pattern.sub(REDACTED, text)
        return text

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, Mapping):
            return {key: self.redact_value(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(self.redact_value(item) for item in value)
        return value

    def processor(
        self, _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        for key in list(event_dict):
            event_dict[key] = self.redact_value(event_dict[key])
        return event_dict


class _RedactingFormatter(logging.Formatter):
    def __init__(self, redactor: Redactor, base: logging.Formatter | None) -> None:
        super().__init__()
        self._redactor = redactor
        self._base = base or logging.Formatter("%(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return self._redactor.redact(self._base.format(record))


_active = Redactor()


def configure_logging(secret_values: Iterable[str] = (), *, level: int = logging.INFO) -> Redactor:
    """Configure structlog and the stdlib root logger. Safe to call more than once."""
    global _active
    _active = Redactor(secret_values)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _active.processor,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stderr))
    root.setLevel(level)
    for handler in root.handlers:
        base = handler.formatter
        if isinstance(base, _RedactingFormatter):
            base = base._base
        handler.setFormatter(_RedactingFormatter(_active, base))
    for noisy in ("httpx", "httpcore", "yfinance", "asyncio", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return _active


def redact(text: str) -> str:
    return _active.redact(text)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
