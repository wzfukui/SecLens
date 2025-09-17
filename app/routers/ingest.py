"""API endpoints for ingesting bulletins."""
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db_session
from app.schemas import BulletinCreate, IngestResponse

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


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
    try:
        for bulletin in bulletins:
            _, created = crud.upsert_bulletin(db, bulletin)
            if created:
                created_count += 1
            else:
                duplicate_count += 1
        db.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - bubble up as HTTP error
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return IngestResponse(accepted=created_count, duplicates=duplicate_count)
