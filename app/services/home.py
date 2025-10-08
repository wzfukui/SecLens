"""Homepage aggregation helpers."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
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
    groups: Dict[str, Dict[str, Any]] = {}

    for config in _iter_source_configs(db):
        items, total = crud.list_bulletins(
            db,
            source_slug=config["slug"],
            limit=limit_per_source,
        )
        if total == 0:
            continue
        group = groups.setdefault(
            config["group_slug"],
            {
                "slug": config["group_slug"],
                "title": config["group_title"],
                "description": config["group_description"],
                "order": config["group_order"],
                "sources": [],
            },
        )
        group["sources"].append(
            {
                "slug": config["slug"],
                "title": config["title"],
                "order": config["source_order"],
                "total": total,
                "items": [BulletinOut.model_validate(item) for item in items],
            }
        )

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
RESOURCES_DIR = Path(__file__).resolve().parents[2] / "resources"


def _load_resource_ui_configs() -> Dict[str, dict[str, Any]]:
    configs: Dict[str, dict[str, Any]] = {}
    if not RESOURCES_DIR.exists():
        return configs
    for manifest_path in RESOURCES_DIR.glob("*/manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        slug = data.get("slug")
        ui = data.get("ui")
        if not slug or not isinstance(ui, dict):
            continue
        configs[slug] = {
            "group_slug": ui.get("group_slug"),
            "group_title": ui.get("group_title"),
            "group_description": ui.get("group_description"),
            "group_order": ui.get("group_order"),
            "source_title": ui.get("source_title") or data.get("name", slug),
            "source_order": ui.get("source_order"),
        }
    return configs


def _iter_source_configs(db: Session) -> list[dict[str, Any]]:
    resource_map = _load_resource_ui_configs()
    configs: list[dict[str, Any]] = []
    seen: set[str] = set()

    plugins = (
        db.query(Plugin)
        .order_by(
            Plugin.group_order.is_(None),
            Plugin.group_order.asc(),
            Plugin.group_title.is_(None),
            Plugin.group_title.asc(),
            Plugin.source_order.is_(None),
            Plugin.source_order.asc(),
            Plugin.slug.asc(),
        )
        .all()
    )

    for plugin in plugins:
        slug = plugin.slug
        seen.add(slug)
        resource_cfg = resource_map.get(slug, {})
        group_slug = plugin.group_slug or resource_cfg.get("group_slug")
        if not group_slug:
            continue
        configs.append(
            {
                "slug": slug,
                "title": plugin.display_name or resource_cfg.get("source_title") or plugin.name,
                "group_slug": group_slug,
                "group_title": plugin.group_title or resource_cfg.get("group_title") or group_slug,
                "group_description": plugin.group_description or resource_cfg.get("group_description") or "",
                "group_order": plugin.group_order if plugin.group_order is not None else resource_cfg.get("group_order"),
                "source_order": plugin.source_order if plugin.source_order is not None else resource_cfg.get("source_order"),
            }
        )

    for slug, cfg in resource_map.items():
        if slug in seen:
            continue
        group_slug = cfg.get("group_slug")
        if not group_slug:
            continue
        configs.append(
            {
                "slug": slug,
                "title": cfg.get("source_title") or slug,
                "group_slug": group_slug,
                "group_title": cfg.get("group_title") or group_slug,
                "group_description": cfg.get("group_description") or "",
                "group_order": cfg.get("group_order"),
                "source_order": cfg.get("source_order"),
            }
        )

    return configs
