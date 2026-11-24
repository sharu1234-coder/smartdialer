from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint, Index
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
from app.core.enums import BorrowerStatus


class Borrower(Base):
    __tablename__ = "borrowers"
    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_number", name="uq_borrower_campaign_phone"),
        Index("ix_borrowers_status", "status"),
        Index("ix_borrowers_campaign_status", "campaign_id", "status"),
        Index("ix_borrowers_priority", "priority"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[BorrowerStatus] = mapped_column(
        SAEnum(BorrowerStatus, name="borrower_status"), default=BorrowerStatus.PENDING, nullable=False
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
        return f"<Borrower id={self.id} phone={self.phone_number} status={self.status}>"
