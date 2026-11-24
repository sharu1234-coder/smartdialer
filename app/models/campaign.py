from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Enum as SAEnum
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
from app.core.enums import CampaignStatus, DialMode


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        SAEnum(CampaignStatus, name="campaign_status"), default=CampaignStatus.DRAFT, nullable=False
    )
    dial_mode: Mapped[DialMode] = mapped_column(
        SAEnum(DialMode, name="dial_mode"), default=DialMode.PROGRESSIVE, nullable=False
    )
    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name} status={self.status}>"
