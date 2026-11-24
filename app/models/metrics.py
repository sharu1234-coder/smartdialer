from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base


class CampaignMetrics(Base):
    __tablename__ = "campaign_metrics"
    __table_args__ = (
        Index("ix_metrics_campaign_id", "campaign_id"),
        Index("ix_metrics_snapshot_at", "snapshot_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    calls_initiated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_connected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_cancelled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    agent_utilization_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_talk_duration_sec: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    avg_setup_latency_sec: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    answer_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    predictive_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_approvals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_reductions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_rejections: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progressive_fallbacks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_events_ignored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    out_of_order_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return f"<CampaignMetrics campaign={self.campaign_id} at={self.snapshot_at}>"
