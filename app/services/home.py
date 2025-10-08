"""Homepage aggregation helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from sqlalchemy.orm import Session

from app import crud
from app.catalog import HOME_SECTIONS
from app.models import Plugin
from app.schemas import BulletinOut


@dataclass
class SourceSection:
    slug: str
    title: str
    total: int
    items: list[BulletinOut]


@dataclass
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


def _build_plugin_sections(db: Session, limit_per_source: int) -> list[HomeSection]:
    plugins = (
        db.query(Plugin)
        .filter(Plugin.group_slug.isnot(None))
        .order_by(
            Plugin.group_order.is_(None),
            Plugin.group_order.asc(),
            Plugin.group_title.is_(None),
            Plugin.group_title.asc(),
            Plugin.slug.asc(),
        )
        .all()
    )

    groups: Dict[str, Dict[str, Any]] = {}

    for plugin in plugins:
        if not plugin.group_slug:
            continue
        group = groups.setdefault(
            plugin.group_slug,
            {
                "slug": plugin.group_slug,
                "title": plugin.group_title or plugin.group_slug,
                "description": plugin.group_description or "",
                "order": plugin.group_order,
                "sources": [],
            },
        )

        items, total = crud.list_bulletins(
            db,
            source_slug=plugin.slug,
            limit=limit_per_source,
        )
        source_entry = {
            "slug": plugin.slug,
            "title": plugin.display_name or plugin.name,
            "order": plugin.source_order,
            "total": total,
            "items": [BulletinOut.model_validate(item) for item in items],
        }
        group["sources"].append(source_entry)

    sections: list[HomeSection] = []
    for data in sorted(
        groups.values(),
        key=lambda value: (
            value["order"] is None,
            value["order"],
            value["title"],
        ),
    ):
        sources = [
            SourceSection(
                slug=entry["slug"],
                title=entry["title"],
                total=entry["total"],
                items=entry["items"],
            )
            for entry in sorted(
                data["sources"],
                key=lambda entry: (
                    entry["order"] is None,
                    entry["order"],
                    entry["title"],
                ),
            )
        ]
        sections.append(
            HomeSection(
                slug=data["slug"],
                title=data["title"],
                description=data["description"],
                sources=sources,
            )
        )
    return sections


def _build_static_sections(db: Session, limit_per_source: int, existing_slugs: set[str]) -> list[HomeSection]:
    sections: list[HomeSection] = []
    for section_cfg in HOME_SECTIONS:
        if section_cfg["slug"] in existing_slugs:
            continue
        sources_cfg: list[dict[str, Any]] = section_cfg.get("topics", [])  # type: ignore[assignment]
        if not sources_cfg:
            sources_cfg = section_cfg.get("labels", [])  # type: ignore[assignment]

        source_sections: list[SourceSection] = []
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


def build_home_sections(db: Session, *, limit_per_source: int = 5) -> list[HomeSection]:
    """Aggregate bulletins into homepage sections driven by plugin metadata and static topics."""

    sections: list[HomeSection] = []
    plugin_sections = _build_plugin_sections(db, limit_per_source)
    sections.extend(plugin_sections)
    existing = {section.slug for section in plugin_sections}
    sections.extend(_build_static_sections(db, limit_per_source, existing))
    return sections


__all__ = ["build_home_sections", "HomeSection", "SourceSection"]
