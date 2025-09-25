"""API endpoints for plugin management."""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models import Plugin
from app.schemas import PluginActivateRequest, PluginInfo, PluginListResponse, PluginUploadRequest
from app.services.plugins import extract_plugin_archive, compute_next_run

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


@router.post("/upload", response_model=PluginInfo, status_code=status.HTTP_201_CREATED)
async def upload_plugin(
    payload: PluginUploadRequest,
    db: Session = Depends(get_db_session),
) -> PluginInfo:
    try:
        data = base64.b64decode(payload.content)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 content") from exc

    try:
        manifest, target_dir = extract_plugin_archive(data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    existing = db.query(Plugin).filter(Plugin.slug == manifest.slug).first()
    if existing and existing.version == manifest.version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plugin version already uploaded")

    plugin = Plugin(
        slug=manifest.slug,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        entrypoint=manifest.entrypoint,
        schedule=manifest.schedule,
        manifest={
            "name": manifest.name,
            "version": manifest.version,
            "slug": manifest.slug,
            "entrypoint": manifest.entrypoint,
            "description": manifest.description,
            "schedule": manifest.schedule,
            "source": manifest.source,
            "runtime": manifest.runtime,
        },
        upload_path=str(target_dir),
        is_active=False,
        status="uploaded",
    )
    db.add(plugin)
    db.commit()
    db.refresh(plugin)
    return PluginInfo.model_validate(plugin)


@router.get("", response_model=PluginListResponse)
def list_plugins(db: Session = Depends(get_db_session)) -> PluginListResponse:
    plugins = db.query(Plugin).order_by(Plugin.created_at.desc()).all()
    return PluginListResponse(items=[PluginInfo.model_validate(p) for p in plugins])


@router.post("/{plugin_id}/activate", response_model=PluginInfo)
def activate_plugin(
    plugin_id: int,
    payload: PluginActivateRequest,
    db: Session = Depends(get_db_session),
) -> PluginInfo:
    plugin = db.query(Plugin).get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")

    if payload.activate:
        if not plugin.schedule:
            raise HTTPException(status_code=400, detail="Plugin manifest missing schedule")
        plugin.is_active = True
        plugin.status = "active"
        plugin.activated_at = datetime.now(timezone.utc)
        plugin.next_run_at = compute_next_run(plugin.schedule)
    else:
        plugin.is_active = False
        plugin.status = "inactive"
    db.commit()
    db.refresh(plugin)
    return PluginInfo.model_validate(plugin)
