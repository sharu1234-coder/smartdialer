# Failure Recovery

## Worker Crash Recovery

### Problem
A dial worker can crash at any point during the allocation pipeline:
1. After `reserve_agent()` but before writing the Call
2. After writing the Call but before writing the Outbox
3. After writing the Outbox but before dispatching to the provider
4. After dispatch but before marking the Call as INITIATED

In all these cases, the agent and/or borrower remain in a `RESERVED` state with no active call progressing.

### Solution: Lease-Based Recovery

Every `Agent` has a `reservation_expires_at` timestamp set at reservation time:
```
reservation_expires_at = now() + 30 seconds (configurable)
```

The `RecoveryWorker` runs every 10 seconds and scans for stale reservations:

**Stale RESERVED calls** (agent reserved, call never sent to provider):
```sql
SELECT * FROM calls
WHERE status = 'RESERVED'
  AND created_at < now() - interval '30 seconds'
```
→ CANCEL the call, return agent to AVAILABLE, return borrower to PENDING.

**Stale INITIATED calls** (call sent to provider, no events received):
```sql
SELECT * FROM calls
WHERE status = 'INITIATED'
  AND created_at < now() - interval '120 seconds'
```
→ FAIL the call (we can't safely cancel — the provider may have already dialed). Release agent.

### Why Not CANCEL for INITIATED?
Once a call is INITIATED, the provider may have already placed the call. Cancelling in our system while the provider continues would create state divergence. FAIL is the safe choice — the borrower remains CALLED (not retried), and the agent is freed.

## Provider Outage

### Detection: Circuit Breaker
Each provider is wrapped by a circuit breaker with three states:

```
CLOSED (healthy) → failures accumulate → OPEN (blocked)
OPEN → timeout expires → HALF_OPEN (test mode)
HALF_OPEN → one success → CLOSED
HALF_OPEN → one failure → OPEN
```

Default thresholds: 5 consecutive failures to open, 60 seconds to try HALF_OPEN.

### Response by Safety Controller
| Circuit Breaker State | Provider Health | Safety Decision |
|----------------------|----------------|----------------|
| CLOSED | HEALTHY | Normal operation |
| HALF_OPEN | DEGRADED | FALLBACK_TO_PROGRESSIVE (max 1 call) |
| OPEN | UNHEALTHY | REJECT (0 calls) |

The Safety Controller queries the circuit breaker's health every tick before approving calls. This means provider outages are detected within one tick (≈1 second) of the circuit breaker opening.

### In-Flight Calls During Outage
Calls that were already INITIATED when the outage began are unaffected — they continue to receive events from the provider's side. Only new dispatches are blocked.

## Duplicate Events

### Problem
Telecom providers may deliver the same webhook event more than once (at-least-once delivery semantics). This can cause double state transitions, corrupting call state.

### Solution: (call_id, event_id) Unique Constraint
Every event from a provider carries a unique `event_id`. We store a `provider_events` record with a compound unique constraint:
```sql
UNIQUE (call_id, event_id)
```

The `EventProcessor` uses INSERT ... ON CONFLICT to detect duplicates:
1. Attempt to insert the event record
2. If conflict (duplicate): mark `is_duplicate=true`, return early without changing call state
3. If no conflict: proceed with state transition

### Atomicity
The uniqueness check and the state transition happen in the same database transaction. This prevents a race where two simultaneous deliveries of the same event both pass the check and both apply the transition.

## Out-of-Order Events

### Problem
Provider B delivers events out of order. For example, COMPLETED may arrive before ANSWERED. If we naively applied every event, the call could end up in an inconsistent state (CONNECTED after COMPLETED).

### Solution: Terminal State Protection
The `EventProcessor` checks whether the call is already in a terminal state (COMPLETED, FAILED, CANCELLED) before applying any transition:

```python
if call.status in TERMINAL_STATES:
    record event as is_out_of_order=True
    return early
```

For non-terminal calls, the state machine's transition table (`CALL_TRANSITIONS`) only allows valid progressions. An invalid transition raises `InvalidStateTransitionError`, which is caught and the event is recorded but not applied.

## Agent Drop (Mass Disconnect)

### Detection
The Safety Controller re-queries available agent count on every tick. If 40% of agents drop OFFLINE, the available count drops immediately. The SC then REDUCEs or REJECTs the pacing engine's request accordingly.

### Existing Calls
Calls already RINGING or ANSWERED that lose their agent are handled by the reconciliation service:
- Agent with expired lease + no active call: released to AVAILABLE
- Agent with expired lease + stale call: stale call is CANCELLED/FAILED

### Recovery
When agents come back online (status → AVAILABLE), the Safety Controller automatically approves more calls on the next tick. No manual intervention needed.
