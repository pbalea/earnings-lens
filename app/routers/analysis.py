from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas

router = APIRouter(tags=["analysis"])


@router.get("/alerts", response_model=list[schemas.AlertOut])
def list_alerts(db: Session = Depends(get_db)):
    return (
        db.query(models.Alert)
        .order_by(models.Alert.created_at.desc())
        .all()
    )
