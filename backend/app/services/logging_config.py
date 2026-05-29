"""JSON logging configuration per TR-1.05."""

import datetime
import logging
from contextvars import ContextVar

from pythonjsonlogger import jsonlogger

# Set once per request by the route-context middleware in main.py.
# The _AppContextFilter reads it so every log record emitted during
# a request automatically includes the route field.
request_route: ContextVar[str] = ContextVar("request_route", default="")


class _AppContextFilter(logging.Filter):
    """Injects route into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.route = request_route.get()  # type: ignore[attr-defined]
        return True


class _JsonFormatter(jsonlogger.JsonFormatter):
    """Emits one JSON object per log record with normalised field names."""

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"
        log_record["level"] = record.levelname
        for key in ("asctime", "levelname", "color_message", "taskName"):
            log_record.pop(key, None)


def setup_logging() -> None:
    """Replace the root logger's handlers with a single JSON stream handler.

    Call once at app startup before any requests are served.  The formatter
    automatically includes timestamp, level, route, and message on every
    record; extra fields passed via logger.error(..., extra={...}) are
    merged in as top-level JSON keys.
    """
    formatter = _JsonFormatter(
        "%(levelname)s %(route)s %(message)s"
    )
    ctx_filter = _AppContextFilter()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(ctx_filter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
