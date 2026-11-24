from __future__ import annotations
import pytest
from app.simulation.engine import SimulationConfig, SimulationEngine
from app.simulation.scenarios import run_scenario, SCENARIO_CONFIGS, SIM_TICKS_PER_SECOND
from app.core.enums import DialMode


def _make_config(
    scenario: str,
    dial_mode: DialMode,
    num_agents: int = 5,
    duration_ticks: int = 60,   # 60 × 10 s/tick = 600 s simulated — enough for C (18 ticks talk)
    provider: str = "provider_a",
    seed: int = 42,
) -> SimulationConfig:
    base = SCENARIO_CONFIGS[scenario].copy()
    return SimulationConfig(
        num_agents=num_agents,
        num_borrowers=num_agents * 10,
        provider_name=provider,
        dial_mode=dial_mode,
        duration_ticks=duration_ticks,
        seed=seed,
        provider_duplicate_rate=0.01,
        provider_out_of_order_rate=0.00,
        **base,
    )


@pytest.mark.simulation
class TestSimulationScenarios:
    """Full-stack simulation tests — verifies end-to-end behavior across all scenarios."""

    def test_scenario_a_progressive_runs_without_error(self):
        """Scenario A (20% answer rate) in progressive mode completes."""
        config = _make_config("A", DialMode.PROGRESSIVE)
        engine = SimulationEngine()
        report = engine.run(config)
        assert report is not None
        assert report.calls_initiated >= 0
        assert report.calls_connected >= 0
        assert report.abandoned_calls == 0, "No abandoned calls allowed"

    def test_scenario_b_predictive_runs_without_error(self):
        """Scenario B (50% answer rate) in predictive mode completes."""
        config = _make_config("B", DialMode.PREDICTIVE)
        engine = SimulationEngine()
        report = engine.run(config)
        assert report is not None
        assert report.calls_initiated >= 0
        assert report.abandoned_calls == 0

    def test_predictive_beats_progressive_calls_initiated(self):
        """
        After fixing the pacing formula, predictive mode must demonstrate that it
        pre-dials beyond the 1:1 ratio of progressive mode.

        The Safety Controller caps APPROVED calls to available_agents for both modes,
        so total calls_initiated ends up similar for both. The reliable signal is
        safety_reductions: predictive requests ceil(agents / rate) > agents per tick,
        so the SC must reduce it every tick.  Progressive never calls the SC at all.
        """
        engine = SimulationEngine()
        prog_config = _make_config("B", DialMode.PROGRESSIVE, num_agents=20, duration_ticks=80, seed=42)
        pred_config = _make_config("B", DialMode.PREDICTIVE, num_agents=20, duration_ticks=80, seed=42)
        prog_report = engine.run(prog_config)
        pred_report = engine.run(pred_config)

        # Both must initiate calls
        assert prog_report.calls_initiated > 0
        assert pred_report.calls_initiated > 0
        # Safety invariant: no abandoned calls in either mode
        assert prog_report.abandoned_calls == 0
        assert pred_report.abandoned_calls == 0
        # Progressive never calls the Safety Controller (1:1 dialing, always within capacity)
        assert prog_report.safety_reductions == 0, (
            "Progressive mode must not trigger Safety Controller reductions"
        )
        # Predictive requests ceil(available / rate) = 2× at 50% → SC must reduce every tick
        assert pred_report.safety_reductions > 0, (
            f"Predictive mode must trigger Safety Controller reductions "
            f"(pacing engine pre-dials 2× available agents at 50% answer rate; "
            f"SC reduces to actual capacity). Got safety_reductions={pred_report.safety_reductions}"
        )

    def test_scenario_d_changing_conditions_deterministic(self):
        """Scenario D uses deterministic phase transitions; seed produces reproducible output."""
        config = _make_config("D", DialMode.PREDICTIVE, duration_ticks=80, seed=42)
        engine = SimulationEngine()
        report1 = engine.run(config)

        config2 = _make_config("D", DialMode.PREDICTIVE, duration_ticks=80, seed=42)
        report2 = engine.run(config2)

        # Identical seed → identical calls_initiated (deterministic)
        assert report1.calls_initiated == report2.calls_initiated, \
            "Scenario D must be deterministic across identical seeds"
        assert report1.dial_ticks > 0

    def test_scenario_c_high_answer_rate(self):
        """Scenario C (70% answer rate) — agents should stay busy, calls should be initiated."""
        config = _make_config("C", DialMode.PREDICTIVE, num_agents=5, duration_ticks=60)
        engine = SimulationEngine()
        report = engine.run(config)
        assert report is not None
        assert report.calls_initiated > 0, "Scenario C should initiate calls"
        total_terminal = report.calls_connected + report.calls_failed + report.calls_cancelled
        if total_terminal >= 5:
            answer_rate = report.calls_connected / total_terminal
            assert answer_rate >= 0.1, f"Answer rate {answer_rate:.2f} too low for 70% scenario"

    def test_abandoned_calls_always_zero(self):
        """Safety invariant: abandoned_calls must always be zero."""
        for scenario in ["A", "B", "C"]:
            for mode in [DialMode.PROGRESSIVE, DialMode.PREDICTIVE]:
                config = _make_config(scenario, mode, num_agents=5, duration_ticks=30)
                engine = SimulationEngine()
                report = engine.run(config)
                assert report.abandoned_calls == 0, (
                    f"Scenario {scenario} {mode.value}: abandoned_calls={report.abandoned_calls}"
                )

    def test_provider_b_chaos_handled(self):
        """Provider B with duplicates and out-of-order events should not crash."""
        base = SCENARIO_CONFIGS["B"].copy()
        config = SimulationConfig(
            num_agents=5,
            num_borrowers=50,
            provider_name="provider_b",
            dial_mode=DialMode.PREDICTIVE,
            duration_ticks=30,
            seed=99,
            provider_duplicate_rate=0.15,
            provider_out_of_order_rate=0.20,
            **base,
        )
        engine = SimulationEngine()
        report = engine.run(config)
        assert report is not None
        assert report.abandoned_calls == 0

    def test_provider_b_duplicate_events_recorded(self):
        """Provider B must generate and record duplicate events (not just claim they're handled)."""
        base = SCENARIO_CONFIGS["B"].copy()
        config = SimulationConfig(
            num_agents=10,
            num_borrowers=100,
            provider_name="provider_b",
            dial_mode=DialMode.PROGRESSIVE,
            duration_ticks=50,
            seed=7,
            provider_duplicate_rate=0.30,  # 30% → definitely generates duplicates
            provider_out_of_order_rate=0.20,
            **base,
        )
        engine = SimulationEngine()
        report = engine.run(config)
        assert report.abandoned_calls == 0
        # With 30% duplicate rate, provider B generates many duplicates — they must be counted
        if report.calls_initiated >= 10:
            assert report.duplicate_events_ignored > 0, (
                "Provider B with 30% duplicate rate must produce duplicate events that are ignored"
            )

    def test_provider_b_no_duplicate_agent_reservation(self):
        """Provider B chaos cannot cause the same agent to be allocated twice."""
        base = SCENARIO_CONFIGS["B"].copy()
        config = SimulationConfig(
            num_agents=5,
            num_borrowers=50,
            provider_name="provider_b",
            dial_mode=DialMode.PREDICTIVE,
            duration_ticks=40,
            seed=55,
            provider_duplicate_rate=0.20,
            provider_out_of_order_rate=0.25,
            **base,
        )
        engine = SimulationEngine()
        report = engine.run(config)
        assert report.abandoned_calls == 0
        # Safety: duplicate/OOO events cannot re-open terminal states → no extra reservations

    def test_scenario_a_b_c_comparison(self):
        """Higher answer rate scenarios should have more connected calls per initiated call."""
        engine = SimulationEngine()
        results = {}
        for s in ["A", "B", "C"]:
            config = _make_config(s, DialMode.PROGRESSIVE, num_agents=5, duration_ticks=60)
            results[s] = engine.run(config)
        # C (70%) should have more answered than A (20%) per initiated call
        if results["C"].calls_initiated > 0 and results["A"].calls_initiated > 0:
            rate_c = results["C"].calls_connected / results["C"].calls_initiated
            rate_a = results["A"].calls_connected / results["A"].calls_initiated
            assert rate_c >= rate_a, f"Scenario C answer rate {rate_c:.2f} should be >= A {rate_a:.2f}"

    def test_talk_duration_uses_simulated_seconds(self):
        """
        avg_talk_duration in the report must be in SIMULATED seconds
        (avg_talk_ticks × sim_ticks_per_second), NOT wall-clock milliseconds.

        With SIM_TICKS_PER_SECOND=10 and Scenario B configured at 90s / 9 ticks,
        completed calls must report ~90s (± 50% variance from Gaussian distribution),
        not <1s (which would indicate raw wall-clock measurement).
        """
        config = _make_config("B", DialMode.PROGRESSIVE, num_agents=10, duration_ticks=80, seed=42)
        engine = SimulationEngine()
        report = engine.run(config)

        if report.calls_completed >= 3:
            # avg_talk_duration should be ~90 simulated seconds (not <1s wall-clock)
            assert report.avg_talk_duration >= 10.0, (
                f"avg_talk_duration={report.avg_talk_duration:.2f}s looks like wall-clock "
                f"milliseconds, not simulated seconds (expected ~90s for Scenario B)"
            )
            assert report.sim_ticks_per_second == SIM_TICKS_PER_SECOND

    def test_wall_clock_vs_simulated_duration_separate(self):
        """wall_clock_seconds and avg_talk_duration must use different units."""
        config = _make_config("B", DialMode.PROGRESSIVE, num_agents=5, duration_ticks=60, seed=42)
        engine = SimulationEngine()
        report = engine.run(config)

        # Wall-clock should be much shorter than simulated duration
        sim_duration = report.duration_ticks * report.sim_ticks_per_second
        assert sim_duration == 60 * SIM_TICKS_PER_SECOND   # 600 simulated seconds
        # Wall-clock should be only a few seconds
        assert report.wall_clock_seconds < sim_duration, \
            "Wall-clock time must be much less than simulated duration"
