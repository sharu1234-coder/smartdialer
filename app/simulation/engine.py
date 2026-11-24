from __future__ import annotations
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import SessionLocal
from app.models import Campaign, Agent, Borrower, Call, ProviderEvent, Outbox, CampaignMetrics
from app.models.reservation import Reservation
from app.core.enums import (
    CampaignStatus, DialMode, AgentStatus, BorrowerStatus, CallStatus
)
from app.repositories import agent_repository, borrower_repository, campaign_repository
from app.workers.dial_worker import DialWorker
from app.workers.event_worker import EventWorker
from app.workers.recovery_worker import RecoveryWorker
from app.providers.provider_factory import (
    initialize_default_providers, reset_providers, get_provider, get_provider_health_map
)
from app.simulation.reports import SimulationReport

logger = logging.getLogger(__name__)


@dataclass
class SimulationConfig:
    scenario: str
    answer_rate: float
    avg_talk_duration: float          # in TICKS (passed to provider)
    num_agents: int
    num_borrowers: int
    provider_name: str
    provider_failure_rate: float
    dial_mode: DialMode
    duration_ticks: int
    seed: int
    changing_answer_rate: bool = False
    changing_talk_duration: bool = False
    provider_latency_ms: float = 100.0
    provider_duplicate_rate: float = 0.01
    provider_out_of_order_rate: float = 0.0
    avg_talk_duration_secs: float = 0.0   # real seconds for display (optional)
    sim_ticks_per_second: int = 1         # 1 tick = N simulated seconds


