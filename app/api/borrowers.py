from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.repositories import borrower_repository
from app.core.exceptions import BorrowerNotFoundError

router = APIRouter()


class BorrowerCreate(BaseModel):
    phone_number: str
    name: str
    campaign_id: str
    priority: int = 0


class BulkBorrowerCreate(BaseModel):
    campaign_id: str
    borrowers: list[dict]


class BorrowerResponse(BaseModel):
    id: str
    phone_number: str
    name: str
    status: str
    campaign_id: str
    priority: int
    attempt_count: int

    model_config = {"from_attributes": True}


@router.post("/", response_model=BorrowerResponse)
def add_borrower(payload: BorrowerCreate, db: Session = Depends(get_db)):
    borrower = borrower_repository.create_borrower(
        db,
        campaign_id=payload.campaign_id,
        phone_number=payload.phone_number,
        name=payload.name,
        priority=payload.priority,
    )
    db.commit()
    return borrower


@router.post("/bulk")
def bulk_add_borrowers(payload: BulkBorrowerCreate, db: Session = Depends(get_db)):
    borrowers = borrower_repository.bulk_create_borrowers(
        db, campaign_id=payload.campaign_id, borrowers_data=payload.borrowers
    )
    db.commit()
    return {"created": len(borrowers)}


@router.get("/{borrower_id}", response_model=BorrowerResponse)
def get_borrower(borrower_id: str, db: Session = Depends(get_db)):
    try:
        return borrower_repository.get_borrower(db, borrower_id)
    except BorrowerNotFoundError:
        raise HTTPException(404, f"Borrower {borrower_id} not found")


@router.get("/")
def list_borrowers(campaign_id: str, db: Session = Depends(get_db)):
    from sqlalchemy import select
    from app.models.borrower import Borrower
    stmt = select(Borrower).where(Borrower.campaign_id == campaign_id).limit(100)
    return list(db.execute(stmt).scalars().all())
