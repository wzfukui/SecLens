"""FastAPI application entrypoint."""
from datetime import datetime, timezone
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from sqlalchemy import func

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session, selectinload

from app import crud
from app.services import build_home_sections, HomeSection, SourceSection
from scripts.scheduler_service import start_scheduler
from app.database import Base, get_db_session, get_engine
from app.schemas import BulletinOut

from app.routers import bulletins, ingest, plugins
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


def create_app() -> FastAPI:
    app = FastAPI(title="SecLens Ingest API", version="0.1.0")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.globals["static_asset_url"] = static_asset_url
    start_scheduler(app)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.on_event("startup")
    def startup_event() -> None:
        _load_asset_manifest.cache_clear()
        _load_asset_manifest()
        engine = get_engine()
        Base.metadata.create_all(bind=engine)

    @app.get("/health", tags=["health"])
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(ingest.router)
    app.include_router(bulletins.router)
    app.include_router(plugins.router)

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

    @app.get("/help", response_class=HTMLResponse, tags=["pages"])
    def help_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="help.html",
            context={"title": "平台工作流程", "page_id": "help"},
        )

    @app.get("/about", response_class=HTMLResponse, tags=["pages"])
    def about_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="about.html",
            context={"title": "关于 SecLens", "page_id": "about"},
        )

    @app.get("/login", response_class=HTMLResponse, tags=["pages"])
    def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"title": "登录", "page_id": "login"},
        )

    @app.get("/dashboard/plugins", response_class=HTMLResponse, tags=["pages"])
    def plugin_dashboard(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
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

        def fmt(dt: Optional[datetime]) -> Optional[str]:
            if not dt:
                return None
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

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
            },
        )

    @app.get("/bulletins/{bulletin_id}", response_class=HTMLResponse, tags=["pages"])
    def bulletin_detail(bulletin_id: int, request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
        bulletin = crud.get_bulletin(db, bulletin_id)
        if not bulletin:
            raise HTTPException(status_code=404, detail="Bulletin not found")
        bulletin_data = BulletinOut.model_validate(bulletin)
        return templates.TemplateResponse(
            request=request,
            name="detail.html",
            context={
                "title": bulletin_data.title,
                "header": "情报详情",
                "bulletin": bulletin_data,
                "page_id": "bulletin-detail",
            },
        )

    return app


app = create_app()
