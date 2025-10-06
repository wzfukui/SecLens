from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models
from app.database import Base
from app.services.home import build_home_sections


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _add_bulletin(session: Session, *, source: str, topics: list[str] | None = None, labels: list[str] | None = None) -> None:
    bulletin = models.Bulletin(
        source_slug=source,
        external_id=f"{source}-{datetime.now(timezone.utc).timestamp()}",
        title=f"{source} bulletin",
        summary="summary",
        body_text="body",
        published_at=datetime.now(timezone.utc),
        topics=topics,
        labels=labels,
    )
    session.add(bulletin)
    session.commit()


def test_build_home_sections_aggregates_by_topic(monkeypatch) -> None:
    session = _make_session()
    _add_bulletin(session, source="source-a", topics=["security-news"])
    _add_bulletin(session, source="source-b", topics=["security-news", "community-update"])

    custom_catalog = [
        {
            "slug": "security_news",
            "title": "安全新闻",
            "description": "新闻聚合",
            "topics": [
                {"topic": "security-news", "title": "新闻聚焦"},
                {"topic": "community-update", "title": "社区"},
            ],
        }
    ]
    monkeypatch.setattr("app.services.home.HOME_SECTIONS", custom_catalog, raising=False)

    sections = build_home_sections(session, limit_per_source=5)
    assert len(sections) == 1
    news_section = sections[0]
    assert news_section.sources[0].slug == "topic:security-news"
    assert news_section.sources[0].total == 2
    assert news_section.sources[1].slug == "topic:community-update"
    assert news_section.sources[1].total == 1


def test_build_home_sections_aggregates_by_label(monkeypatch) -> None:
    session = _make_session()
    _add_bulletin(session, source="source-a", labels=["funding", "merger"])

    custom_catalog = [
        {
            "slug": "security_funding",
            "title": "安全融资",
            "description": "融资动态",
            "labels": [
                {"label": "funding", "title": "融资"},
                {"label": "merger", "title": "并购"},
            ],
        }
    ]
    monkeypatch.setattr("app.services.home.HOME_SECTIONS", custom_catalog, raising=False)

    sections = build_home_sections(session, limit_per_source=5)
    assert len(sections[0].sources) == 2
    by_label = {source.slug: source.total for source in sections[0].sources}
    assert by_label["label:funding"] == 1
    assert by_label["label:merger"] == 1
