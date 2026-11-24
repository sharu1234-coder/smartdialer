from __future__ import annotations
from app.simulation.engine import SimulationConfig, SimulationEngine
from app.simulation.reports import SimulationReport
from app.core.enums import DialMode

# Time model: 1 simulation tick represents SIM_TICKS_PER_SECOND real (simulated) seconds.
# This lets the simulation complete in seconds of wall-clock time while faithfully
# modelling minutes-long calls.  All avg_talk_duration values in SCENARIO_CONFIGS are
# stored in SIMULATED SECONDS (as specified by the assignment); the engine converts
# them to ticks before passing them to providers.
SIM_TICKS_PER_SECOND = 10  # 1 tick = 10 simulated seconds

BASE_AGENTS = 20
BASE_BORROWERS = 200
# 160 ticks × 10 s/tick = 1 600 simulated seconds (~27 min).
# Enough for Scenario C calls (180 s talk = 18 ticks) to complete many times.
BASE_TICKS = 160

SCENARIO_CONFIGS: dict[str, dict] = {
    "A": {
        "scenario": "A",
        "answer_rate": 0.20,
        # Assignment: 20 % answer rate, 120 s average talk time
        "avg_talk_duration_secs": 120.0,
        "avg_talk_duration": 120.0 / SIM_TICKS_PER_SECOND,  # 12 ticks
        "sim_ticks_per_second": SIM_TICKS_PER_SECOND,
        "provider_failure_rate": 0.05,
        "provider_latency_ms": 50.0,
    },
    "B": {
        "scenario": "B",
        "answer_rate": 0.50,
        # Assignment: 50 % answer rate, 90 s average talk time
        "avg_talk_duration_secs": 90.0,
        "avg_talk_duration": 90.0 / SIM_TICKS_PER_SECOND,   # 9 ticks
        "sim_ticks_per_second": SIM_TICKS_PER_SECOND,
        "provider_failure_rate": 0.05,
        "provider_latency_ms": 50.0,
    },
    "C": {
        "scenario": "C",
        "answer_rate": 0.70,
        # Assignment: 70 % answer rate, 180 s average talk time
        "avg_talk_duration_secs": 180.0,
        "avg_talk_duration": 180.0 / SIM_TICKS_PER_SECOND,  # 18 ticks
        "sim_ticks_per_second": SIM_TICKS_PER_SECOND,
        "provider_failure_rate": 0.05,
        "provider_latency_ms": 50.0,
    },
    "D": {
        "scenario": "D",
        # Phase 1 baseline — deterministic transitions are handled by the engine.
        # Phases: low (tick 25 %) → high (tick 50 %) → provider-degraded (tick 75 %)
        "answer_rate": 0.35,
        "avg_talk_duration_secs": 90.0,
        "avg_talk_duration": 90.0 / SIM_TICKS_PER_SECOND,   # 9 ticks
        "sim_ticks_per_second": SIM_TICKS_PER_SECOND,
        "provider_failure_rate": 0.05,
        "provider_latency_ms": 100.0,
        "changing_answer_rate": True,
        "changing_talk_duration": True,
    },
}


def run_scenario(
    name: str,
    dial_mode: DialMode,
    num_agents: int = BASE_AGENTS,
    provider: str = "provider_a",
    duration_ticks: int = BASE_TICKS,
    seed: int = 42,
) -> SimulationReport:
    base = SCENARIO_CONFIGS[name].copy()
    config = SimulationConfig(
        num_agents=num_agents,
        num_borrowers=num_agents * 10,
        provider_name=provider,
        dial_mode=dial_mode,
        duration_ticks=duration_ticks,
        seed=seed,
        provider_duplicate_rate=0.15 if provider == "provider_b" else 0.01,
        provider_out_of_order_rate=0.20 if provider == "provider_b" else 0.00,
        **base,
    )
    engine = SimulationEngine()
    return engine.run(config)


def compare_modes(
    scenario: str,
    num_agents: int = BASE_AGENTS,
    provider: str = "provider_a",
    duration_ticks: int = BASE_TICKS,
    seed: int = 42,
) -> dict:
    progressive = run_scenario(scenario, DialMode.PROGRESSIVE, num_agents, provider, duration_ticks, seed)
    predictive = run_scenario(scenario, DialMode.PREDICTIVE, num_agents, provider, duration_ticks, seed)
    return {
        "scenario": scenario,
        "provider": provider,
        "seed": seed,
        "progressive": progressive.to_dict(),
        "predictive": predictive.to_dict(),
        "utilization_improvement": predictive.agent_utilization - progressive.agent_utilization,
        "calls_improvement": predictive.calls_initiated - progressive.calls_initiated,
    }
