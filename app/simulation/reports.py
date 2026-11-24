from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class SimulationReport:
    scenario: str
    dial_mode: str
    duration_ticks: int
    num_agents: int
    num_borrowers: int
    provider: str

    # Call stats
    calls_initiated: int = 0
    calls_connected: int = 0
    calls_completed: int = 0
    calls_failed: int = 0
    calls_cancelled: int = 0
    abandoned_calls: int = 0  # connected without agent — must be 0

    # Efficiency
    agent_utilization: float = 0.0
    avg_idle_time_seconds: float = 0.0
    # avg_talk_duration: simulated seconds = avg_talk_ticks * sim_ticks_per_second
    avg_talk_duration: float = 0.0
    avg_talk_duration_ticks: float = 0.0   # raw tick count from provider
    avg_talk_duration_secs_configured: float = 0.0  # from scenario config (expected)
    avg_setup_latency: float = 0.0
    actual_answer_rate: float = 0.0

    # Time model
    sim_ticks_per_second: int = 1   # 1 tick = this many simulated seconds
    wall_clock_seconds: float = 0.0  # actual elapsed wall-clock time

    # Safety controller
    safety_approvals: int = 0
    safety_reductions: int = 0
    safety_rejections: int = 0
    progressive_fallbacks: int = 0

    # Provider
    provider_failures: int = 0
    duplicate_events_ignored: int = 0
    out_of_order_events: int = 0

    # Pacing
    predictive_requests: int = 0
    dial_ticks: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def print_report(self) -> None:
        line = "=" * 60
        sim_secs = self.duration_ticks * self.sim_ticks_per_second
        print(f"\n{line}")
        print(f"  SIMULATION REPORT — Scenario {self.scenario} [{self.dial_mode}]")
        print(line)
        print(f"  Provider:              {self.provider}")
        print(f"  Agents:                {self.num_agents}")
        print(f"  Borrowers:             {self.num_borrowers}")
        print(f"  Duration (ticks):      {self.duration_ticks}")
        print(f"  Time model:            1 tick = {self.sim_ticks_per_second}s simulated")
        print(f"  Simulated duration:    {sim_secs}s ({sim_secs/60:.1f} min simulated)")
        print(f"  Wall-clock elapsed:    {self.wall_clock_seconds:.2f}s")
        print()
        print("  CALL OUTCOMES")
        print(f"    Initiated:           {self.calls_initiated}")
        print(f"    Connected:           {self.calls_connected}")
        print(f"    Completed:           {self.calls_completed}")
        print(f"    Failed:              {self.calls_failed}")
        print(f"    Cancelled:           {self.calls_cancelled}")
        print(f"    Abandoned:           {self.abandoned_calls}  ← must be 0")
        print()
        print("  EFFICIENCY")
        print(f"    Agent Utilization:   {self.agent_utilization * 100:.1f}%")
        print(f"    Answer Rate:         {self.actual_answer_rate * 100:.1f}%")
        configured = (
            f"  (configured {self.avg_talk_duration_secs_configured:.0f}s)"
            if self.avg_talk_duration_secs_configured > 0 else ""
        )
        print(f"    Avg Talk Duration:   {self.avg_talk_duration:.1f}s simulated"
              f"  [{self.avg_talk_duration_ticks:.1f} ticks]{configured}")
        print(f"    Avg Setup Latency:   {self.avg_setup_latency:.3f}s wall-clock")
        print()
        print("  SAFETY CONTROLLER")
        print(f"    Approvals:           {self.safety_approvals}")
        print(f"    Reductions:          {self.safety_reductions}")
        print(f"    Rejections:          {self.safety_rejections}")
        print(f"    Progressive Fallback:{self.progressive_fallbacks}")
        print()
        print("  PROVIDER HEALTH")
        print(f"    Failures:            {self.provider_failures}")
        print(f"    Duplicate Events:    {self.duplicate_events_ignored}")
        print(f"    Out-of-Order Events: {self.out_of_order_events}")
        print(f"{line}\n")
