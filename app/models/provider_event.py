from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean, JSON, UniqueConstraint, Index
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base


class ProviderEvent(Base):
    __tablename__ = "provider_events"
    __table_args__ = (
        UniqueConstraint("call_id", "event_id", name="uq_provider_event_call_event"),
        Index("ix_provider_events_call_id", "call_id"),
        Index("ix_provider_events_event_id", "event_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    call_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    provider_name: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    normalized_status: Mapped[str] = mapped_column(String(50), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_out_of_order: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ProviderEvent id={self.id} call={self.call_id} "
            f"type={self.event_type} dup={self.is_duplicate}>"
        )
