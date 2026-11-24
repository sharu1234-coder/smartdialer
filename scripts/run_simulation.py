#!/usr/bin/env python3
"""
Run one of the four simulation scenarios.

Usage:
    # Single scenario with specific mode and provider
    python scripts/run_simulation.py --scenario A --mode progressive --agents 10 --ticks 160
    python scripts/run_simulation.py --scenario B --mode predictive --agents 10 --provider provider_b

    # Compare progressive vs predictive for all scenarios, both providers
    python scripts/run_simulation.py --scenario all --agents 10 --ticks 160

    # Compare both providers side-by-side
    python scripts/run_simulation.py --scenario B --mode predictive --provider all

Time model
----------
1 tick = SIM_TICKS_PER_SECOND (10) simulated seconds.
160 ticks ≈ 1 600 simulated seconds (~27 min of simulated call activity).
Scenario C calls (180 s talk time = 18 ticks) complete comfortably within this window.
"""
from __future__ import annotations
import sys
import os
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_all_tables
from app.simulation.scenarios import run_scenario, compare_modes, SCENARIO_CONFIGS, SIM_TICKS_PER_SECOND
from app.core.enums import DialMode

# Ensure tables exist before any simulation runs
create_all_tables()


def parse_args():
    p = argparse.ArgumentParser(description="Run SmartDialer simulation")
    p.add_argument("--scenario", choices=["A", "B", "C", "D", "all"], default="A")
    p.add_argument("--mode", choices=["progressive", "predictive", "both"], default="both")
    p.add_argument("--provider", choices=["provider_a", "provider_b", "all"], default="provider_a")
    p.add_argument("--agents", type=int, default=10)
    p.add_argument("--ticks", type=int, default=160)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--json", dest="output_json", action="store_true",
                   help="Also emit machine-readable JSON results to stdout after reports")
    return p.parse_args()


def run_one(scenario_key: str, mode_str: str, provider: str, num_agents: int, ticks: int, seed: int):
    cfg = SCENARIO_CONFIGS[scenario_key]
    mode = DialMode.PROGRESSIVE if mode_str == "progressive" else DialMode.PREDICTIVE

    secs = cfg["avg_talk_duration_secs"]
    print(f"\n{'='*60}")
    print(f"Scenario {scenario_key} | Mode: {mode.value} | Provider: {provider}")
    print(f"Agents: {num_agents}  |  Ticks: {ticks}  |  Seed: {seed}")
    print(f"Time model: 1 tick = {SIM_TICKS_PER_SECOND}s simulated "
          f"({ticks * SIM_TICKS_PER_SECOND}s / {ticks * SIM_TICKS_PER_SECOND / 60:.0f}min simulated)")
    print(f"Answer rate: {cfg['answer_rate']:.0%}  |  Avg talk: {secs:.0f}s simulated "
          f"({secs/SIM_TICKS_PER_SECOND:.0f} ticks)")
    print("=" * 60)

    report = run_scenario(
        name=scenario_key,
        dial_mode=mode,
        num_agents=num_agents,
        provider=provider,
        duration_ticks=ticks,
        seed=seed,
    )

    report.print_report()
    return report


def main():
    args = parse_args()
    all_results = []

    scenarios = ["A", "B", "C", "D"] if args.scenario == "all" else [args.scenario]
    providers = ["provider_a", "provider_b"] if args.provider == "all" else [args.provider]
    modes = (["progressive", "predictive"] if args.mode == "both"
             else [args.mode] if args.mode in ("progressive", "predictive")
             else ["progressive", "predictive"])

    for scenario_key in scenarios:
        for prov in providers:
            for mode_str in modes:
                report = run_one(scenario_key, mode_str, prov, args.agents, args.ticks, args.seed)
                all_results.append(report.to_dict())

    total = len(all_results)
    print(f"\nCompleted {total} simulation run(s).")

    if args.output_json:
        print("\n--- JSON RESULTS ---")
        print(json.dumps(all_results, indent=2, default=str))


if __name__ == "__main__":
    main()
