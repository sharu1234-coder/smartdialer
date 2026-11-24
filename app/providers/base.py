from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from app.core.enums import ProviderEventType, ProviderStatus


@dataclass
class ProviderCallResult:
    success: bool
    provider_call_id: Optional[str]
    error: Optional[str] = None
    is_duplicate: bool = False


@dataclass
class NormalizedEvent:
    call_id: str
    event_id: str
    event_type: ProviderEventType
    provider_name: str
    sequence_number: Optional[int]
    raw_payload: dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TelecomProvider(ABC):
    """
    Abstract telecom provider interface.
    The dialer never imports provider-specific classes directly.
    """

    @abstractmethod
    def initiate_call(
        self, call_id: str, phone_number: str, idempotency_key: str
    ) -> ProviderCallResult:
        """Initiate an outbound call. Returns provider_call_id on success."""

    @abstractmethod
    def get_call_status(self, provider_call_id: str) -> Optional[ProviderEventType]:
        """Return current call status as normalized event type."""

    @abstractmethod
    def cancel_call(self, provider_call_id: str) -> bool:
        """Attempt to cancel an in-progress call. Returns True if cancelled."""

    @abstractmethod
    def get_pending_events(self, provider_call_id: str) -> list[NormalizedEvent]:
        """Return any new events for this call since last poll."""

    @abstractmethod
    def health_check(self) -> ProviderStatus:
        """Return current provider health."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""

    def set_failure_mode(self, enabled: bool) -> None:
        """Toggle forced failure mode (for testing)."""
