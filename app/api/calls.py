from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.repositories.call_repository import get_call, get_active_calls, get_calls_in_states
from app.core.exceptions import CallNotFoundError
from app.core.enums import CallStatus

router = APIRouter()


@router.get("/{call_id}")
def get_call_detail(call_id: str, db: Session = Depends(get_db)):
    try:
        call = get_call(db, call_id)
        return {
            "id": call.id,
            "campaign_id": call.campaign_id,
            "borrower_id": call.borrower_id,
            "agent_id": call.agent_id,
            "status": call.status,
            "dial_mode": call.dial_mode,
            "provider_id": call.provider_id,
            "provider_call_id": call.provider_call_id,
            "idempotency_key": call.idempotency_key,
            "failure_reason": call.failure_reason,
            "initiated_at": call.initiated_at,
            "answered_at": call.answered_at,
            "completed_at": call.completed_at,
            "created_at": call.created_at,
        }
    except CallNotFoundError:
        raise HTTPException(404, f"Call {call_id} not found")


@router.get("/active/list")
def list_active_calls(campaign_id: str | None = None, db: Session = Depends(get_db)):
    calls = get_active_calls(db, campaign_id)
    return [{"id": c.id, "status": c.status, "agent_id": c.agent_id} for c in calls]


@router.get("/history/list")
def list_call_history(
    campaign_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    if status:
        try:
            call_status = CallStatus(status.upper())
            calls = get_calls_in_states(db, [call_status], campaign_id)[:limit]
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    else:
        calls = get_active_calls(db, campaign_id)[:limit]
    return [
        {
            "id": c.id,
            "status": c.status,
            "dial_mode": c.dial_mode,
            "agent_id": c.agent_id,
            "created_at": c.created_at,
        }
        for c in calls
    ]
