# Architecture Decision Records

## ADR-001: PostgreSQL as Sole State Store

**Status**: Accepted

**Context**: The system needs strong consistency guarantees for agent reservation, call state, and idempotency. We evaluated Redis (for speed), Kafka (for event streaming), and PostgreSQL.

**Decision**: Use PostgreSQL as the single authoritative state store. No Redis cache for call/agent state. No Kafka.

**Consequences**:
- ✅ Full ACID guarantees — no split-brain between cache and DB
- ✅ Row-level locking (`SELECT FOR UPDATE SKIP LOCKED`) enables safe concurrent workers without an external coordinator
- ✅ Single system to operate, monitor, and back up
- ✅ Alembic migrations provide schema versioning
- ⚠️ Throughput limited by PostgreSQL connection pool — mitigated by connection pooling (pool_size=10, max_overflow=20) and efficient queries
- ⚠️ Not suitable for >10,000 concurrent calls without connection pooler (PgBouncer); at that scale, the design remains valid but infrastructure scales

## ADR-002: Optimistic Locking for Agent Reservation

**Status**: Accepted

**Context**: Two dial workers could both select the same AVAILABLE agent and attempt to reserve it. We need exactly-once reservation.

**Decision**: Add a `state_version` column. Reserve with:
```sql
UPDATE agents SET status = 'RESERVED', state_version = state_version + 1
WHERE id = :id AND status = 'AVAILABLE' AND state_version = :expected
RETURNING *
```

**Alternatives Considered**:
- Pessimistic lock (`SELECT FOR UPDATE`): Works but holds lock for the duration of the transaction; `SKIP LOCKED` on agents would have worked but has different contention semantics.
- Application-level mutex: Not distributed-safe.

**Consequences**:
- ✅ Zero deadlock risk — lost update detected, not locked
- ✅ Fast — no lock waiting
- ✅ Explicit audit trail via version bump
- ⚠️ Caller must handle `AgentNotAvailableError` and retry (the CallAllocator does this)

## ADR-003: Safety Controller Independence

**Status**: Accepted

**Context**: The pacing engine computes a desired call count based on estimated answer rates and agent counts. If this estimate is wrong (stale cache, algorithm bug), agents could be overloaded.

**Decision**: The Safety Controller never receives agent capacity as a parameter. It always queries `SELECT COUNT(*) FROM agents WHERE status = 'AVAILABLE'` independently.

**Consequences**:
- ✅ Single point of enforcement for capacity limits
- ✅ Pacing engine bugs cannot bypass safety limits
- ✅ Safety controller audits are independently logged
- ⚠️ Extra DB query per tick — acceptable cost for safety guarantees

## ADR-004: Outbox Pattern for Provider Dispatch

**Status**: Accepted

**Context**: The allocator writes agent+borrower reservation and call record in one transaction. Provider dispatch (HTTP call to telecom API) happens after. If the process crashes between write and dispatch, the call would be stuck in RESERVED forever.

**Decision**: Allocator writes an outbox record (`call_outbox`) in the same transaction as the call. A separate event worker polls pending outbox entries and dispatches them. Failed dispatches are retried via outbox retry logic.

**Consequences**:
- ✅ At-least-once delivery guarantee for provider dispatch
- ✅ App can crash safely at any point without losing call intent
- ✅ Retry logic is independent of allocation logic
- ⚠️ Slight latency increase (allocate → outbox write → worker picks up → dispatch)
- ⚠️ Duplicate dispatch possible if worker crashes after dispatch but before marking outbox SENT — mitigated by provider-side idempotency keys

## ADR-005: Tick-Based Simulation

**Status**: Accepted

**Context**: Real call durations (60-180s) make real-time simulation too slow for testing.

**Decision**: Each simulation tick = 1 simulated second. Talk duration is tracked in ticks, not real seconds. `time.monotonic()` is only used for provider event timing, scaled by a simulation speed factor.

**Consequences**:
- ✅ 120-tick simulation completes in <1 second real time
- ✅ All four scenarios can be tested in a CI pipeline
- ⚠️ Simulation results don't capture real network latency or OS scheduling effects

## ADR-006: Modular Monolith

**Status**: Accepted

**Context**: The assignment could be implemented as microservices (separate pacing, safety, allocator services). This would be complex to operate and test.

**Decision**: Single deployable Python application with internal module boundaries. Workers are threads in dev, separate processes in production.

**Consequences**:
- ✅ Single deployment artifact
- ✅ Shared database transaction across components (critical for allocation atomicity)
- ✅ Simpler local development and testing
- ⚠️ Workers must not block each other — mitigated by separate DB sessions per worker
- ⚠️ Scale-out requires running multiple instances with a load balancer — PostgreSQL's row-level locking handles concurrent instances correctly

## ADR-007: Synchronous SQLAlchemy over async

**Status**: Accepted

**Context**: FastAPI supports async. SQLAlchemy 2.x supports both sync and async (asyncpg driver).

**Decision**: Use synchronous SQLAlchemy with psycopg2.

**Consequences**:
- ✅ Simpler code — no `async/await` throughout the ORM layer
- ✅ `SELECT FOR UPDATE SKIP LOCKED` works identically in sync mode
- ✅ Easier to reason about transaction boundaries
- ⚠️ Each request holds a thread while waiting for DB I/O
- ⚠️ At very high concurrency, async would improve throughput — acceptable for this scale
