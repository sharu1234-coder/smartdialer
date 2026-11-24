from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.repositories import campaign_repository
from app.core.enums import CampaignStatus, DialMode
from app.core.exceptions import CampaignNotFoundError

router = APIRouter()


class CampaignCreate(BaseModel):
    name: str
    dial_mode: DialMode = DialMode.PROGRESSIVE
    max_concurrent_calls: int = 50
    priority: int = 0


class CampaignResponse(BaseModel):
    id: str
    name: str
    status: str
    dial_mode: str
    max_concurrent_calls: int
    priority: int

    model_config = {"from_attributes": True}


@router.post("/", response_model=CampaignResponse)
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    campaign = campaign_repository.create_campaign(
        db,
        name=payload.name,
        dial_mode=payload.dial_mode,
        max_concurrent_calls=payload.max_concurrent_calls,
        priority=payload.priority,
    )
    db.commit()
    return campaign


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    try:
        return campaign_repository.get_campaign(db, campaign_id)
    except CampaignNotFoundError:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
def start_campaign(campaign_id: str, db: Session = Depends(get_db)):
    try:
        campaign = campaign_repository.get_campaign(db, campaign_id)
        if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
            raise HTTPException(400, "Campaign must be DRAFT or PAUSED to start")
        result = campaign_repository.update_campaign_status(db, campaign_id, CampaignStatus.ACTIVE)
        db.commit()
        return result
    except CampaignNotFoundError:
        raise HTTPException(404, f"Campaign {campaign_id} not found")


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
def pause_campaign(campaign_id: str, db: Session = Depends(get_db)):
    try:
        result = campaign_repository.update_campaign_status(db, campaign_id, CampaignStatus.PAUSED)
        db.commit()
        return result
    except CampaignNotFoundError:
        raise HTTPException(404, f"Campaign {campaign_id} not found")


@router.get("/{campaign_id}/stats")
def get_campaign_stats(campaign_id: str, db: Session = Depends(get_db)):
    try:
        return campaign_repository.get_campaign_stats(db, campaign_id)
    except CampaignNotFoundError:
        raise HTTPException(404, f"Campaign {campaign_id} not found")


@router.get("/")
def list_campaigns(db: Session = Depends(get_db)):
    return campaign_repository.get_all_campaigns(db)
