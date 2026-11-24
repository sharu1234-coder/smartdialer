from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, JSON, Enum as SAEnum, Index
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base
from app.core.enums import OutboxStatus


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_status", "status"),
        Index("ix_outbox_call_id", "call_id"),
        Index("ix_outbox_idempotency_key", "idempotency_key"),
        Index("ix_outbox_next_retry_at", "next_retry_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    provider_name: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[OutboxStatus] = mapped_column(
        SAEnum(OutboxStatus, name="outbox_status"), default=OutboxStatus.PENDING, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
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
        return f"<Outbox id={self.id} call={self.call_id} status={self.status}>"
