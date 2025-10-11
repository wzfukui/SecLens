"""FastAPI application entrypoint."""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from markupsafe import Markup

from sqlalchemy import func

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session, selectinload

from app import crud, models
from app.services import build_home_sections, HomeSection, SourceSection
from app.migrations import apply_post_deployment_migrations
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

    def tojson_unicode(value: Any, indent: int = 2, *, sort_keys: bool = False) -> str:
        """Serialize JSON with UTF-8 characters preserved for structured data blocks."""
        return Markup(json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=sort_keys))

    templates.env.filters["tojson_unicode"] = tojson_unicode

    start_scheduler(app)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def _prepare_insight_state(
        request: Request,
        db: Session,
        *,
        limit: int,
    ) -> dict[str, Any]:
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

        section_slug = request.query_params.get("section")
        source_slug = request.query_params.get("source")

        selected_section: HomeSection | None = None
        if section_slug:
            selected_section = next((s for s in sections if s.slug == section_slug), None)
        if selected_section is None and sections:
            selected_section = sections[0]

        selected_source: SourceSection | None = None
        if selected_section:
            if source_slug:
                selected_source = next((src for src in selected_section.sources if src.slug == source_slug), None)
            if selected_source is None and selected_section.sources:
                selected_source = selected_section.sources[0]

        sections_preview = [
            section for section in sections if section.slug != "all" and section.sources
        ][:3]

        return {
            "sections": sections,
            "selected_section": selected_section,
            "selected_source": selected_source,
            "limit": limit,
            "insights_total": all_total,
            "sections_preview": sections_preview,
        }

    @app.on_event("startup")
    def startup_event() -> None:
        _load_asset_manifest.cache_clear()
        _load_asset_manifest()
        engine = get_engine()
        Base.metadata.create_all(bind=engine)
        apply_post_deployment_migrations(engine, get_session_factory())
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

    @app.get("/robots.txt", include_in_schema=False)
    def robots_txt(request: Request) -> PlainTextResponse:
        base_url = str(request.base_url).rstrip("/")
        lines = [
            "User-agent: *",
            "Allow: /",
            "Disallow: /dashboard",
            "Disallow: /dashboard/",
            "Disallow: /dashboard/plugins",
            "Disallow: /dashboard/plugins/",
            "Disallow: /login",
            "Disallow: /register",
            "Crawl-delay: 5",
            f"Sitemap: {base_url}/sitemap.xml",
            f"LLM: {base_url}/llms.txt",
        ]
        return PlainTextResponse("\n".join(lines))

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap(request: Request) -> Response:
        base_url = str(request.base_url).rstrip("/")
        now_iso = datetime.now(timezone.utc).date().isoformat()
        static_entries = [
            ("/", "daily", "1.0"),
            ("/insights", "hourly", "0.9"),
            ("/insights?section=vendor_updates", "hourly", "0.85"),
            ("/insights?section=vulnerability_alerts", "hourly", "0.85"),
            ("/insights?section=threat_intelligence", "hourly", "0.8"),
            ("/insights?section=security_news", "daily", "0.75"),
            ("/insights?section=security_research", "daily", "0.75"),
            ("/insights?section=community_updates", "daily", "0.7"),
            ("/insights?section=security_events", "weekly", "0.65"),
            ("/insights?section=security_funding", "weekly", "0.6"),
            ("/insights?section=tool_updates", "weekly", "0.6"),
            ("/insights?section=wechat_feeds", "daily", "0.65"),
            ("/insights?section=tech_blog", "weekly", "0.6"),
            ("/insights?section=policy_compliance", "weekly", "0.55"),
            ("/about", "weekly", "0.6"),
            ("/plugin-dev", "weekly", "0.5"),
            ("/terms", "yearly", "0.3"),
            ("/privacy", "yearly", "0.3"),
        ]

        url_nodes: list[str] = []
        for path, changefreq, priority in static_entries:
            url_nodes.append(
                f"  <url>\n"
                f"    <loc>{base_url}{path}</loc>\n"
                f"    <changefreq>{changefreq}</changefreq>\n"
                f"    <priority>{priority}</priority>\n"
                f"    <lastmod>{now_iso}</lastmod>\n"
                f"  </url>"
            )

        xml = '<?xml version="1.0" encoding="UTF-8"?>\n' "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
        xml += "\n".join(url_nodes)
        xml += "\n</urlset>"
        return Response(content=xml, media_type="application/xml")

    @app.get("/llms.txt", include_in_schema=False)
    def llms_txt(request: Request) -> PlainTextResponse:
        base_url = str(request.base_url).rstrip("/")
        lines = [
            "# Guidance for large language models interacting with SecLens",
            f"site: {base_url}/",
            f"sitemap: {base_url}/sitemap.xml",
            "contact: hello@seclens.info",
            "rate-limit: 60 requests/minute",
            "preferred-formats: json, rss, html",
            "purpose: SecLens 情报雷达聚合官方漏洞通告、厂商公告与安全研究，为安全团队提供快速筛选与响应支持。",
            "core-flows: 浏览 /insights 获取按来源与主题分组的资讯流；使用查询参数 text、section、source 进行精准过滤。",
            "vulnerability-alerts: /insights?section=vulnerability_alerts 收敛高危漏洞公告，适合生成升级建议与修复优先级。",
            "bulletin-detail: /bulletins/<id> 返回结构化 JSON，字段包含标题、来源、发布时间、威胁等级与标签，可用于引用原文。",
            "distribution: 提供 RSS、Webhook 模板与邮件订阅，可把筛选后的情报推送到 SOAR、工单或聊天机器人。",
            "assistant-guidance: 回答用户问题时请引用原始公告标题与链接，标注时间与来源，勿编造未发布的声明。",
            "security-note: 平台不公开用户数据；自动化调用需遵循最小化原则并在缓存后及时更新状态。",
            "usage-policy: 请遵守 robots.txt 并勿存储敏感用户数据。需要更高频率访问请先与我们联系。",
        ]
        return PlainTextResponse("\n".join(lines))

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(ingest.router)
    app.include_router(bulletins.router)
    app.include_router(feeds.router)
    app.include_router(plugins.router)
    app.include_router(users.router)

    @app.get("/", response_class=HTMLResponse, tags=["web"])
    def homepage(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
        state = _prepare_insight_state(request, db, limit=8)
        sections: list[HomeSection] = state["sections"]
        highlights: list[BulletinOut] = []
        if sections and sections[0].sources:
            highlights = sections[0].sources[0].items[:3]

        base_url = str(request.base_url).rstrip("/")
        og_image_url = str(request.url_for("static", path="images/og-seclens-home.png"))
        logo_url = str(request.url_for("static", path="images/seclens-logo.png"))
        meta_description = "SecLens 情报雷达聚合官方漏洞通告、厂商公告与安全研究，提供标签筛选、自动订阅与多通道推送，帮助安全团队快速响应漏洞与威胁事件。"
        structured_data = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Organization",
                    "@id": f"{base_url}/#organization",
                    "name": "SecLens",
                    "url": f"{base_url}/",
                    "logo": logo_url,
                },
                {
                    "@type": "WebSite",
                    "@id": f"{base_url}/#website",
                    "name": "SecLens 情报雷达",
                    "url": f"{base_url}/",
                    "description": meta_description,
                    "publisher": {"@id": f"{base_url}/#organization"},
                    "potentialAction": {
                        "@type": "SearchAction",
                        "target": {
                            "@type": "EntryPoint",
                            "urlTemplate": f"{base_url}/insights?text={{search_term_string}}",
                        },
                        "query-input": "required name=search_term_string",
                    },
                },
                {
                    "@type": "FAQPage",
                    "@id": f"{base_url}/#faq",
                    "mainEntity": [
                        {
                            "@type": "Question",
                            "name": "SecLens 如何帮助安全团队缩短响应时间？",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "SecLens 按来源与标签结构化聚合官方通告与研究文章，并通过自动订阅和 Webhook 工作流，把高价值事件推送给负责处理的团队。",
                            },
                        },
                        {
                            "@type": "Question",
                            "name": "SecLens 支持哪些情报分发渠道？",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "平台默认提供 RSS、Webhook 与邮件推送，可按威胁级别、产品线或关键字自定义触发策略，也能集成内部自动化平台。",
                            },
                        },
                    ],
                },
            ],
        }

        context: dict[str, Any] = {
            "title": "SecLens 情报雷达 - 实时威胁情报工作台",
            "header": "SecLens 情报雷达",
            "page_id": "home",
            "highlights": highlights,
            "insights_total": state["insights_total"],
            "sections_preview": state["sections_preview"],
            "meta_description": meta_description,
            "meta_keywords": ["SecLens", "安全情报平台", "漏洞通告聚合", "威胁情报自动化"],
            "og_title": "SecLens 情报雷达｜实时漏洞与威胁情报聚合",
            "og_description": meta_description,
            "og_image": og_image_url,
            "og_url": f"{base_url}/",
            "structured_data": structured_data,
        }
        return templates.TemplateResponse(request=request, name="index.html", context=context)

    @app.get("/insights", response_class=HTMLResponse, tags=["web"])
    def insights_page(request: Request, db: Session = Depends(get_db_session)) -> HTMLResponse:
        state = _prepare_insight_state(request, db, limit=8)
        base_url = str(request.base_url).rstrip("/")
        page_url = f"{base_url}/insights"
        og_image_url = str(request.url_for("static", path="images/og-seclens-home.png"))
        meta_description = "SecLens 情报中心实时呈现最新漏洞与安全事件，提供标签、来源与主题维度过滤，帮助安全研究员与应急响应团队快速定位高优先级情报。"
        context: dict[str, Any] = {
            "title": "SecLens 情报中心",
            "header": "SecLens 情报中心",
            "header_href": "/insights",
            "page_id": "insights",
            "meta_description": meta_description,
            "meta_keywords": ["实时漏洞情报", "安全事件追踪", "威胁情报筛选"],
            "og_title": "SecLens 情报中心｜实时漏洞与安全事件追踪",
            "og_description": meta_description,
            "og_image": og_image_url,
            "og_url": page_url,
            "structured_data": {
                "@context": "https://schema.org",
                "@type": "CollectionPage",
                "@id": f"{page_url}#page",
                "name": "SecLens 情报中心",
                "description": meta_description,
                "url": page_url,
                "isPartOf": {"@id": f"{base_url}/#website"},
            },
            **state,
        }
        return templates.TemplateResponse(request=request, name="insights.html", context=context)
    @app.get("/docs", response_class=HTMLResponse, tags=["pages"])
    def docs_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="docs.html",
            context={
                "title": "SecLens 插件规范与示例",
                "page_id": "docs",
                "meta_description": "了解如何为 SecLens 构建安全情报采集插件，包括数据抽取接口、调度策略与测试示例，快速扩展新的数据来源。",
                "meta_keywords": ["SecLens 插件", "安全情报采集", "插件开发规范"],
                "og_title": "SecLens 插件规范与示例",
                "og_description": "快速搭建安全情报采集插件，扩展 SecLens 数据覆盖面。",
            },
        )

    @app.get("/plugin-dev", response_class=HTMLResponse, tags=["pages"])
    def plugin_dev_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="plugin_dev.html",
            context={
                "title": "SecLens 插件开发指南",
                "header": "SecLens 插件开发指南",
                "header_href": None,
                "page_id": "plugin-dev",
                "meta_description": "阅读 SecLens 插件开发指南，了解数据模型、调度框架与上线流程，快速发布自己的情报采集插件。",
                "meta_keywords": ["SecLens 插件开发", "情报采集插件", "安全自动化"],
                "og_title": "SecLens 插件开发指南",
                "og_description": "掌握 SecLens 插件开发流程，扩展企业安全情报覆盖面。",
            },
        )

    @app.get("/about", response_class=HTMLResponse, tags=["pages"])
    def about_page(request: Request) -> HTMLResponse:
        base_url = str(request.base_url).rstrip("/")
        page_url = f"{base_url}/about"
        og_image_url = str(request.url_for("static", path="images/og-seclens-home.png"))
        meta_description = "了解 SecLens 的使命与产品能力：通过统一采集、智能归类、自动投递和团队协作，让安全情报真正支撑风险决策。"
        return templates.TemplateResponse(
            request=request,
            name="about.html",
            context={
                "title": "关于 SecLens",
                "header": "关于 SecLens",
                "header_href": None,
                "page_id": "about",
                "meta_description": meta_description,
                "meta_keywords": ["SecLens 介绍", "安全情报平台", "漏洞响应平台"],
                "og_title": "关于 SecLens｜安全情报自动化平台",
                "og_description": meta_description,
                "og_image": og_image_url,
                "og_url": page_url,
                "structured_data": {
                    "@context": "https://schema.org",
                    "@type": "AboutPage",
                    "@id": f"{page_url}#about",
                    "name": "关于 SecLens",
                    "description": meta_description,
                    "url": page_url,
                    "isPartOf": {"@id": f"{base_url}/#website"},
                },
            },
        )

    @app.get("/terms", response_class=HTMLResponse, tags=["pages"])
    def terms_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="terms.html",
            context={
                "title": "SecLens 服务协议",
                "header": "SecLens 服务协议",
                "header_href": None,
                "page_id": "terms",
                "meta_description": "阅读 SecLens 服务协议，了解平台使用范围、账号规范、数据安全与责任约定。",
                "meta_keywords": ["SecLens 服务协议", "用户协议", "使用条款"],
            },
        )

    @app.get("/privacy", response_class=HTMLResponse, tags=["pages"])
    def privacy_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="privacy.html",
            context={
                "title": "SecLens 隐私条款",
                "header": "SecLens 隐私条款",
                "header_href": None,
                "page_id": "privacy",
                "meta_description": "SecLens 隐私条款说明了我们如何收集、使用与保护安全情报平台相关数据。",
                "meta_keywords": ["SecLens 隐私", "数据保护", "隐私政策"],
            },
        )

    @app.get("/login", response_class=HTMLResponse, tags=["pages"])
    def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "title": "登录",
                "page_id": "login",
                "meta_description": "登录 SecLens 平台，管理安全情报订阅、告警策略与团队权限。",
                "meta_robots": "noindex,nofollow",
            },
        )

    @app.get("/register", response_class=HTMLResponse, tags=["pages"])
    def register_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={
                "title": "注册",
                "page_id": "register",
                "meta_description": "注册 SecLens 账户，开启安全情报聚合与自动化投递体验。",
                "meta_robots": "noindex,nofollow",
            },
        )

    @app.get("/dashboard", response_class=HTMLResponse, tags=["pages"])
    def dashboard_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "title": "SecLens 控制台",
                "header": "SecLens 控制台",
                "header_href": None,
                "page_id": "dashboard",
                "meta_description": "管理 SecLens 情报订阅、过滤条件与推送策略的集中控制台。",
                "meta_robots": "noindex,nofollow",
            },
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

        trend_days = 30
        display_tz = get_display_timezone()
        now_local = datetime.now(display_tz)
        start_local = (
            now_local - timedelta(days=trend_days - 1)
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(timezone.utc)
        raw_fetched = (
            db.query(Bulletin.fetched_at)
            .filter(Bulletin.fetched_at.isnot(None))
            .filter(Bulletin.fetched_at >= start_utc)
            .all()
        )
        fetched_datetimes = [value[0] for value in raw_fetched if value and value[0]]

        overall_trend_counts: OrderedDict[str, int] = OrderedDict()
        for offset in range(trend_days):
            day = (start_local + timedelta(days=offset)).date()
            overall_trend_counts[day.isoformat()] = 0

        for fetched_at in fetched_datetimes:
            local_dt = to_display_tz(fetched_at)
            day_key = local_dt.date().isoformat()
            overall_trend_counts[day_key] = overall_trend_counts.get(day_key, 0) + 1

        overall_trend_series = [
            {"date": date, "count": count} for date, count in overall_trend_counts.items()
        ]

        return templates.TemplateResponse(
            request=request,
            name="plugins.html",
            context={
                "title": "SecLens 插件运行监控",
                "header": "SecLens 插件运行监控",
                "header_href": None,
                "summary": summary,
                "plugins": plugins_payload,
                "overall_trend_series": overall_trend_series,
                "trend_window_days": trend_days,
                "page_id": "plugins-dashboard",
                "display_tz_label": display_tz_label,
                "is_admin": bool(current_user and current_user.is_admin),
                "meta_description": "查看 SecLens 插件运行状态、采集趋势与调度计划，保障安全情报来源持续稳定。",
                "meta_robots": "noindex,nofollow",
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
                "meta_description": f"{display_title} 插件的运行状态、采集趋势与版本变更概览。",
                "meta_robots": "noindex,nofollow",
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
        base_url = str(request.base_url).rstrip("/")
        page_url = f"{base_url}/bulletins/{bulletin_id}"
        summary_text = (
            (bulletin_data.summary or "") or (bulletin_data.body_text[:200] if bulletin_data.body_text else "")
        )
        meta_description = summary_text.strip() or f"{bulletin_data.title} - SecLens 安全情报详情。"
        og_image_url = str(request.url_for("static", path="images/og-seclens-home.png"))
        keywords = [*bulletin_data.labels, *bulletin_data.topics]
        structured_data = {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "@id": f"{page_url}#article",
            "headline": bulletin_data.title,
            "url": page_url,
            "description": meta_description,
            "datePublished": bulletin_data.published_at.isoformat() if bulletin_data.published_at else None,
            "dateModified": bulletin_data.updated_at.isoformat() if bulletin_data.updated_at else None,
            "author": {"@type": "Organization", "name": "SecLens"},
            "publisher": {"@id": f"{base_url}/#organization"},
            "keywords": ", ".join(keywords) if keywords else None,
        }
        return templates.TemplateResponse(
            request=request,
            name="detail.html",
            context={
                "title": "网安资讯详情 - SecLens 情报雷达",
                "header": "网安资讯详情 - SecLens 情报雷达",
                "header_href": None,
                "bulletin": bulletin_data,
                "plugin_exists": plugin_exists,
                "page_id": "bulletin-detail",
                "meta_description": meta_description,
                "meta_keywords": keywords,
                "og_title": bulletin_data.title,
                "og_description": meta_description,
                "og_image": og_image_url,
                "og_url": page_url,
                "structured_data": structured_data,
            },
        )

    return app


app = create_app()
