"""Shared helpers for normalising publication timestamps across collectors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence
import logging

import yaml
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


logger = logging.getLogger(__name__)

_POLICY_FILE = Path(__file__).resolve().parents[1] / "resources" / "time_policies.yaml"


@dataclass(frozen=True)
class TimePolicy:
    default_timezone: Optional[str] = None
    naive_strategy: str = "assume_default"
    max_future_drift_minutes: Optional[int] = None
    max_past_drift_days: Optional[int] = None
    forbid_midnight_if_no_time: bool = False

    @property
    def max_future_drift(self) -> Optional[timedelta]:
        if self.max_future_drift_minutes is None:
            return None
        return timedelta(minutes=self.max_future_drift_minutes)

    @property
    def max_past_drift(self) -> Optional[timedelta]:
        if self.max_past_drift_days is None:
            return None
        return timedelta(days=self.max_past_drift_days)


@dataclass
class _ParsedCandidate:
    value: datetime
    had_timezone: bool
    date_only: bool
    raw: Any
    label: str


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_policy_file() -> dict[str, Any]:
    if not _POLICY_FILE.exists():
        logger.warning("Time policy file %s not found; using defaults", _POLICY_FILE)
        return {}
    with _POLICY_FILE.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        logger.warning("Unexpected time policy structure in %s; using defaults", _POLICY_FILE)
        return {}
    return data


@lru_cache(maxsize=None)
def _policies_by_source() -> dict[str, TimePolicy]:
    data = _load_policy_file()
    defaults = data.get("defaults", {}) if isinstance(data.get("defaults"), dict) else {}
    sources = data.get("sources", {}) if isinstance(data.get("sources"), dict) else {}

    default_policy = TimePolicy(
        default_timezone=defaults.get("default_timezone"),
        naive_strategy=defaults.get("naive_strategy", "assume_default"),
        max_future_drift_minutes=_coerce_int(defaults.get("max_future_drift_minutes")),
        max_past_drift_days=_coerce_int(defaults.get("max_past_drift_days")),
        forbid_midnight_if_no_time=bool(defaults.get("forbid_midnight_if_no_time", False)),
    )

    resolved: dict[str, TimePolicy] = {}
    for slug, overrides in sources.items():
        if not isinstance(overrides, dict):
            continue
        resolved[slug] = TimePolicy(
            default_timezone=overrides.get("default_timezone", default_policy.default_timezone),
            naive_strategy=overrides.get("naive_strategy", default_policy.naive_strategy),
            max_future_drift_minutes=_coerce_int(
                overrides.get("max_future_drift_minutes", default_policy.max_future_drift_minutes)
            ),
            max_past_drift_days=_coerce_int(
                overrides.get("max_past_drift_days", default_policy.max_past_drift_days)
            ),
            forbid_midnight_if_no_time=bool(
                overrides.get("forbid_midnight_if_no_time", default_policy.forbid_midnight_if_no_time)
            ),
        )
    resolved["_default"] = default_policy
    return resolved


def get_time_policy(source_slug: str) -> TimePolicy:
    policies = _policies_by_source()
    return policies.get(source_slug, policies["_default"])


def _get_zoneinfo(name: Optional[str]) -> ZoneInfo | timezone:
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone '%s'; falling back to UTC", name)
        return timezone.utc


def _parse_timestamp(value: float) -> datetime:
    """Coerce numeric timestamps (seconds or milliseconds) into aware UTC datetimes."""

    seconds = float(value)
    if seconds > 1e12:
        seconds = seconds / 1000.0
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _normalise_iso(text: str) -> str:
    stripped = text.strip()
    if stripped.endswith("Z") or stripped.endswith("z"):
        stripped = stripped[:-1] + "+00:00"
    if "+" in stripped and stripped[-3] != ":":
        # normalise +0800 to +08:00
        plus_index = stripped.rfind("+")
        minus_index = stripped.rfind("-")
        idx = max(plus_index, minus_index)
        if idx > 0 and len(stripped) - idx in (5, 6):
            offset = stripped[idx + 1 :]
            if offset.isdigit():
                stripped = stripped[: idx + 1] + offset[:2] + ":" + offset[2:]
    return stripped


def _parse_datetime_string(text: str) -> Optional[datetime]:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        pass
    iso_candidate = _normalise_iso(stripped)
    try:
        return datetime.fromisoformat(iso_candidate)
    except ValueError:
        pass
    # Attempt to treat as pure integer timestamp encoded as string
    if stripped.isdigit():
        try:
            return _parse_timestamp(float(stripped))
        except (ValueError, OverflowError):
            return None
    return None


def _parse_candidate(value: Any, label: str) -> Optional[_ParsedCandidate]:
    if value is None:
        return None
    raw = value
    if isinstance(value, datetime):
        had_tz = value.tzinfo is not None
        return _ParsedCandidate(value=value, had_timezone=had_tz, date_only=False, raw=raw, label=label)
    if isinstance(value, (int, float)):
        dt = _parse_timestamp(value)
        return _ParsedCandidate(value=dt, had_timezone=True, date_only=False, raw=raw, label=label)
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        dt = _parse_datetime_string(txt)
        if dt is None:
            return None
        date_only = False
        if "T" not in txt and " " not in txt and ":" not in txt:
            date_only = True
        return _ParsedCandidate(
            value=dt,
            had_timezone=dt.tzinfo is not None,
            date_only=date_only,
            raw=txt,
            label=label,
        )
    return None


def _tz_label(tz: timezone | ZoneInfo, dt: datetime) -> str:
    key = getattr(tz, "key", None)
    if key:
        return key
    name = tz.tzname(dt)
    if name:
        return name
    offset = tz.utcoffset(dt)
    if offset:
        total_minutes = int(offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        total_minutes = abs(total_minutes)
        hours, minutes = divmod(total_minutes, 60)
        return f"UTC{sign}{hours:02d}:{minutes:02d}"
    return "UTC"


def _apply_naive_policy(candidate: _ParsedCandidate, policy: TimePolicy, metadata: dict[str, Any]) -> Optional[datetime]:
    strategy = policy.naive_strategy or "assume_default"
    if strategy == "reject":
        metadata["flag"] = "naive_rejected"
        return None
    if strategy == "utc":
        metadata["applied_timezone"] = "UTC"
        return candidate.value.replace(tzinfo=timezone.utc)
    tz = _get_zoneinfo(policy.default_timezone)
    metadata["applied_timezone"] = _tz_label(tz, candidate.value)
    return candidate.value.replace(tzinfo=tz)


def resolve_published_at(
    source_slug: str,
    candidates: Sequence[tuple[Any, str]],
    *,
    fetched_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> tuple[Optional[datetime], dict[str, Any]]:
    """Resolve a publication datetime according to the configured policy."""

    policy = get_time_policy(source_slug)
    base = fetched_at or now or datetime.now(timezone.utc)

    for raw_value, label in candidates:
        candidate = _parse_candidate(raw_value, label)
        if not candidate:
            continue
        metadata: dict[str, Any] = {
            "source": candidate.label,
            "raw": candidate.raw,
            "fallback": False,
        }
        if candidate.date_only:
            metadata["date_only"] = True

        if candidate.had_timezone:
            resolved = candidate.value.astimezone(timezone.utc)
            metadata["applied_timezone"] = _tz_label(candidate.value.tzinfo, candidate.value)  # type: ignore[arg-type]
        else:
            resolved = _apply_naive_policy(candidate, policy, metadata)
            if resolved is None:
                continue
            resolved = resolved.astimezone(timezone.utc)

        if (
            candidate.date_only
            and policy.forbid_midnight_if_no_time
            and candidate.value.time() == time(0, 0)
        ):
            metadata["flag"] = "date_only_midnight"

        if policy.max_future_drift is not None and base is not None:
            allowed = base + policy.max_future_drift
            if resolved > allowed:
                metadata["flag"] = "future_drift"
                metadata["fallback"] = True
                metadata["applied_timezone"] = "fetched_at"
                return base, metadata
        if policy.max_past_drift is not None and base is not None:
            threshold = base - policy.max_past_drift
            if resolved < threshold:
                metadata.setdefault("flag", "past_drift")
        return resolved, metadata

    metadata = {"source": None, "fallback": True}
    if fetched_at:
        metadata["applied_timezone"] = "fetched_at"
        return fetched_at, metadata
    return None, metadata


__all__ = ["TimePolicy", "get_time_policy", "resolve_published_at"]
