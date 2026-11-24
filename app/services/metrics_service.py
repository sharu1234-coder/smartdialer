from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.models.metrics import CampaignMetrics
from app.models.call import Call
from app.models.provider_event import ProviderEvent
from app.repositories.call_repository import count_calls_by_status
from app.repositories.agent_repository import count_available, count_by_status
from app.core.enums import CallStatus, AgentStatus

logger = logging.getLogger(__name__)


@dataclass
class CampaignMetricsData:
    campaign_id: str
    calls_initiated: int
    calls_connected: int
    calls_completed: int
    calls_failed: int
    calls_cancelled: int
    agent_utilization_pct: float
    avg_talk_duration_sec: float
    avg_setup_latency_sec: float
    answer_rate: float
    agents_available: int
    agents_reserved: int
    agents_connected: int
    duplicate_events_ignored: int
    out_of_order_events: int
    snapshot_at: datetime

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "calls_initiated": self.calls_initiated,
            "calls_connected": self.calls_connected,
            "calls_completed": self.calls_completed,
            "calls_failed": self.calls_failed,
            "calls_cancelled": self.calls_cancelled,
            "agent_utilization_pct": round(self.agent_utilization_pct, 4),
            "avg_talk_duration_sec": round(self.avg_talk_duration_sec, 2),
            "avg_setup_latency_sec": round(self.avg_setup_latency_sec, 2),
            "answer_rate": round(self.answer_rate, 4),
            "agents_available": self.agents_available,
            "agents_reserved": self.agents_reserved,
            "agents_connected": self.agents_connected,
            "duplicate_events_ignored": self.duplicate_events_ignored,
            "out_of_order_events": self.out_of_order_events,
            "snapshot_at": self.snapshot_at.isoformat(),
        }


class MetricsService:
    def get_campaign_metrics(self, db: Session, campaign_id: str) -> CampaignMetricsData:
        call_counts = count_calls_by_status(db, campaign_id)

        completed = call_counts.get(CallStatus.COMPLETED, 0)
        failed = call_counts.get(CallStatus.FAILED, 0)
        cancelled = call_counts.get(CallStatus.CANCELLED, 0)
        connected = call_counts.get(CallStatus.CONNECTED, 0)
        total_terminal = completed + failed + cancelled

        # Answer rate = answered / (answered + failed)
        answered = completed  # completed implies answered
        answer_rate = answered / max(1, answered + failed) if total_terminal > 0 else 0.0

        # Average talk duration from completed calls
        avg_talk = self._avg_talk_duration(db, campaign_id)
        avg_setup = self._avg_setup_latency(db, campaign_id)

        # Agent utilization: (connected agents * 100) / total_agents
        total_agents = sum([
            count_available(db, campaign_id),
            count_by_status(db, AgentStatus.RESERVED, campaign_id),
            count_by_status(db, AgentStatus.DIALING, campaign_id),
            count_by_status(db, AgentStatus.CONNECTED, campaign_id),
            count_by_status(db, AgentStatus.WRAP_UP, campaign_id),
        ])
        agents_connected = count_by_status(db, AgentStatus.CONNECTED, campaign_id)
        utilization = agents_connected / max(1, total_agents) if total_agents > 0 else 0.0

        # Provider event anomalies
        dup_events = db.execute(
            select(func.count(ProviderEvent.id)).where(
                ProviderEvent.is_duplicate == True  # noqa: E712
            )
        ).scalar() or 0
        ooo_events = db.execute(
            select(func.count(ProviderEvent.id)).where(
                ProviderEvent.is_out_of_order == True  # noqa: E712
            )
        ).scalar() or 0

        # Count total initiated calls
        from sqlalchemy import select as sa_select
        initiated = db.execute(
            sa_select(func.count(Call.id)).where(
                Call.campaign_id == campaign_id,
                Call.initiated_at.is_not(None),
            )
        ).scalar() or 0

        return CampaignMetricsData(
            campaign_id=campaign_id,
            calls_initiated=initiated,
            calls_connected=call_counts.get(CallStatus.CONNECTED, 0) + completed,
            calls_completed=completed,
            calls_failed=failed,
            calls_cancelled=cancelled,
            agent_utilization_pct=utilization,
            avg_talk_duration_sec=avg_talk,
            avg_setup_latency_sec=avg_setup,
            answer_rate=answer_rate,
            agents_available=count_available(db, campaign_id),
            agents_reserved=count_by_status(db, AgentStatus.RESERVED, campaign_id),
            agents_connected=agents_connected,
            duplicate_events_ignored=dup_events,
            out_of_order_events=ooo_events,
            snapshot_at=datetime.now(timezone.utc),
        )

    def snapshot_metrics(self, db: Session, campaign_id: str) -> CampaignMetrics:
        data = self.get_campaign_metrics(db, campaign_id)
        snapshot = CampaignMetrics(
            campaign_id=campaign_id,
            snapshot_at=data.snapshot_at,
            calls_initiated=data.calls_initiated,
            calls_connected=data.calls_connected,
            calls_completed=data.calls_completed,
            calls_failed=data.calls_failed,
            calls_cancelled=data.calls_cancelled,
            agent_utilization_pct=data.agent_utilization_pct,
            avg_talk_duration_sec=data.avg_talk_duration_sec,
            avg_setup_latency_sec=data.avg_setup_latency_sec,
            answer_rate=data.answer_rate,
            duplicate_events_ignored=data.duplicate_events_ignored,
            out_of_order_events=data.out_of_order_events,
        )
        db.add(snapshot)
        db.flush()
        return snapshot

    @staticmethod
    def _avg_talk_duration(db: Session, campaign_id: str) -> float:
        stmt = (
            select(Call.answered_at, Call.completed_at)
            .where(
                Call.campaign_id == campaign_id,
                Call.status == CallStatus.COMPLETED,
                Call.answered_at.is_not(None),
                Call.completed_at.is_not(None),
            )
            .limit(1000)
        )
        rows = db.execute(stmt).all()
        if not rows:
            return 0.0
        durations = [
            (row.completed_at - row.answered_at).total_seconds()
            for row in rows
            if row.answered_at and row.completed_at
        ]
        return sum(durations) / len(durations) if durations else 0.0

    @staticmethod
    def _avg_setup_latency(db: Session, campaign_id: str) -> float:
        stmt = (
            select(Call.created_at, Call.initiated_at)
            .where(
                Call.campaign_id == campaign_id,
                Call.initiated_at.is_not(None),
            )
            .limit(1000)
        )
        rows = db.execute(stmt).all()
        if not rows:
            return 0.0
        latencies = [
            (row.initiated_at - row.created_at).total_seconds()
            for row in rows
            if row.initiated_at and row.created_at
        ]
        return sum(latencies) / len(latencies) if latencies else 0.0
