"""FastAPI application entrypoint."""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session, selectinload

from app import crud, models
from app.services import build_home_sections, HomeSection, SourceSection
from scripts.scheduler_service import start_scheduler
from app.database import Base, get_db_session, get_engine, get_session_factory
from app.schemas import BulletinOut
from app.logging_utils import setup_logging
from app.utils.datetime import (
    format_display,
    get_display_timezone,
    get_display_timezone_label,
    to_display_tz,
)
from app.config import get_settings
from app.utils.security import hash_password
from app.dependencies import get_optional_user

from app.routers import admin, auth, bulletins, feeds, ingest, plugins, users
from app.models import Plugin, Bulletin


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ASSET_DIST_DIR = STATIC_DIR / "dist"
ASSET_MANIFEST_PATH = ASSET_DIST_DIR / "manifest.json"


@lru_cache(maxsize=1)
def _load_asset_manifest() -> dict[str, str]:
    if ASSET_MANIFEST_PATH.exists():
        try:
            return json.loads(ASSET_MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def static_asset_url(filename: str) -> str:
    manifest = _load_asset_manifest()
    target = manifest.get(filename, filename)
    return f"/static/dist/{target}"


setup_logging()


def create_app() -> FastAPI:
    app = FastAPI(title="SecLens Ingest API", version="0.1.0")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.globals["static_asset_url"] = static_asset_url
    app.state.templates = templates

    def display_time_filter(value: Optional[datetime], pattern: Optional[str] = None) -> str:
        formatted = format_display(value, pattern=pattern)
        return formatted or ""

    templates.env.filters["display_time"] = display_time_filter

    def render_extra_filter(value: Any) -> str:
        """Render extra JSON fields without escaping non-ASCII characters."""
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value

    templates.env.filters["render_extra"] = render_extra_filter

    start_scheduler(app)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.on_event("startup")
    def startup_event() -> None:
        _load_asset_manifest.cache_clear()
        _load_asset_manifest()
        engine = get_engine()
        Base.metadata.create_all(bind=engine)
        settings = get_settings()
        if settings.admin_email and settings.admin_password:
            session_factory = get_session_factory()
            with session_factory() as session:
                existing = crud.get_user_by_email(session, settings.admin_email)
                if existing is None:
                    password_hash = hash_password(settings.admin_password)
                    crud.create_user(
                        session,
                        email=settings.admin_email,
                        password_hash=password_hash,
                        display_name="管理员",
                        is_admin=True,
                    )
                    session.commit()

    @app.get("/health", tags=["health"])
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(ingest.router)
    app.include_router(bulletins.router)
    app.include_router(feeds.router)
    app.include_router(plugins.router)
    app.include_router(users.router)

    @app.get("/", response_class=HTMLResponse, tags=["web"])
    def homepage(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
        limit = 8
        sections = build_home_sections(db, limit_per_source=limit)
        all_items, all_total = crud.list_bulletins(db, limit=limit)
        all_section = HomeSection(
            slug="all",
            title="全部",
            description="最新采集的全量资讯流",
            sources=[
                SourceSection(
                    slug="all",
                    title="全部来源",
                    total=all_total,
                    items=[BulletinOut.model_validate(item) for item in all_items],
                )
            ],
        )
        sections.insert(0, all_section)
        if not sections:
            sections = []

        section_slug = request.query_params.get("section")
        source_slug = request.query_params.get("source")

        selected_section = None
        if section_slug:
            selected_section = next((s for s in sections if s.slug == section_slug), None)
        if selected_section is None and sections:
            selected_section = sections[0]

        selected_source = None
        if selected_section:
            if source_slug:
                selected_source = next((src for src in selected_section.sources if src.slug == source_slug), None)
            if selected_source is None and selected_section.sources:
                selected_source = selected_section.sources[0]

        context = {
            "title": "SecLens 安全情报台",
            "header": "SecLens 情报雷达",
            "sections": sections,
            "selected_section": selected_section,
            "selected_source": selected_source,
            "limit": limit,
            "all_total": all_total,
            "page_id": "home",
        }
        return templates.TemplateResponse(request=request, name="index.html", context=context)
    @app.get("/docs", response_class=HTMLResponse, tags=["pages"])
    def docs_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="docs.html",
            context={"title": "插件规范与示例", "page_id": "docs"},
        )

    @app.get("/plugin-dev", response_class=HTMLResponse, tags=["pages"])
    def plugin_dev_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="plugin_dev.html",
            context={"title": "插件开发指南", "page_id": "plugin-dev"},
        )

    @app.get("/about", response_class=HTMLResponse, tags=["pages"])
    def about_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="about.html",
            context={"title": "关于 SecLens", "page_id": "about"},
        )

    @app.get("/terms", response_class=HTMLResponse, tags=["pages"])
    def terms_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="terms.html",
            context={"title": "SecLens 服务协议", "page_id": "terms"},
        )

    @app.get("/privacy", response_class=HTMLResponse, tags=["pages"])
    def privacy_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="privacy.html",
            context={"title": "SecLens 隐私条款", "page_id": "privacy"},
        )

    @app.get("/login", response_class=HTMLResponse, tags=["pages"])
    def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"title": "登录", "page_id": "login"},
        )

    @app.get("/register", response_class=HTMLResponse, tags=["pages"])
    def register_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"title": "注册", "page_id": "register"},
        )

    @app.get("/dashboard", response_class=HTMLResponse, tags=["pages"])
    def dashboard_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"title": "个人控制台", "page_id": "dashboard"},
        )

    @app.get("/dashboard/plugins", response_class=HTMLResponse, tags=["pages"])
    def plugin_dashboard(
        request: Request,
        db: Session = Depends(get_db_session),
        current_user: Optional[models.User] = Depends(get_optional_user),
    ) -> HTMLResponse:
        plugin_rows = (
            db.query(Plugin)
            .options(
                selectinload(Plugin.current_version),
                selectinload(Plugin.versions),
            )
            .order_by(Plugin.slug.asc())
            .all()
        )
        counts = dict(
            db.query(Bulletin.source_slug, func.count(Bulletin.id))
            .group_by(Bulletin.source_slug)
            .all()
        )

        display_tz_label = get_display_timezone_label()

        def fmt(dt: Optional[datetime]) -> Optional[str]:
            return format_display(dt, pattern="%Y-%m-%d %H:%M")

        plugins_payload: list[dict[str, object]] = []
        active = 0
        failed = 0
        total_collected = 0
        for plugin in plugin_rows:
            current = plugin.current_version
            latest = current or (plugin.versions[0] if plugin.versions else None)
            status = (latest.status if latest else "uploaded") or "uploaded"
            is_running = bool(plugin.is_enabled and current and current.is_active)
            if is_running:
                active += 1
            if any(version.status == "failed" for version in plugin.versions):
                failed += 1

            def status_display() -> str:
                if not plugin.is_enabled:
                    return "已禁用"
                return {
                    "active": "运行中",
                    "inactive": "已停用",
                    "failed": "运行异常",
                    "uploaded": "待激活",
                    "disabled": "已禁用",
                }.get(status, status)

            collected = counts.get(plugin.slug, 0)
            total_collected += collected
            plugins_payload.append(
                {
                    "id": plugin.id,
                    "slug": plugin.slug,
                    "name": plugin.display_name or plugin.name,
                    "version": latest.version if latest else "—",
                    "status": status,
                    "status_display": status_display(),
                    "is_active": is_running,
                    "schedule": (current.schedule if current else latest.schedule if latest else None) or "—",
                    "last_run_at": fmt(current.last_run_at if current else None) or "—",
                    "next_run_at": fmt(current.next_run_at if current else None) or "—",
                    "created_at": fmt(plugin.created_at) or "—",
                    "total_items": collected,
                    "group_title": plugin.group_title,
                }
            )

        summary = [
            {"label": "总插件数", "value": len(plugin_rows)},
            {"label": "已激活", "value": active},
            {"label": "运行异常", "value": failed},
            {"label": "采集总量", "value": total_collected},
        ]

        return templates.TemplateResponse(
            request=request,
            name="plugins.html",
            context={
                "title": "插件运行监控",
                "header": "插件运行监控",
                "summary": summary,
                "plugins": plugins_payload,
                "page_id": "plugins-dashboard",
                "display_tz_label": display_tz_label,
                "is_admin": bool(current_user and current_user.is_admin),
            },
        )

    @app.get("/dashboard/plugins/{slug}", response_class=HTMLResponse, tags=["pages"])
    def plugin_detail_page(
        slug: str,
        request: Request,
        current_user: models.User | None = Depends(get_optional_user),
        db: Session = Depends(get_db_session),
    ) -> HTMLResponse:
        plugin = (
            db.query(Plugin)
            .options(
                selectinload(Plugin.current_version),
                selectinload(Plugin.versions),
                selectinload(Plugin.runs),
            )
            .filter(Plugin.slug == slug)
            .first()
        )
        if plugin is None:
            raise HTTPException(status_code=404, detail="Plugin not found")

        display_tz_label = get_display_timezone_label()

        def fmt(dt: Optional[datetime]) -> Optional[str]:
            return format_display(dt, pattern="%Y-%m-%d %H:%M")

        fallback_dt = datetime.min.replace(tzinfo=timezone.utc)
        versions_sorted = sorted(
            plugin.versions,
            key=lambda version: version.created_at or fallback_dt,
            reverse=True,
        )

        current_version = plugin.current_version or (versions_sorted[0] if versions_sorted else None)
        manifest = current_version.manifest if current_version and current_version.manifest else None
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2) if manifest else None

        versions_payload: list[dict[str, object]] = []
        for version in versions_sorted:
            versions_payload.append(
                {
                    "id": version.id,
                    "version": version.version,
                    "status": version.status,
                    "is_active": version.is_active,
                    "schedule": version.schedule or "未配置",
                    "created_at": fmt(version.created_at) or "—",
                    "activated_at": fmt(version.activated_at) or "—",
                    "last_run_at": fmt(version.last_run_at) or "—",
                    "next_run_at": fmt(version.next_run_at) or "—",
                }
            )

        current_created_at = (
            (current_version.created_at or fallback_dt) if current_version else fallback_dt
        )
        pending_candidate = next(
            (
                version
                for version in versions_sorted
                if version.status == "uploaded"
                and (version.created_at or fallback_dt) > current_created_at
            ),
            None,
        )
        pending_version_payload = (
            {
                "id": pending_candidate.id,
                "version": pending_candidate.version,
                "status": pending_candidate.status,
                "created_at": fmt(pending_candidate.created_at) or "—",
                "schedule": pending_candidate.schedule or "未配置",
            }
            if pending_candidate
            else None
        )

        runs_payload: list[dict[str, object]] = []
        for run in sorted(plugin.runs, key=lambda r: r.started_at, reverse=True)[:10]:
            summary: dict[str, object] = {}
            if run.output:
                try:
                    summary = json.loads(run.output)
                except (TypeError, json.JSONDecodeError):
                    summary = {}
            runs_payload.append(
                {
                    "status": run.status,
                    "started_at": fmt(run.started_at) or "—",
                    "finished_at": fmt(run.finished_at) or "—",
                    "message": run.message,
                    "collected": summary.get("collected"),
                    "accepted": summary.get("accepted"),
                    "duplicates": summary.get("duplicates"),
                }
            )

        total_items = (
            db.query(func.count(Bulletin.id))
            .filter(Bulletin.source_slug == plugin.slug)
            .scalar()
        ) or 0

        trend_days = 30
        display_tz = get_display_timezone()
        now_local = datetime.now(display_tz)
        start_local = (now_local - timedelta(days=trend_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(timezone.utc)

        raw_fetched = (
            db.query(Bulletin.fetched_at)
            .filter(Bulletin.source_slug == plugin.slug)
            .filter(Bulletin.fetched_at.isnot(None))
            .filter(Bulletin.fetched_at >= start_utc)
            .all()
        )
        fetched_datetimes = [value[0] for value in raw_fetched if value and value[0]]

        trend_counts: OrderedDict[str, int] = OrderedDict()
        for offset in range(trend_days):
            day = (start_local + timedelta(days=offset)).date()
            trend_counts[day.isoformat()] = 0

        for fetched_at in fetched_datetimes:
            local_dt = to_display_tz(fetched_at)
            day_key = local_dt.date().isoformat()
            trend_counts[day_key] = trend_counts.get(day_key, 0) + 1

        trend_series = [{"date": date, "count": count} for date, count in trend_counts.items()]

        recent_bulletins = (
            db.query(Bulletin)
            .filter(Bulletin.source_slug == plugin.slug)
            .order_by(Bulletin.published_at.desc().nullslast(), Bulletin.id.desc())
            .limit(10)
            .all()
        )

        display_title = plugin.display_name or plugin.name
        page_title = f"{display_title} · SecLens"

        return templates.TemplateResponse(
            request=request,
            name="plugin_detail.html",
            context={
                "title": page_title,
                "header": display_title,
                "plugin": plugin,
                "current_version": current_version,
                "manifest": manifest,
                "manifest_json": manifest_json,
                "versions": versions_payload,
                "runs": runs_payload,
                "total_items": total_items,
                "trend_series": trend_series,
                "trend_window_days": trend_days,
                "recent_bulletins": recent_bulletins,
                "page_id": "plugin-detail",
                "is_admin": bool(current_user and current_user.is_admin),
                "pending_version": pending_version_payload,
                "display_tz_label": display_tz_label,
            },
        )

    @app.get("/bulletins/{bulletin_id}", response_class=HTMLResponse, tags=["pages"])
    def bulletin_detail(bulletin_id: int, request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
        bulletin = crud.get_bulletin(db, bulletin_id)
        if not bulletin:
            raise HTTPException(status_code=404, detail="Bulletin not found")
        bulletin_data = BulletinOut.model_validate(bulletin)
        plugin_exists = (
            db.query(Plugin.slug).filter(Plugin.slug == bulletin_data.source_slug).first() is not None
        )
        return templates.TemplateResponse(
            request=request,
            name="detail.html",
            context={
                "title": bulletin_data.title,
                "header": "情报详情",
                "bulletin": bulletin_data,
                "plugin_exists": plugin_exists,
                "page_id": "bulletin-detail",
            },
        )

    return app


app = create_app()
