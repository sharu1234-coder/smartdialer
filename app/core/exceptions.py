from __future__ import annotations


class SmartDialerError(Exception):
    pass


class AgentNotAvailableError(SmartDialerError):
    pass


class BorrowerNotAvailableError(SmartDialerError):
    pass


class InvalidStateTransitionError(SmartDialerError):
    def __init__(self, entity: str, from_state: str, to_state: str):
        super().__init__(f"Invalid transition for {entity}: {from_state} -> {to_state}")
        self.entity = entity
        self.from_state = from_state
        self.to_state = to_state


class SafetyControllerRejectError(SmartDialerError):
    pass


class ProviderError(SmartDialerError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class DuplicateEventError(SmartDialerError):
    pass


class StaleReservationError(SmartDialerError):
    pass


class CampaignNotActiveError(SmartDialerError):
    pass


class CallNotFoundError(SmartDialerError):
    pass


class AgentNotFoundError(SmartDialerError):
    pass


class BorrowerNotFoundError(SmartDialerError):
    pass


class CampaignNotFoundError(SmartDialerError):
    pass
