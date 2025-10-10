from datetime import datetime, timedelta, timezone

from app.time_utils import resolve_published_at


def test_resolve_naive_uses_default_timezone():
    fetched_at = datetime(2025, 10, 10, 3, 0, 0, tzinfo=timezone.utc)
    published_at, meta = resolve_published_at(
        "doonsec_wechat",
        [("2025-10-10T11:20:49", "item.pubDate")],
        fetched_at=fetched_at,
    )

    assert published_at == datetime(2025, 10, 10, 3, 20, 49, tzinfo=timezone.utc)
    assert meta["source"] == "item.pubDate"
    assert meta["applied_timezone"] == "Asia/Shanghai"
    assert meta.get("fallback") is False


def test_resolve_future_drift_falls_back_to_fetched():
    fetched_at = datetime(2025, 10, 10, 0, 0, 0, tzinfo=timezone.utc)
    future_value = fetched_at + timedelta(hours=6)

    published_at, meta = resolve_published_at(
        "exploit_db",
        [(future_value.isoformat(), "item.pubDate")],
        fetched_at=fetched_at,
    )

    assert published_at == fetched_at
    assert meta.get("flag") == "future_drift"
    assert meta.get("fallback") is True
    assert meta.get("applied_timezone") == "fetched_at"


def test_resolve_numeric_timestamp():
    target = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    fetched_at = target
    timestamp_value = int(target.timestamp())

    published_at, meta = resolve_published_at(
        "aliyun_security",
        [(timestamp_value, "item.publishTime")],
        fetched_at=fetched_at,
    )

    assert published_at == target
    assert meta["applied_timezone"] == "UTC"
    assert meta.get("fallback") is False
