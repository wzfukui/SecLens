"""API endpoints for plugin management."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.database import get_db_session
from app.models import Plugin, PluginRun, PluginVersion
from app.schemas import (
    PluginActivateRequest,
    PluginInfo,
    PluginListResponse,
    PluginRunInfo,
    PluginUploadRequest,
    PluginVersionInfo,
)
from app.services.plugins import PluginManifest, compute_next_run, extract_plugin_archive
from scripts.scheduler_service import run_plugins_once

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


def _load_plugin(db: Session, plugin_id: int) -> Plugin | None:
    return (
        db.query(Plugin)
        .options(
            selectinload(Plugin.versions),
            selectinload(Plugin.current_version),
        )
        .filter(Plugin.id == plugin_id)
        .first()
    )


def _apply_ui_config(plugin: Plugin, manifest: PluginManifest) -> None:
    ui = manifest.ui or {}
    if ui:
        if "source_title" in ui:
            plugin.display_name = ui.get("source_title") or plugin.display_name
        if "group_slug" in ui:
            plugin.group_slug = ui.get("group_slug") or plugin.group_slug
        if "group_title" in ui:
            plugin.group_title = ui.get("group_title") or plugin.group_title
        if "group_description" in ui:
            plugin.group_description = ui.get("group_description") or plugin.group_description
        if "group_order" in ui:
            plugin.group_order = ui.get("group_order")
        if "source_order" in ui:
            plugin.source_order = ui.get("source_order")
    if not plugin.display_name:
        plugin.display_name = plugin.display_name or manifest.name


def _plugin_to_schema(plugin: Plugin, *, include_versions: bool = True) -> PluginInfo:
    current = (
        PluginVersionInfo.model_validate(plugin.current_version, from_attributes=True)
        if plugin.current_version
        else None
    )
    versions = (
        [
            PluginVersionInfo.model_validate(version, from_attributes=True)
            for version in plugin.versions
        ]
        if include_versions
        else []
    )
    return PluginInfo(
        id=plugin.id,
        slug=plugin.slug,
        name=plugin.name,
        description=plugin.description,
        display_name=plugin.display_name,
        group_slug=plugin.group_slug,
        group_title=plugin.group_title,
        group_description=plugin.group_description,
        group_order=plugin.group_order,
        source_order=plugin.source_order,
        created_at=plugin.created_at,
        updated_at=plugin.updated_at,
        is_enabled=plugin.is_enabled,
        current_version=current,
        versions=versions,
    )


def _manifest_payload(manifest: PluginManifest) -> dict[str, object]:
    return {
        "name": manifest.name,
        "version": manifest.version,
        "slug": manifest.slug,
        "entrypoint": manifest.entrypoint,
        "description": manifest.description,
        "schedule": manifest.schedule,
        "source": manifest.source,
        "runtime": manifest.runtime,
    }


@router.post("/upload", response_model=PluginInfo, status_code=status.HTTP_201_CREATED)
async def upload_plugin(
    payload: PluginUploadRequest,
    db: Session = Depends(get_db_session),
) -> PluginInfo:
    try:
        data = base64.b64decode(payload.content)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 content"
        ) from exc

    try:
        manifest, target_dir = extract_plugin_archive(data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    plugin = (
        db.query(Plugin)
        .options(
            selectinload(Plugin.versions),
            selectinload(Plugin.current_version),
        )
        .filter(Plugin.slug == manifest.slug)
        .first()
    )

    if plugin is None:
        plugin = Plugin(
            slug=manifest.slug,
            name=manifest.name,
            description=manifest.description,
        )
        db.add(plugin)
        db.flush()
    else:
        # Keep metadata in sync with latest upload.
        plugin.name = manifest.name
        plugin.description = manifest.description

    _apply_ui_config(plugin, manifest)

    duplicate = next(
        (version for version in plugin.versions if version.version == manifest.version),
        None,
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plugin version already uploaded",
        )

    version = PluginVersion(
        plugin_id=plugin.id,
        version=manifest.version,
        entrypoint=manifest.entrypoint,
        schedule=manifest.schedule,
        manifest=_manifest_payload(manifest),
        upload_path=str(target_dir),
        status="uploaded",
        is_active=False,
    )

    plugin.versions.append(version)
    plugin.updated_at = datetime.now(timezone.utc)
    db.commit()

    refreshed = _load_plugin(db, plugin.id)
    if refreshed is None:
        raise HTTPException(status_code=500, detail="Failed to load plugin after upload")
    return _plugin_to_schema(refreshed)


@router.get("", response_model=PluginListResponse)
def list_plugins(db: Session = Depends(get_db_session)) -> PluginListResponse:
    plugins = (
        db.query(Plugin)
        .options(
            selectinload(Plugin.versions),
            selectinload(Plugin.current_version),
        )
        .order_by(Plugin.created_at.desc())
        .all()
    )
    return PluginListResponse(items=[_plugin_to_schema(plugin) for plugin in plugins])


@router.post("/{plugin_id}/activate", response_model=PluginInfo)
def activate_plugin(
    plugin_id: int,
    payload: PluginActivateRequest,
    db: Session = Depends(get_db_session),
) -> PluginInfo:
    plugin = _load_plugin(db, plugin_id)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")

    now = datetime.now(timezone.utc)

    if payload.activate:
        if not plugin.versions:
            raise HTTPException(status_code=400, detail="Plugin has no uploaded versions")
        if payload.version_id:
            target = next((v for v in plugin.versions if v.id == payload.version_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="Plugin version not found")
        else:
            target = plugin.current_version or plugin.versions[0]

        if not target.schedule:
            raise HTTPException(status_code=400, detail="Plugin manifest missing schedule")

        for version in plugin.versions:
            if version.id == target.id:
                version.is_active = True
                version.status = "active"
                version.activated_at = now
                version.deactivated_at = None
                version.next_run_at = compute_next_run(
                    version.schedule,
                    reference=now,
                    immediate=True,
                )
            else:
                version.is_active = False
                if version.status == "active":
                    version.status = "inactive"
                version.deactivated_at = now
                version.next_run_at = None

        plugin.current_version = target
        plugin.is_enabled = True
    else:
        plugin.is_enabled = False
        plugin.current_version = None
        for version in plugin.versions:
            version.is_active = False
            if version.status == "active":
                version.status = "inactive"
            version.deactivated_at = now
            version.next_run_at = None

    plugin.updated_at = now
    db.commit()

    refreshed = _load_plugin(db, plugin_id)
    if refreshed is None:
        raise HTTPException(status_code=500, detail="Failed to load plugin after update")
    return _plugin_to_schema(refreshed)


@router.post("/run-once", response_model=PluginListResponse)
def trigger_run_once(db: Session = Depends(get_db_session)) -> PluginListResponse:
    run_plugins_once()
    plugins = (
        db.query(Plugin)
        .options(
            selectinload(Plugin.versions),
            selectinload(Plugin.current_version),
        )
        .order_by(Plugin.created_at.desc())
        .all()
    )
    return PluginListResponse(items=[_plugin_to_schema(plugin) for plugin in plugins])


@router.get("/runs", response_model=list[PluginRunInfo])
def list_plugin_runs(
    limit: int = 20,
    db: Session = Depends(get_db_session),
) -> list[PluginRunInfo]:
    runs = (
        db.query(PluginRun, Plugin.slug, PluginVersion.version)
        .join(Plugin, Plugin.id == PluginRun.plugin_id)
        .outerjoin(PluginVersion, PluginVersion.id == PluginRun.plugin_version_id)
        .order_by(PluginRun.started_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )

    payload: list[PluginRunInfo] = []
    for run, slug, version in runs:
        payload.append(
            PluginRunInfo(
                id=run.id,
                plugin_id=run.plugin_id,
                plugin_slug=slug,
                plugin_version_id=run.plugin_version_id,
                plugin_version=version,
                status=run.status,
                message=run.message,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
        )
    return payload
