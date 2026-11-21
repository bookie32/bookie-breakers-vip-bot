"""Structured JSON logging with a strict allowlist of extra fields."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any


_SAFE_FIELDS = {
    "available",
    "bot_user_id",
    "channel_id",
    "command_count",
    "command_name",
    "command_status",
    "connected_guild_count",
    "configured_servers",
    "error_type",
    "event",
    "event_method",
    "guild_id",
    "guild_name",
    "panel",
    "reason",
    "server",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field_name in _SAFE_FIELDS:
            if hasattr(record, field_name):
                document[field_name] = getattr(record, field_name)
        return json.dumps(document, ensure_ascii=False, default=str)


def configure_logging() -> None:
    configured_level = logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO").upper())
    if not isinstance(configured_level, int):
        configured_level = logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(configured_level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
