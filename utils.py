"""Logging, notifications, and time helpers."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from config import Settings

EASTERN = ZoneInfo("America/New_York")
_LOGGER: Optional[logging.Logger] = None


def to_eastern(dt: Optional[datetime] = None) -> datetime:
    """Convert or localize a datetime to US/Eastern."""
    if dt is None:
        return datetime.now(EASTERN)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EASTERN)
    return dt.astimezone(EASTERN)


def setup_logging(settings: Settings) -> logging.Logger:
    """Configure rotating file + console logging."""
    global _LOGGER
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "my-trade.log"

    logger = logging.getLogger("my_trade")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    _LOGGER = logger
    return logger


def get_logger() -> logging.Logger:
    """Return the application logger."""
    if _LOGGER is None:
        from config import get_settings

        return setup_logging(get_settings())
    return _LOGGER


def is_trading_window(
    now_et: datetime,
    start_hour: int,
    start_minute: int,
    end_hour: int,
    end_minute: int,
) -> bool:
    """True if current ET time is within the allowed intraday window."""
    t = now_et.time()
    start = time(start_hour, start_minute)
    end = time(end_hour, end_minute)
    return start <= t <= end


def is_weekday(now_et: datetime) -> bool:
    """True Monday–Friday."""
    return now_et.weekday() < 5


def send_alert(settings: Settings, message: str, level: str = "INFO") -> None:
    """Send optional Telegram and/or Slack notifications."""
    logger = get_logger()
    prefix = f"[{level}] "
    full_message = prefix + message

    if settings.telegram_bot_token and settings.telegram_chat_id:
        try:
            url = (
                f"https://api.telegram.org/bot{settings.telegram_bot_token}"
                f"/sendMessage"
            )
            requests.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": full_message,
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.warning("Telegram alert failed: %s", exc)

    if settings.slack_webhook_url:
        try:
            requests.post(
                settings.slack_webhook_url,
                json={"text": full_message},
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.warning("Slack alert failed: %s", exc)
