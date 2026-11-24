from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, Index
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
from app.core.enums import AgentStatus


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_status", "status"),
        Index("ix_agents_campaign_id", "campaign_id"),
        Index("ix_agents_status_campaign", "status", "campaign_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        SAEnum(AgentStatus, name="agent_status"), default=AgentStatus.OFFLINE, nullable=False
    )
    campaign_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    current_call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
        return f"<Agent id={self.id} name={self.name} status={self.status}>"
