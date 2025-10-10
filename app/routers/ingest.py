"""API endpoints for ingesting bulletins."""
import logging
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db_session
from app.schemas import BulletinCreate, IngestResponse
from app.services.notifications import handle_new_bulletins

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])

logger = logging.getLogger(__name__)


@router.post("/bulletins", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_bulletins(
    bulletins: Sequence[BulletinCreate],
    db: Session = Depends(get_db_session),
) -> IngestResponse:
    """Persist incoming bulletins and report how many were new versus duplicates."""

    if not bulletins:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload may not be empty")

    created_count = 0
    duplicate_count = 0
    new_bulletin_ids: list[int] = []
    try:
        for bulletin in bulletins:
            bulletin_obj, created = crud.upsert_bulletin(db, bulletin)
            if created:
                db.flush()
                if bulletin_obj.id is not None:
                    new_bulletin_ids.append(bulletin_obj.id)
                created_count += 1
            else:
                duplicate_count += 1
        db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - bubble up as HTTP error
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    else:
        if new_bulletin_ids:
            try:
                handle_new_bulletins(db, new_bulletin_ids)
            except Exception as exc:  # pragma: no cover - avoid crashing ingestion
                logger.warning("处理推送规则失败: %s", exc)

    return IngestResponse(accepted=created_count, duplicates=duplicate_count)
