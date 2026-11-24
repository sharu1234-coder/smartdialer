from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.providers.provider_factory import (
    get_provider, get_provider_health_map, get_circuit_breaker
)
from app.services.event_processor import EventProcessor
from app.core.enums import ProviderEventType

router = APIRouter()
_event_processor = EventProcessor()


class ProviderEventWebhook(BaseModel):
    call_id: str
    event_id: str
    event_type: str
    provider_name: str
    raw_payload: dict = {}
    sequence_number: int | None = None


@router.get("/health")
def get_provider_health():
    return get_provider_health_map()


@router.post("/{provider_name}/failure")
def toggle_failure_mode(provider_name: str, enabled: bool = True):
    try:
        provider = get_provider(provider_name)
        provider.set_failure_mode(enabled)
        cb = get_circuit_breaker(provider_name)
        if enabled:
            # Trigger circuit breaker
            for _ in range(cb.failure_threshold + 1):
                cb.record_failure()
        else:
            cb.reset()
        return {"provider": provider_name, "failure_mode": enabled}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/{provider_name}/circuit-breaker")
def get_circuit_breaker_status(provider_name: str):
    cb = get_circuit_breaker(provider_name)
    return {
        "provider": provider_name,
        "state": cb.state,
        "failure_count": cb.failure_count,
        "health": cb.health.value,
    }


@router.post("/events/webhook")
def receive_provider_event(
    payload: ProviderEventWebhook, db: Session = Depends(get_db)
):
    try:
        event_type = ProviderEventType(payload.event_type.upper())
    except ValueError:
        raise HTTPException(400, f"Invalid event_type: {payload.event_type}")

    result = _event_processor.process(
        db=db,
        call_id=payload.call_id,
        event_type=event_type,
        event_id=payload.event_id,
        provider_name=payload.provider_name,
        raw_payload=payload.raw_payload,
        sequence_number=payload.sequence_number,
    )
    db.commit()
    return {
        "event_id": result.event_id,
        "is_duplicate": result.is_duplicate,
        "is_out_of_order": result.is_out_of_order,
        "new_call_status": result.new_call_status,
        "skipped": result.skipped,
        "reason": result.reason,
    }
