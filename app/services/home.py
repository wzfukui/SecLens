"""Homepage aggregation helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app import crud
from app.catalog import HOME_SECTIONS
from app.schemas import BulletinOut


@dataclass(slots=True)
class SourceSection:
    slug: str
    title: str
    total: int
    items: list[BulletinOut]


@dataclass(slots=True)
class HomeSection:
    slug: str
    title: str
    description: str
    sources: list[SourceSection]


def _resolve_source_slug(config: dict[str, Any], *, fallback_prefix: str) -> str:
    slug = config.get("slug")
    if slug:
        return slug
    topic = config.get("topic")
    if topic:
        return f"topic:{topic}"
    label = config.get("label")
    if label:
        return f"label:{label}"
    return f"{fallback_prefix}:{id(config)}"


def _list_source_bulletins(
    db: Session,
    config: dict[str, Any],
    *,
    limit: int,
) -> tuple[list[BulletinOut], int]:
    filters: dict[str, Any] = {}
    if slug := config.get("slug"):
        filters["source_slug"] = slug
    if topic := config.get("topic"):
        filters["topic"] = topic
    if label := config.get("label"):
        filters["label"] = label
    if text := config.get("text"):
        filters["text"] = text

    if not filters:
        return [], 0

    items, total = crud.list_bulletins(db, limit=limit, **filters)
    return [BulletinOut.model_validate(item) for item in items], total


def build_home_sections(db: Session, *, limit_per_source: int = 5) -> list[HomeSection]:
    """Aggregate bulletins into predefined home sections."""

    sections: list[HomeSection] = []
    for section_cfg in HOME_SECTIONS:
        sources_cfg: list[dict[str, Any]] = section_cfg.get("sources", [])  # type: ignore[assignment]
        source_sections: list[SourceSection] = []
        if not sources_cfg:
            sources_cfg = section_cfg.get("topics", [])  # type: ignore[assignment]
        if not sources_cfg:
            sources_cfg = section_cfg.get("labels", [])  # type: ignore[assignment]

        for source_cfg in sources_cfg:
            if not isinstance(source_cfg, dict):
                continue
            slug = _resolve_source_slug(source_cfg, fallback_prefix=section_cfg["slug"])
            title = source_cfg.get("title") or slug
            items, total = _list_source_bulletins(db, source_cfg, limit=limit_per_source)
            source_sections.append(
                SourceSection(
                    slug=slug,
                    title=title,
                    total=total,
                    items=items,
                )
            )
        sections.append(
            HomeSection(
                slug=section_cfg["slug"],
                title=section_cfg["title"],
                description=section_cfg.get("description", ""),
                sources=source_sections,
            )
        )
    return sections


__all__ = ["build_home_sections", "HomeSection", "SourceSection"]
