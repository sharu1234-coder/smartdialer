from __future__ import annotations
from app.core.enums import AgentStatus, CallStatus
from app.core.exceptions import InvalidStateTransitionError

AGENT_TRANSITIONS: dict[AgentStatus, set[AgentStatus]] = {
    AgentStatus.OFFLINE: {AgentStatus.AVAILABLE},
    AgentStatus.AVAILABLE: {AgentStatus.RESERVED, AgentStatus.PAUSED, AgentStatus.OFFLINE},
    AgentStatus.RESERVED: {AgentStatus.DIALING, AgentStatus.AVAILABLE, AgentStatus.OFFLINE},
    AgentStatus.DIALING: {AgentStatus.CONNECTED, AgentStatus.AVAILABLE, AgentStatus.OFFLINE},
    AgentStatus.CONNECTED: {AgentStatus.WRAP_UP, AgentStatus.AVAILABLE, AgentStatus.OFFLINE},
    AgentStatus.WRAP_UP: {AgentStatus.AVAILABLE, AgentStatus.PAUSED, AgentStatus.OFFLINE},
    AgentStatus.PAUSED: {AgentStatus.AVAILABLE, AgentStatus.OFFLINE},
}

CALL_TRANSITIONS: dict[CallStatus, set[CallStatus]] = {
    CallStatus.QUEUED: {CallStatus.RESERVED, CallStatus.CANCELLED},
    CallStatus.RESERVED: {CallStatus.INITIATED, CallStatus.CANCELLED, CallStatus.FAILED},
    CallStatus.INITIATED: {CallStatus.RINGING, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.RINGING: {CallStatus.ANSWERED, CallStatus.FAILED, CallStatus.CANCELLED},
    CallStatus.ANSWERED: {CallStatus.CONNECTED, CallStatus.FAILED, CallStatus.COMPLETED},
    CallStatus.CONNECTED: {CallStatus.COMPLETED, CallStatus.FAILED},
    CallStatus.COMPLETED: set(),
    CallStatus.FAILED: set(),
    CallStatus.CANCELLED: set(),
}

TERMINAL_CALL_STATES: frozenset[CallStatus] = frozenset(
    {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.CANCELLED}
)

ACTIVE_CALL_STATES: frozenset[CallStatus] = frozenset(
    {
        CallStatus.RESERVED,
        CallStatus.INITIATED,
        CallStatus.RINGING,
        CallStatus.ANSWERED,
        CallStatus.CONNECTED,
    }
)


def validate_agent_transition(from_state: AgentStatus, to_state: AgentStatus) -> None:
    allowed = AGENT_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise InvalidStateTransitionError("Agent", from_state.value, to_state.value)


def validate_call_transition(from_state: CallStatus, to_state: CallStatus) -> None:
    if from_state in TERMINAL_CALL_STATES:
        raise InvalidStateTransitionError("Call", from_state.value, to_state.value)
    allowed = CALL_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise InvalidStateTransitionError("Call", from_state.value, to_state.value)


def is_terminal_call_state(state: CallStatus) -> bool:
    return state in TERMINAL_CALL_STATES


def is_active_call_state(state: CallStatus) -> bool:
    return state in ACTIVE_CALL_STATES


# Map provider event type to call status transition
from app.core.enums import ProviderEventType

PROVIDER_EVENT_TO_CALL_STATUS: dict[ProviderEventType, CallStatus] = {
    ProviderEventType.RINGING: CallStatus.RINGING,
    ProviderEventType.ANSWERED: CallStatus.ANSWERED,
    ProviderEventType.CONNECTED: CallStatus.CONNECTED,
    ProviderEventType.COMPLETED: CallStatus.COMPLETED,
    ProviderEventType.FAILED: CallStatus.FAILED,
    ProviderEventType.CANCELLED: CallStatus.CANCELLED,
}
