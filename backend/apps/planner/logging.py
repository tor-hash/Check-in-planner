"""Lightweight structured-logging helpers.

We don't pull in structlog to keep the dependency surface small; a single
JsonFormatter is enough to ship newline-delimited JSON to stdout, which
Render (and most hosting platforms) will pick up automatically.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_RESERVED_LOG_RECORD_ATTRS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName",
}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record.

    Any extra keyword arguments passed to ``logger.info(msg, extra={...})``
    end up as top-level fields, which is how the booking service attaches
    structured context (manager_id, person_id, etc.).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
