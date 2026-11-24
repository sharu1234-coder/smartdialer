# SmartDialer — Architecture

## Overview

SmartDialer is a production-grade outbound calling system that supports two dialing modes:

- **Progressive**: 1 available agent → at most 1 outbound call. Never dials more than you have agents for.
- **Predictive**: Statistical pacing engine starts calls *before* agents finish, compensating for the fact that only a fraction of calls will be answered.

## Component Architecture

```
Campaign
  └── Pacing Engine (Progressive or Predictive)
        └── Safety Controller (independent DB gate)
              └── Call Allocator (atomic agent + borrower reservation)
                    └── Outbox (durable dispatch record)
                          └── Telecom Provider (A or B)
                                └── Event Processor (idempotent state machine)
```

### Why Each Layer Exists

**Pacing Engine** decides *how many calls to request*. It knows nothing about whether the system can actually serve them — it only optimizes throughput.

**Safety Controller** is an independent gate. It queries the database directly (never trusts the pacing engine's capacity claims) and enforces hard limits. This separation means a bug in the pacing engine cannot cause agent overload — the SC will catch it.

**Call Allocator** performs the atomic allocation: SELECT one borrower + SELECT one agent + reserve both + create Call + create Outbox, all in one transaction with row-level locks.

**Outbox Pattern** decouples DB writes from network calls. The allocator writes an outbox record; a separate event worker dispatches it to the telecom provider. If the app crashes after writing but before dispatching, the outbox entry is re-processed on restart.

## Data Model

```
campaigns ──< agents        (campaign assigns agents)
campaigns ──< borrowers     (campaign has a list of people to call)
campaigns ──< calls         (a call record per dial attempt)
calls ──< call_outbox       (pending provider dispatches)
calls ──< provider_events   (events from the telecom provider)
calls ──< reservations      (audit trail of agent+borrower pairing)
campaigns ──< metrics       (per-tick metrics for analysis)
```

## Concurrency Model

### Agent Reservation — Optimistic Locking

Each `Agent` row has a `state_version: int`. To reserve an agent:

```sql
UPDATE agents
SET status = 'RESERVED', state_version = state_version + 1, ...
WHERE id = :agent_id
  AND status = 'AVAILABLE'
  AND state_version = :expected_version
RETURNING *
```

If two workers race for the same agent, only one's `WHERE` clause matches — the other gets zero rows back and raises `AgentNotAvailableError`. No deadlocks, no pessimistic locks held.

### Borrower Selection — Pessimistic Locking with SKIP LOCKED

```sql
SELECT * FROM borrowers
WHERE campaign_id = :cid AND status = 'PENDING'
ORDER BY priority DESC, created_at ASC
FOR UPDATE SKIP LOCKED
LIMIT 1
```

`SKIP LOCKED` ensures that concurrent workers get different borrowers without blocking each other. Combined, optimistic locking on agents + skip-locked on borrowers ensures zero double-allocation under any concurrency level.

## Safety Controller

The Safety Controller evaluates every request independently. Its logic:

| Provider Health | Decision | Approved |
|----------------|----------|---------|
| UNHEALTHY | REJECT | 0 |
| DEGRADED | FALLBACK_TO_PROGRESSIVE | min(1, available) |
| HEALTHY | APPROVE or REDUCE | min(requested, available) |

It never receives the agent count as an argument — it queries `SELECT COUNT(*) FROM agents WHERE status = 'AVAILABLE'` itself. This independence means a pacing engine bug that over-estimates capacity is caught here.

## State Machines

### Call States
```
QUEUED → RESERVED → INITIATED → RINGING → ANSWERED → CONNECTED → COMPLETED
                                                               └──> FAILED
                            └──> FAILED
              └──> CANCELLED
```

Terminal states (COMPLETED, FAILED, CANCELLED) are protected — no event can re-open them.

### Agent States
```
OFFLINE → AVAILABLE → RESERVED → DIALING → CONNECTED → WRAP_UP → AVAILABLE
                └──> PAUSED → AVAILABLE
```

## Worker Architecture

Three workers run in production, each in its own process:

| Worker | Interval | Responsibility |
|--------|----------|---------------|
| `DialWorker` | 1s | Select borrowers, run pacing/safety, allocate calls |
| `EventWorker` | 500ms | Dispatch outbox entries, poll active calls for events |
| `RecoveryWorker` | 10s | Reconcile stale reservations from crashed workers |

## Provider Design

**Provider A** — reliable mock (5% failure, 100ms latency, 1% duplicates)  
**Provider B** — chaotic mock (20% failure, 300ms latency, 10% timeout, 15% duplicate events, 20% out-of-order events)

Both are wrapped by a **Circuit Breaker** (CLOSED → OPEN → HALF_OPEN) that tracks failure rates and stops dispatching to unhealthy providers.

## Recovery Scenarios

| Failure | Detection | Recovery |
|---------|-----------|---------|
| Worker crash post-reservation, pre-initiation | `created_at` lease expiry | CANCEL call, release agent |
| Worker crash post-initiation | `created_at` lease expiry | FAIL call, release agent |
| Provider outage | Circuit breaker opens | Safety controller falls back / rejects |
| Duplicate event from provider | `(call_id, event_id)` unique constraint | Mark duplicate, skip |
| Out-of-order event | Terminal state check | Mark out-of-order, skip |
| Agent drop | Safety controller re-queries DB | Reduce approved calls |

## Technology Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.15 |
| Web Framework | FastAPI |
| ORM | SQLAlchemy 2.x (sync) |
| DB Driver | psycopg2 |
| Database | PostgreSQL 18 |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Testing | pytest |
