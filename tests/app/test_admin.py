from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from app import crud, database, models
from tests.app.test_user_auth import create_test_client, auth_headers, register_and_login


def make_admin(client: TestClient, email: str) -> None:
    session_factory = database.get_session_factory()
    with session_factory() as session:
        user = crud.get_user_by_email(session, email)
        assert user is not None
        user.is_admin = True
        session.add(user)
        session.commit()


def test_admin_generate_and_use_activation_code():
    client = create_test_client()

    admin_tokens = register_and_login(client, "admin@example.com", password="AdminPass123!")
    make_admin(client, "admin@example.com")

    login_resp = client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"})
    assert login_resp.status_code == 200
    admin_tokens = login_resp.json()

    create_resp = client.post(
        "/admin/codes",
        data={"quantity": "1", "expires_in_days": "30", "notes": "测试批次"},
        headers=auth_headers(admin_tokens),
        allow_redirects=False,
    )
    assert create_resp.status_code == 303

    session_factory = database.get_session_factory()
    with session_factory() as session:
        code = (
            session.query(models.ActivationCode)
            .order_by(models.ActivationCode.created_at.desc())
            .first()
        )
        assert code is not None
        activation_code = code.code
        assert code.is_used is False

    user_tokens = register_and_login(client, "vipuser@example.com", password="VipPass123!")

    activate_resp = client.post(
        "/users/me/activate",
        json={"code": activation_code},
        headers=auth_headers(user_tokens),
    )
    assert activate_resp.status_code == 200
    vip_info = activate_resp.json()
    assert vip_info["is_vip"] is True
    assert vip_info["vip_expires_at"] is not None

    with session_factory() as session:
        code = (
            session.query(models.ActivationCode)
            .filter(models.ActivationCode.code == activation_code)
            .first()
        )
        assert code is not None
        assert code.is_used is True
        assert code.used_by_user is not None
        assert code.used_by_user.email == "vipuser@example.com"
        assert code.used_at is not None

        user = crud.get_user_by_email(session, "vipuser@example.com")
        assert user is not None
        assert user.vip_expires_at is not None
        expires_at = user.vip_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        assert expires_at > datetime.now(timezone.utc)
