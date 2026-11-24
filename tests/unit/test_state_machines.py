from __future__ import annotations
import pytest
from app.core.enums import AgentStatus, CallStatus
from app.core.exceptions import InvalidStateTransitionError
from app.core.state_machines import (
    validate_agent_transition,
    validate_call_transition,
    is_terminal_call_state,
    TERMINAL_CALL_STATES,
)


class TestAgentStateMachine:
    def test_offline_to_available(self):
        validate_agent_transition(AgentStatus.OFFLINE, AgentStatus.AVAILABLE)

    def test_available_to_reserved(self):
        validate_agent_transition(AgentStatus.AVAILABLE, AgentStatus.RESERVED)

    def test_available_to_paused(self):
        validate_agent_transition(AgentStatus.AVAILABLE, AgentStatus.PAUSED)

    def test_reserved_to_dialing(self):
        validate_agent_transition(AgentStatus.RESERVED, AgentStatus.DIALING)

    def test_dialing_to_connected(self):
        validate_agent_transition(AgentStatus.DIALING, AgentStatus.CONNECTED)

    def test_connected_to_wrap_up(self):
        validate_agent_transition(AgentStatus.CONNECTED, AgentStatus.WRAP_UP)

    def test_wrap_up_to_available(self):
        validate_agent_transition(AgentStatus.WRAP_UP, AgentStatus.AVAILABLE)

    def test_invalid_offline_to_reserved(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_agent_transition(AgentStatus.OFFLINE, AgentStatus.RESERVED)

    def test_invalid_connected_to_reserved(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_agent_transition(AgentStatus.CONNECTED, AgentStatus.RESERVED)

    def test_invalid_wrap_up_to_connected(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_agent_transition(AgentStatus.WRAP_UP, AgentStatus.CONNECTED)

    def test_all_states_can_go_offline(self):
        can_go_offline = [AgentStatus.AVAILABLE, AgentStatus.RESERVED,
                          AgentStatus.DIALING, AgentStatus.CONNECTED,
                          AgentStatus.WRAP_UP, AgentStatus.PAUSED]
        for status in can_go_offline:
            validate_agent_transition(status, AgentStatus.OFFLINE)


class TestCallStateMachine:
    def test_queued_to_reserved(self):
        validate_call_transition(CallStatus.QUEUED, CallStatus.RESERVED)

    def test_reserved_to_initiated(self):
        validate_call_transition(CallStatus.RESERVED, CallStatus.INITIATED)

    def test_initiated_to_ringing(self):
        validate_call_transition(CallStatus.INITIATED, CallStatus.RINGING)

    def test_ringing_to_answered(self):
        validate_call_transition(CallStatus.RINGING, CallStatus.ANSWERED)

    def test_answered_to_connected(self):
        validate_call_transition(CallStatus.ANSWERED, CallStatus.CONNECTED)

    def test_connected_to_completed(self):
        validate_call_transition(CallStatus.CONNECTED, CallStatus.COMPLETED)

    def test_ringing_to_failed(self):
        validate_call_transition(CallStatus.RINGING, CallStatus.FAILED)

    def test_terminal_completed_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_call_transition(CallStatus.COMPLETED, CallStatus.ANSWERED)

    def test_terminal_failed_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_call_transition(CallStatus.FAILED, CallStatus.RINGING)

    def test_terminal_cancelled_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_call_transition(CallStatus.CANCELLED, CallStatus.INITIATED)

    def test_terminal_states_set(self):
        assert CallStatus.COMPLETED in TERMINAL_CALL_STATES
        assert CallStatus.FAILED in TERMINAL_CALL_STATES
        assert CallStatus.CANCELLED in TERMINAL_CALL_STATES

    def test_is_terminal(self):
        assert is_terminal_call_state(CallStatus.COMPLETED)
        assert is_terminal_call_state(CallStatus.FAILED)
        assert not is_terminal_call_state(CallStatus.ANSWERED)
        assert not is_terminal_call_state(CallStatus.RINGING)
