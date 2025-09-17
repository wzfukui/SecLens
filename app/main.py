"""FastAPI application entrypoint."""
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from app import crud
from app.services import build_home_sections
from app.database import Base, get_db_session, get_engine
from fastapi.responses import HTMLResponse

from app.routers import bulletins, ingest, plugins


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def create_app() -> FastAPI:
    app = FastAPI(title="SecLens Ingest API", version="0.1.0")
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    @app.on_event("startup")
    def startup_event() -> None:
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
        sections = build_home_sections(db, limit_per_source=8)
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
        }
        return templates.TemplateResponse(request=request, name="index.html", context=context)
    @app.get("/docs", response_class=HTMLResponse, tags=["pages"])
    def docs_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="docs.html",
            context={"title": "插件规范与示例"},
        )

    @app.get("/help", response_class=HTMLResponse, tags=["pages"])
    def help_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="help.html",
            context={"title": "平台工作流程"},
        )

    @app.get("/about", response_class=HTMLResponse, tags=["pages"])
    def about_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="about.html",
            context={"title": "关于 SecLens"},
        )

    @app.get("/login", response_class=HTMLResponse, tags=["pages"])
    def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"title": "登录"},
        )

    return app


app = create_app()
