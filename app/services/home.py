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


def build_home_sections(db: Session, *, limit_per_source: int = 5) -> list[HomeSection]:
    """Aggregate bulletins into predefined home sections."""

    sections: list[HomeSection] = []
    for section_cfg in HOME_SECTIONS:
        sources_cfg: list[dict[str, Any]] = section_cfg.get("sources", [])  # type: ignore[assignment]
        source_sections: list[SourceSection] = []
        for source in sources_cfg:
            slug = source["slug"]
            title = source.get("title", slug)
            items, total = crud.list_bulletins(db, source_slug=slug, limit=limit_per_source)
            source_sections.append(
                SourceSection(
                    slug=slug,
                    title=title,
                    total=total,
                    items=[BulletinOut.model_validate(item) for item in items],
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
