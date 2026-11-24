from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.simulation.scenarios import run_scenario, compare_modes
from app.core.enums import DialMode

router = APIRouter()


class SimulationRequest(BaseModel):
    scenario: str = "A"
    dial_mode: str = "PROGRESSIVE"
    num_agents: int = 20
    provider: str = "provider_a"
    duration_ticks: int = 60
    seed: int = 42


@router.post("/run")
def run_simulation(payload: SimulationRequest):
    try:
        dial_mode = DialMode(payload.dial_mode.upper())
    except ValueError:
        raise HTTPException(400, f"Invalid dial_mode: {payload.dial_mode}")

    if payload.scenario not in ("A", "B", "C", "D"):
        raise HTTPException(400, f"Scenario must be A, B, C, or D")

    report = run_scenario(
        name=payload.scenario,
        dial_mode=dial_mode,
        num_agents=payload.num_agents,
        provider=payload.provider,
        duration_ticks=payload.duration_ticks,
        seed=payload.seed,
    )
    return report.to_dict()


@router.get("/compare/{scenario}")
def compare_scenario(
    scenario: str,
    num_agents: int = 20,
    provider: str = "provider_a",
    duration_ticks: int = 60,
    seed: int = 42,
):
    if scenario not in ("A", "B", "C", "D"):
        raise HTTPException(400, f"Scenario must be A, B, C, or D")

    return compare_modes(
        scenario=scenario,
        num_agents=num_agents,
        provider=provider,
        duration_ticks=duration_ticks,
        seed=seed,
    )