class SimulationEngine:
    """
    Tick-based simulation engine. Each tick = 1 simulated second.
    Uses real database for state, but in-memory providers for speed.
    """

    def run(self, config: SimulationConfig) -> SimulationReport:
        rng = random.Random(config.seed)

        # Reset and re-initialize providers with scenario parameters
        reset_providers()
        provider_kwargs = {
            "answer_rate": config.answer_rate,
            "avg_talk_duration": config.avg_talk_duration,
            "failure_rate": config.provider_failure_rate,
            "latency_ms": config.provider_latency_ms,
            "seed": config.seed,
        }
        if config.provider_name == "provider_b":
            provider_kwargs["duplicate_rate"] = config.provider_duplicate_rate
            provider_kwargs["out_of_order_rate"] = config.provider_out_of_order_rate
            initialize_default_providers(provider_b_kwargs=provider_kwargs)
        else:
            provider_kwargs["duplicate_rate"] = config.provider_duplicate_rate
            initialize_default_providers(provider_a_kwargs=provider_kwargs)

        db = SessionLocal()
        wall_start = time.monotonic()
        report = SimulationReport(
            scenario=config.scenario,
            dial_mode=config.dial_mode.value,
            duration_ticks=config.duration_ticks,
            num_agents=config.num_agents,
            num_borrowers=config.num_borrowers,
            provider=config.provider_name,
            sim_ticks_per_second=config.sim_ticks_per_second,
            avg_talk_duration_secs_configured=config.avg_talk_duration_secs,
        )

        try:
            self._reset_simulation_data(db)
            campaign_id = self._seed_data(db, config)
            db.commit()

            dial_worker = DialWorker(campaign_id, config.dial_mode, provider_name=config.provider_name)
            event_worker = EventWorker(config.provider_name)
            recovery_worker = RecoveryWorker()

            for tick in range(config.duration_ticks):
                # Scenario D: deterministic phase transitions
                # Phase 1 (0 .. 25%):  baseline   — answer_rate=0.35, talk=9 ticks (90 s)
                # Phase 2 (25%.. 50%): low period  — answer_rate=0.10, talk=6 ticks (60 s)
                # Phase 3 (50%.. 75%): high period — answer_rate=0.65, talk=12 ticks (120 s)
                # Phase 4 (75%..100%): recovery    — answer_rate=0.40, talk=9 ticks (90 s)
                if config.changing_answer_rate or config.changing_talk_duration:
                    t25 = config.duration_ticks // 4
                    t50 = config.duration_ticks // 2
                    t75 = config.duration_ticks * 3 // 4
                    if tick == t25:
                        self._update_provider_rate(config.provider_name, 0.10, 6.0)
                        logger.info("Scenario D phase 2 (low): answer_rate=0.10 talk=6ticks at tick %d", tick)
                    elif tick == t50:
                        self._update_provider_rate(config.provider_name, 0.65, 12.0)
                        logger.info("Scenario D phase 3 (high): answer_rate=0.65 talk=12ticks at tick %d", tick)
                    elif tick == t75:
                        self._update_provider_rate(config.provider_name, 0.40, 9.0)
                        logger.info("Scenario D phase 4 (recovery): answer_rate=0.40 talk=9ticks at tick %d", tick)

                # Dial tick
                try:
                    tick_result = dial_worker.run_tick(db)
                    report.calls_initiated += tick_result.calls_initiated
                    report.dial_ticks += 1

                    if tick_result.safety_evaluation is not None:
                        ev = tick_result.safety_evaluation
                        from app.core.enums import SafetyDecision
                        report.predictive_requests += 1
                        if ev.decision == SafetyDecision.APPROVE:
                            report.safety_approvals += 1
                        elif ev.decision == SafetyDecision.REDUCE:
                            report.safety_reductions += 1
                        elif ev.decision == SafetyDecision.REJECT:
                            report.safety_rejections += 1
                        elif ev.decision == SafetyDecision.FALLBACK_TO_PROGRESSIVE:
                            report.progressive_fallbacks += 1

                    db.commit()
                except Exception as exc:
                    logger.error("Dial tick error at tick %d: %s", tick, exc)
                    db.rollback()

                # Event worker tick
                try:
                    event_result = event_worker.run_tick(db)
                    report.provider_failures += event_result.provider_failures
                    report.duplicate_events_ignored += event_result.events_duplicated
                    report.out_of_order_events += event_result.events_out_of_order
                    db.commit()
                except Exception as exc:
                    logger.error("Event tick error at tick %d: %s", tick, exc)
                    db.rollback()

                # Recovery every 10 ticks
                if tick % 10 == 0:
                    try:
                        recovery_worker.run(db)
                    except Exception as exc:
                        logger.error("Recovery error at tick %d: %s", tick, exc)
                        db.rollback()

            # Collect final metrics
            self._collect_final_metrics(db, campaign_id, config, report)

        except Exception as exc:
            logger.exception("Simulation failed: %s", exc)
            db.rollback()
        finally:
            db.close()

        report.wall_clock_seconds = time.monotonic() - wall_start
        return report

    def _reset_simulation_data(self, db: Session) -> None:
        """Clear simulation-specific tables. Recreates missing tables first."""
        from app.database import engine as main_engine
        # Ensure all tables exist (handles case where load test dropped them)
        from app.database import Base as AppBase
        import app.models  # noqa: F401 — registers all models with Base
        AppBase.metadata.create_all(bind=main_engine)
        for model in [CampaignMetrics, ProviderEvent, Outbox, Reservation, Call, Borrower, Agent, Campaign]:
            try:
                db.execute(text(f"DELETE FROM {model.__tablename__}"))
            except Exception:
                db.rollback()
        db.flush()

    def _seed_data(self, db: Session, config: SimulationConfig) -> str:
        campaign = Campaign(
            name=f"Sim-{config.scenario}-{config.dial_mode.value}",
            status=CampaignStatus.ACTIVE,
            dial_mode=config.dial_mode,
            max_concurrent_calls=config.num_agents * 3,
            started_at=datetime.now(timezone.utc),
        )
        db.add(campaign)
        db.flush()

        # Seed agents
        for i in range(config.num_agents):
            agent = Agent(
                name=f"Agent-{i+1:03d}",
                status=AgentStatus.AVAILABLE,
                campaign_id=campaign.id,
                available_since=datetime.now(timezone.utc),
                last_heartbeat=datetime.now(timezone.utc),
            )
            db.add(agent)

        # Seed borrowers
        for i in range(config.num_borrowers):
            borrower = Borrower(
                phone_number=f"+1555{i:07d}",
                name=f"Borrower-{i+1:04d}",
                campaign_id=campaign.id,
                status=BorrowerStatus.PENDING,
                priority=0,
            )
            db.add(borrower)

        db.flush()
        return campaign.id

    def _update_provider_rate(
        self, provider_name: str, answer_rate: float, talk_duration: float
    ) -> None:
        try:
            provider = get_provider(provider_name)
            provider.answer_rate = answer_rate
            provider.avg_talk_duration = talk_duration
        except Exception:
            pass

    def _collect_final_metrics(
        self, db: Session, campaign_id: str, config: SimulationConfig, report: SimulationReport
    ) -> None:
        from app.repositories.call_repository import count_calls_by_status
        from app.services.metrics_service import MetricsService

        try:
            counts = count_calls_by_status(db, campaign_id)
            report.calls_completed = counts.get(CallStatus.COMPLETED, 0)
            report.calls_failed = counts.get(CallStatus.FAILED, 0)
            report.calls_cancelled = counts.get(CallStatus.CANCELLED, 0)
            report.calls_connected = counts.get(CallStatus.CONNECTED, 0) + report.calls_completed

            total_terminal = report.calls_completed + report.calls_failed
            if total_terminal > 0:
                report.actual_answer_rate = report.calls_completed / total_terminal

            # --- Tick-based talk duration from provider (accurate, units-consistent) ---
            # The provider tracks how many TICKS each completed call actually talked for.
            # Multiply by sim_ticks_per_second to get SIMULATED seconds.
            try:
                provider = get_provider(config.provider_name)
                avg_ticks = provider.get_avg_talk_ticks() if hasattr(provider, "get_avg_talk_ticks") else 0.0
                report.avg_talk_duration_ticks = avg_ticks
                report.avg_talk_duration = avg_ticks * config.sim_ticks_per_second
            except Exception:
                pass

            # --- Agent utilization: fraction of agent-ticks spent on completed calls ---
            # total_talk_ticks = completed_calls × avg_talk_ticks
            # total_capacity   = num_agents × duration_ticks
            if report.avg_talk_duration_ticks > 0 and report.calls_completed > 0:
                total_talk_ticks = report.avg_talk_duration_ticks * report.calls_completed
                total_capacity = config.num_agents * config.duration_ticks
                report.agent_utilization = min(1.0, total_talk_ticks / max(1, total_capacity))

            metrics_svc = MetricsService()
            data = metrics_svc.get_campaign_metrics(db, campaign_id)
            # avg_setup_latency from MetricsService is wall-clock seconds (fine for setup)
            report.avg_setup_latency = data.avg_setup_latency_sec
            # NOTE: Duplicate events are intentionally NOT stored in the DB — the EventProcessor
            # returns early for duplicates without calling _record_event.  The correct counts are
            # the ones accumulated via event_result.events_duplicated in the tick loop above.
            # We only take out_of_order from the DB because those ARE stored (is_out_of_order=True).
            report.out_of_order_events = max(report.out_of_order_events, data.out_of_order_events)

        except Exception as exc:
            logger.error("Error collecting final metrics: %s", exc)
