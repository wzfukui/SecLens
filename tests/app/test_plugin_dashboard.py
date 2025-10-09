from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import database
from app.models import Plugin, PluginVersion, Bulletin
from app.models import PluginRun

from tests.app.test_ingest import create_test_client


def _add_plugin(session: Session, *, slug: str, status: str, is_active: bool = False) -> None:
    now = datetime.now(timezone.utc)
    plugin = Plugin(
        slug=slug,
        name=f"{slug} collector",
        description="test",
        created_at=now,
        updated_at=now,
        is_enabled=True,
    )
    session.add(plugin)
    session.flush()

    version = PluginVersion(
        plugin_id=plugin.id,
        version="1.0.0",
        entrypoint="collector:run",
        schedule="1800" if is_active else None,
        status=status,
        is_active=is_active,
        upload_path="/tmp",
        manifest={"version": "1.0.0"},
        created_at=now,
        updated_at=now,
        activated_at=now if is_active else None,
        last_run_at=now if is_active else None,
        next_run_at=now if is_active else None,
    )
    plugin.versions.append(version)
    if is_active:
        plugin.current_version = version
    session.commit()


def _add_bulletin(session: Session, *, source_slug: str) -> int:
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
    return bulletin.id


def test_plugin_dashboard_renders_plugin_table():
    client = create_test_client()
    SessionFactory = database._SessionLocal  # type: ignore[attr-defined]
    assert SessionFactory is not None

    with SessionFactory() as session:
        _add_plugin(session, slug="demo_plugin", status="active", is_active=True)
        _add_plugin(session, slug="staging_plugin", status="uploaded", is_active=False)
        _add_bulletin(session, source_slug="demo_plugin")

    response = client.get("/dashboard/plugins")
    assert response.status_code == 200
    body = response.text
    assert "插件运行监控" in body
    assert "demo_plugin" in body
    assert "staging_plugin" in body
    assert "采集总量" in body


def test_plugin_detail_page_shows_versions_and_runs():
    client = create_test_client()
    SessionFactory = database._SessionLocal  # type: ignore[attr-defined]
    assert SessionFactory is not None

    plugin_slug = "detail_plugin"

    with SessionFactory() as session:
        _add_plugin(session, slug=plugin_slug, status="active", is_active=True)
        plugin = session.query(Plugin).filter(Plugin.slug == plugin_slug).first()
        assert plugin is not None
        version = plugin.current_version
        assert version is not None
        version.manifest = {
            "slug": plugin.slug,
            "name": plugin.name,
            "version": version.version,
            "entrypoint": version.entrypoint,
        }
        run = PluginRun(
            plugin_id=plugin.id,
            plugin_version_id=version.id,
            status="completed",
        )
        session.add(run)
        bulletin_id = _add_bulletin(session, source_slug=plugin.slug)
        session.commit()

    response = client.get(f"/dashboard/plugins/{plugin_slug}")
    assert response.status_code == 200
    body = response.text
    assert "detail_plugin" in body
    assert "版本历史" in body
    assert "采集趋势" in body
    assert "plugin-trend-chart" in body
    assert "/bulletins/" in body

    detail_response = client.get(f"/bulletins/{bulletin_id}")
    assert detail_response.status_code == 200
    assert f"/dashboard/plugins/{plugin_slug}" in detail_response.text
