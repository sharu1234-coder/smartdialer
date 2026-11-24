from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.repositories import agent_repository
from app.core.enums import AgentStatus
from app.core.exceptions import AgentNotFoundError

router = APIRouter()


class AgentCreate(BaseModel):
    name: str
    campaign_id: str | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    status: str
    campaign_id: str | None
    current_call_id: str | None
    state_version: int

    model_config = {"from_attributes": True}


@router.post("/", response_model=AgentResponse)
def register_agent(payload: AgentCreate, db: Session = Depends(get_db)):
    agent = agent_repository.create_agent(db, name=payload.name, campaign_id=payload.campaign_id)
    db.commit()
    return agent


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    try:
        return agent_repository.get_agent(db, agent_id)
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent {agent_id} not found")


@router.post("/{agent_id}/heartbeat")
def heartbeat(agent_id: str, db: Session = Depends(get_db)):
    try:
        agent_repository.update_heartbeat(db, agent_id)
        db.commit()
        return {"status": "ok"}
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent {agent_id} not found")


@router.post("/{agent_id}/available", response_model=AgentResponse)
def set_available(agent_id: str, db: Session = Depends(get_db)):
    try:
        agent = agent_repository.release_agent(db, agent_id, AgentStatus.AVAILABLE)
        db.commit()
        return agent
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent {agent_id} not found")


@router.post("/{agent_id}/offline", response_model=AgentResponse)
def set_offline(agent_id: str, db: Session = Depends(get_db)):
    try:
        agent = agent_repository.release_agent(db, agent_id, AgentStatus.OFFLINE)
        db.commit()
        return agent
    except AgentNotFoundError:
        raise HTTPException(404, f"Agent {agent_id} not found")
