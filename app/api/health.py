from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db

router = APIRouter()


@router.get("/live")
def liveness():
    return {"status": "alive"}


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail=f"Database not ready: {exc}")
