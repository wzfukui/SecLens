from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database, models, crud
from app.database import Base, get_db_session
from app.main import create_app

# Ensure models are imported so metadata is registered.
import app.models  # noqa: F401


def create_test_client() -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    database._engine = engine  # type: ignore[attr-defined]
    database._SessionLocal = session_factory  # type: ignore[attr-defined]
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db
    return TestClient(app)


def register_and_login(client: TestClient, email: str, password: str = "StrongPass123!") -> dict:
    register_resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "display_name": "Tester"},
    )
    assert register_resp.status_code == 201
    login_resp = client.post("/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    return login_resp.json()


def auth_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_user_registration_login_and_profile():
    client = create_test_client()
    tokens = register_and_login(client, "user1@example.com")

    me_resp = client.get("/auth/me", headers=auth_headers(tokens))
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["email"] == "user1@example.com"
    assert body["display_name"] == "Tester"
    assert body["is_admin"] is False

    vip_resp = client.get("/users/me/vip", headers=auth_headers(tokens))
    assert vip_resp.status_code == 200
    vip = vip_resp.json()
    assert vip["is_vip"] is False
    assert vip["vip_expires_at"] is None


def test_activation_code_and_notification_settings():
    client = create_test_client()
    tokens = register_and_login(client, "user2@example.com")
    session_factory = database.get_session_factory()

    with session_factory() as session:
        code = models.ActivationCode(
            code="VIPCODE-001",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        session.add(code)
        session.commit()

    activate_resp = client.post(
        "/users/me/activate",
        json={"code": "VIPCODE-001"},
        headers=auth_headers(tokens),
    )
    assert activate_resp.status_code == 200
    vip = activate_resp.json()
    assert vip["is_vip"] is True
    assert vip["vip_expires_at"] is not None

    notif_payload = {
        "webhook_url": "https://example.com/webhook",
        "notify_email": "alerts@example.com",
        "send_webhook": True,
        "send_email": True,
    }
    notif_resp = client.put(
        "/users/me/notifications",
        json=notif_payload,
        headers=auth_headers(tokens),
    )
    assert notif_resp.status_code == 200
    saved = notif_resp.json()
    assert saved["webhook_url"] == notif_payload["webhook_url"]
    assert saved["notify_email"] == notif_payload["notify_email"]
    assert saved["send_webhook"] is True
    assert saved["send_email"] is True


def test_push_rule_and_subscription_flow():
    client = create_test_client()
    tokens = register_and_login(client, "user3@example.com")
    session_factory = database.get_session_factory()

    with session_factory() as session:
        plugin = models.Plugin(slug="test_plugin", name="Test Plugin", description="Demo")
        session.add(plugin)
        session.commit()

    rule_resp = client.post(
        "/users/me/push-rules",
        json={
            "name": "关键字过滤",
            "keyword": "漏洞",
            "is_active": True,
            "notify_via_webhook": True,
            "notify_via_email": False,
        },
        headers=auth_headers(tokens),
    )
    assert rule_resp.status_code == 201
    rule = rule_resp.json()
    assert rule["name"] == "关键字过滤"
    assert rule["keyword"] == "漏洞"

    sub_resp = client.post(
        "/users/me/subscriptions",
        json={
            "name": "插件订阅",
            "channel_slugs": ["test_plugin"],
            "is_active": True,
            "keyword_filter": "漏洞",
        },
        headers=auth_headers(tokens),
    )
    assert sub_resp.status_code == 201
    subscription = sub_resp.json()
    assert subscription["name"] == "插件订阅"
    assert subscription["channel_slugs"] == ["test_plugin"]
    assert subscription["rss_url"] is not None

    list_resp = client.get("/users/me/subscriptions", headers=auth_headers(tokens))
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["token"] == subscription["token"]

    with session_factory() as session:
        user = crud.get_user_by_email(session, "user3@example.com")
        assert user is not None
        user.vip_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        session.commit()

    rss_resp = client.get(subscription["rss_url"], headers={})
    assert rss_resp.status_code == 200
    rss_body = rss_resp.content.decode("utf-8")
    assert "无有效的订阅服务" in rss_body
    assert "<item>" not in rss_body


def test_ingest_triggers_webhook_notifications(monkeypatch: pytest.MonkeyPatch):
    client = create_test_client()
    tokens = register_and_login(client, "user4@example.com", password="SecretPass!23")

    # Ensure plugin exists for the bulletin source.
    session_factory = database.get_session_factory()
    with session_factory() as session:
        plugin = models.Plugin(slug="webhook_plugin", name="Webhook Plugin", description="Demo")
        session.add(plugin)
        session.commit()

    # Enable webhook notifications.
    client.put(
        "/users/me/notifications",
        json={
            "webhook_url": "https://hook.example.com/notify",
            "send_webhook": True,
            "send_email": False,
        },
        headers=auth_headers(tokens),
    )

    # Create matching push rule.
    client.post(
        "/users/me/push-rules",
        json={
            "name": "Webhook Rule",
            "keyword": "紧急",
            "is_active": True,
            "notify_via_webhook": True,
            "notify_via_email": False,
        },
        headers=auth_headers(tokens),
    )

    captured: dict = {}

    def fake_post(url: str, json: dict | None = None, timeout: float | None = None):
        captured["url"] = url
        captured["payload"] = json

        class DummyResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

        return DummyResponse()

    monkeypatch.setattr("app.services.notifications.httpx.post", fake_post)

    payload = [
        {
            "source": {
                "source_slug": "webhook_plugin",
                "external_id": "abc-123",
                "origin_url": "https://example.org/alerts/123",
            },
            "content": {
                "title": "紧急漏洞通告",
                "summary": "发现紧急漏洞，请及时处理。",
                "body_text": "紧急情况说明……",
                "published_at": datetime(2024, 5, 1, tzinfo=timezone.utc).isoformat(),
            },
        }
    ]

    ingest_resp = client.post("/v1/ingest/bulletins", json=payload)
    assert ingest_resp.status_code == 202
    assert ingest_resp.json()["accepted"] == 1
    assert captured["url"] == "https://hook.example.com/notify"
    assert captured["payload"]["rule_name"] == "Webhook Rule"
    assert captured["payload"]["bulletin"]["title"] == "紧急漏洞通告"


def test_ingest_triggers_email_notifications(monkeypatch: pytest.MonkeyPatch):
    client = create_test_client()
    tokens = register_and_login(client, "user5@example.com", password="SecretPass!23")

    session_factory = database.get_session_factory()
    with session_factory() as session:
        plugin = models.Plugin(slug="email_plugin", name="Email Plugin", description="Demo")
        session.add(plugin)
        session.commit()

    client.put(
        "/users/me/notifications",
        json={
            "notify_email": "alerts@example.com",
            "send_email": True,
            "send_webhook": False,
        },
        headers=auth_headers(tokens),
    )

    client.post(
        "/users/me/push-rules",
        json={
            "name": "Email Rule",
            "keyword": "提醒",
            "is_active": True,
            "notify_via_webhook": False,
            "notify_via_email": True,
        },
        headers=auth_headers(tokens),
    )

    captured: dict = {}

    def fake_send_email(*, to, subject, html, text=None):
        captured["to"] = list(to)
        captured["subject"] = subject
        captured["html"] = html
        captured["text"] = text

    monkeypatch.setattr("app.services.notifications.send_email", fake_send_email)

    payload = [
        {
            "source": {
                "source_slug": "email_plugin",
                "external_id": "ex-321",
            },
            "content": {
                "title": "提醒漏洞通告",
                "summary": "提醒相关漏洞。",
                "body_text": "更多信息……",
                "published_at": datetime(2024, 6, 1, tzinfo=timezone.utc).isoformat(),
            },
        }
    ]

    resp = client.post("/v1/ingest/bulletins", json=payload)
    assert resp.status_code == 202
    assert resp.json()["accepted"] == 1
    assert captured["to"] == ["alerts@example.com"]
    assert "提醒" in captured["subject"]
    assert "提醒漏洞通告" in captured["html"]
