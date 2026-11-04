"""JSON-lines logging on stdout."""

import json
import logging as _logging
import sys
from datetime import UTC, datetime

_STANDARD = frozenset(_logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
}


class _JsonFormatter(_logging.Formatter):
    def format(self, record: _logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = _logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = _logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
