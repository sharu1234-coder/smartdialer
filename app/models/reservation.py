from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Index
from sqlalchemy.orm import mapped_column, Mapped
from app.database import Base


class Reservation(Base):
    """Tracks active agent-borrower-call reservations for audit and recovery."""
    __tablename__ = "reservations"
    __table_args__ = (
        Index("ix_reservations_agent_id", "agent_id"),
        Index("ix_reservations_call_id", "call_id"),
        Index("ix_reservations_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    borrower_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False
    )
    call_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<Reservation id={self.id} agent={self.agent_id} "
            f"call={self.call_id} expires={self.expires_at}>"
        )
