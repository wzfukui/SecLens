"""Helpers for converting datetimes to the configured display timezone."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from functools import lru_cache
import logging
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_display_timezone() -> ZoneInfo | timezone:
    """Return the ZoneInfo configured for user-facing datetime display."""

    tz_name = get_settings().display_timezone
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone '%s', falling back to UTC for display", tz_name)
    return timezone.utc


def _coerce_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware, defaulting to UTC if naive."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def to_display_tz(dt: datetime) -> datetime:
    """Convert a datetime to the configured display timezone."""

    return _coerce_aware(dt).astimezone(get_display_timezone())


def _format_utc_offset(offset: Optional[timedelta]) -> str:
    """Format a UTC offset as ±HH:MM."""

    if offset is None:
        return ""
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def format_display(dt: Optional[datetime], pattern: Optional[str] = None) -> Optional[str]:
    """Format a datetime for end-user display.

    Returns None when dt is None, otherwise converts to the display timezone and
    renders either with the provided strftime pattern or a default format of
    'YYYY-MM-DD HH:MM (UTC±HH:MM)'.
    """

    if dt is None:
        return None
    localized = to_display_tz(dt)
    if pattern:
        return localized.strftime(pattern)

    offset = _format_utc_offset(localized.utcoffset())
    offset_section = f" (UTC{offset})" if offset else ""
    return f"{localized.strftime('%Y-%m-%d %H:%M')}{offset_section}"


__all__ = ["format_display", "get_display_timezone", "to_display_tz"]
