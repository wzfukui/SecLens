from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import database
from app.models import Plugin, Bulletin

from tests.app.test_ingest import create_test_client


def _add_plugin(session: Session, *, slug: str, status: str, is_active: bool = False) -> None:
    now = datetime.now(timezone.utc)
    plugin = Plugin(
        slug=slug,
        name=f"{slug} collector",
        version="1.0.0",
        description="test",
        entrypoint="collector:run",
        schedule="1800" if is_active else None,
        status=status,
        is_active=is_active,
        upload_path="/tmp",
        created_at=now,
        updated_at=now,
        activated_at=now if is_active else None,
        last_run_at=now if is_active else None,
        next_run_at=now if is_active else None,
    )
    session.add(plugin)
    session.commit()


def _add_bulletin(session: Session, *, source_slug: str) -> None:
    now = datetime.now(timezone.utc)
    bulletin = Bulletin(
        source_slug=source_slug,
        external_id=f"{source_slug}-{now.timestamp()}",
        title=f"{source_slug} sample",
        summary="demo",
        fetched_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(bulletin)
    session.commit()


def test_plugin_dashboard_renders_plugin_table():
    client = create_test_client()
    SessionFactory = database._SessionLocal  # type: ignore[attr-defined]
    assert SessionFactory is not None

    with SessionFactory() as session:
        _add_plugin(session, slug="demo_plugin", status="active", is_active=False)
        _add_plugin(session, slug="staging_plugin", status="uploaded", is_active=False)
        _add_bulletin(session, source_slug="demo_plugin")

    response = client.get("/dashboard/plugins")
    assert response.status_code == 200
    body = response.text
    assert "插件运行监控" in body
    assert "demo_plugin" in body
    assert "staging_plugin" in body
    assert "采集总量" in body
