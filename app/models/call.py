from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
from app.core.enums import CallStatus, DialMode


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_status", "status"),
        Index("ix_calls_campaign_id", "campaign_id"),
        Index("ix_calls_agent_id", "agent_id"),
        Index("ix_calls_borrower_id", "borrower_id"),
        Index("ix_calls_idempotency_key", "idempotency_key"),
        Index("ix_calls_campaign_status", "campaign_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    borrower_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    provider_id: Mapped[str] = mapped_column(String(50), default="provider_a", nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus, name="call_status"), default=CallStatus.QUEUED, nullable=False
    )
    dial_mode: Mapped[DialMode] = mapped_column(
        SAEnum(DialMode, name="call_dial_mode"), default=DialMode.PROGRESSIVE, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Call id={self.id} status={self.status} agent={self.agent_id}>"
