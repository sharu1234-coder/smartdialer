from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.workers.dial_worker import DialWorker
from app.services.predictive_pacing import PredictivePacingEngine
from app.services.safety_controller import SafetyController
from app.providers.provider_factory import get_overall_health
from app.core.enums import DialMode
from app.core.exceptions import CampaignNotFoundError, CampaignNotActiveError

router = APIRouter()
_pacing_engine = PredictivePacingEngine()
_safety_controller = SafetyController()


class DialTickRequest(BaseModel):
    campaign_id: str
    mode: DialMode = DialMode.PROGRESSIVE


@router.post("/tick")
def run_dial_tick(payload: DialTickRequest, db: Session = Depends(get_db)):
    try:
        worker = DialWorker(payload.campaign_id, payload.mode)
        result = worker.run_tick(db)
        db.commit()
        return {
            "dial_mode": result.dial_mode,
            "calls_initiated": result.calls_initiated,
            "available_agents": result.available_agents,
            "errors": result.errors,
            "pacing_decision": (
                {
                    "requested_calls": result.pacing_decision.requested_calls,
                    "estimated_answer_rate": result.pacing_decision.estimated_answer_rate,
                    "reasoning": result.pacing_decision.reasoning,
                }
                if result.pacing_decision
                else None
            ),
            "safety_evaluation": (
                result.safety_evaluation.to_dict() if result.safety_evaluation else None
            ),
        }
    except (CampaignNotFoundError, CampaignNotActiveError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Dial tick failed: {exc}")


@router.get("/pacing/{campaign_id}")
def get_pacing_decision(campaign_id: str, db: Session = Depends(get_db)):
    provider_health = get_overall_health()
    decision = _pacing_engine.calculate_pacing(db, campaign_id, provider_health)
    return {
        "campaign_id": campaign_id,
        "estimated_answer_rate": decision.estimated_answer_rate,
        "available_agents": decision.available_agents,
        "in_flight_calls": decision.in_flight_calls,
        "requested_calls": decision.requested_calls,
        "reasoning": decision.reasoning,
        "is_fallback": decision.is_fallback,
        "sample_size": decision.sample_size,
    }


@router.get("/safety/{campaign_id}")
def get_safety_evaluation(
    campaign_id: str,
    requested: int = 10,
    db: Session = Depends(get_db),
):
    provider_health = get_overall_health()
    evaluation = _safety_controller.evaluate(db, campaign_id, requested, provider_health)
    return evaluation.to_dict()
