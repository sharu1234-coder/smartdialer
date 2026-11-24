# SmartDialer

A production-grade outbound call center dialer supporting **Progressive** and **Predictive** modes, built as a complete take-home assignment.

## Architecture in One Sentence

Campaign → Pacing Engine → **Independent Safety Controller** → Call Allocator → Outbox → Telecom Provider → Event Processor

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+ running locally

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure database (copy and edit)
cp .env.example .env
# Edit DATABASE_URL in .env

# Run database migrations
python -m alembic upgrade head

# Seed demo data
python scripts/seed_demo.py

# Start the API server
python -m uvicorn app.main:app --reload
```

API available at: http://localhost:8000
Interactive docs: http://localhost:8000/docs

## Running Tests

```bash
# Create test database first
python -c "
import psycopg2
c = psycopg2.connect('postgresql://postgres:password@localhost:5432/postgres')
c.autocommit = True
cur = c.cursor()
cur.execute(\"CREATE DATABASE smartdialer_test\")
c.close()
"

# Run all tests
python -m pytest tests/ -v --tb=short

# Run specific test categories
python -m pytest tests/unit/ -v
python -m pytest tests/integration/ -v
python -m pytest tests/concurrency/ -v
python -m pytest tests/failure/ -v
```

## Running Simulations

### Time Model

1 simulation tick = 10 simulated seconds (`SIM_TICKS_PER_SECOND = 10`).  
160 ticks = 1,600 simulated seconds (≈ 27 minutes of simulated call activity) while completing in wall-clock seconds.

Talk durations in reports are in **simulated seconds** (the provider tracks `talk_ticks`; the report multiplies by `sim_ticks_per_second`). Wall-clock elapsed time is reported separately.

### Scenario configurations (fixed)

| Scenario | Answer rate | Avg talk (simulated) | Notes |
|---|---|---|---|
| A | 20% | 120 s | Low answer rate — high failure overhead |
| B | 50% | 90 s | Balanced |
| C | 70% | 180 s | High answer rate + long talk → agents occupied longer |
| D | 35%/10%/65%/40% | 90/60/120/90 s | Deterministic 4-phase: baseline → low → high → recovery |

```bash
# Single scenario, specific provider and mode
python scripts/run_simulation.py --scenario A --mode progressive --provider provider_a --agents 10 --ticks 160

# Compare both modes on one scenario
python scripts/run_simulation.py --scenario B --mode both --agents 10 --ticks 160

# All scenarios, both providers, both modes — machine-readable JSON output
python scripts/run_simulation.py --scenario all --provider all --agents 10 --ticks 160 --json

# Reproduce exact audit results (seed 42)
python scripts/run_simulation.py --scenario all --provider provider_a --seed 42 --agents 10 --ticks 160
```

### Simulation results summary (seed=42, 10 agents, 160 ticks, provider_a)

| Scenario | Mode | Completed | Utilization | Avg Talk (sim s) | Abandoned |
|---|---|---|---|---|---|
| A (20% / 120s) | Progressive | 31 | 21.4% | 110.3 | 0 |
| A (20% / 120s) | Predictive  | 31 | 21.7% | 111.9 | 0 |
| B (50% / 90s)  | Progressive | 78 | 41.4% | 84.9  | 0 |
| B (50% / 90s)  | Predictive  | 73 | 38.5% | 84.4  | 0 |
| C (70% / 180s) | Progressive | 31 | 35.6% | 183.9 | 0 |
| C (70% / 180s) | Predictive  | 31 | 35.6% | 183.9 | 0 |
| D (variable)   | Progressive | 45 | 23.9% | 85.1  | 0 |
| D (variable)   | Predictive  | 43 | 22.9% | 85.1  | 0 |

**Note on Scenario C parity:** With 70% answer rate and 18-tick talk time, agents are occupied for most of the simulation, leaving fewer free agents for predictive to outpace progressive on. Both modes are constrained by the borrower count bottleneck (100 borrowers, 10 agents). Predictive's advantage is larger when answer rates are low and variable.

**Provider B comparison:** Provider B injects higher failure rates and duplicate events (15–22 per run vs 0–5 for Provider A). Both providers show 0 abandoned calls and identical safety-invariant compliance. See `docs/simulation-results.json` for the full 16-run result set.

## Load Testing

Two modes are available.

### Burst mode — raw allocation throughput

Concurrent workers compete for agents without processing events (agents never release). Measures allocation speed and pool stability.

```bash
python scripts/run_load_test.py --workers 2  --duration 5  --agents 100
python scripts/run_load_test.py --workers 5  --duration 10 --agents 100
python scripts/run_load_test.py --workers 10 --duration 15 --agents 100
```

Outcome categories:

| Category | Meaning |
|---|---|
| Successful allocations | Agent + borrower reserved, outbox written |
| No resource (expected) | No AVAILABLE agent or PENDING borrower — normal when all agents are busy |
| DB connection error | `FATAL: too many clients` — pool misconfiguration |
| Pool timeout | SQLAlchemy pool exhausted — increase `pool_size` or reduce workers |
| Other | Programming error — investigate the log |

### Sustained mode — agent recycling verification

Runs a full tick loop (DialWorker + EventWorker) so agents recycle through RESERVED → CONNECTED → AVAILABLE. `completions > agent_count` proves recycling works.

```bash
python scripts/run_load_test.py --mode sustained --ticks 120 --agents 20
```

**Measured result (20 agents, 120 ticks, 50% answer rate, 3-tick talk):**  
168 completions with 20 agents — agents recycled ✓  
PostgreSQL active connections: 1 after test ✓

**Expected results (burst, 100 agents, single-process):** no unexpected errors, peak PostgreSQL connections ≤ 15.

## Database Connection Budget

| Component | pool_size | max_overflow | Max connections |
|---|---|---|---|
| API server (per uvicorn worker) | 5 | 5 | 10 |
| Load-test script | 10 | 5 | 15 |
| Test suite (per test) | 1 | 1 | 2 |
| `run_workers.py` | 5 | 5 | 10 |

With the API and load test running simultaneously the ceiling is **25 connections**, well within PostgreSQL's default `max_connections = 100`.

### Session lifecycle rules

- Every `SessionLocal()` call **must** be wrapped in a `try/finally` block that calls `db.close()`.
- FastAPI endpoint dependencies use a `yield` dependency (`get_db()` in `app/database.py`) which guarantees `close()` even on 500 errors.
- Worker tasks create one `Session` per tick and close it in `finally`, never holding a session open across provider I/O.
- Never share a `Session` between threads.

### Troubleshooting `FATAL: sorry, too many clients already`

1. Check how many engines are being created: each `create_engine()` call allocates a new pool.  
   Every call site in the application should import the **singleton** engine from `app.database`.
2. Verify no test file calls `create_engine()` inside a loop or per-call helper function.
3. Run `SELECT count(*), state FROM pg_stat_activity GROUP BY state;` to see idle vs active connections.
4. If the total exceeds `max_connections`, shrink `pool_size` before raising the PostgreSQL limit.

## Project Structure

```
smartdialer/
├── app/
│   ├── api/              # FastAPI routers
│   ├── core/             # Enums, exceptions, state machines
│   ├── models/           # SQLAlchemy ORM models
│   ├── providers/        # Mock telecom providers + circuit breaker
│   ├── repositories/     # DB access layer
│   ├── services/         # Business logic (pacing, safety, allocator, events)
│   ├── simulation/       # Simulation engine + scenarios
│   ├── workers/          # Background workers
│   ├── config.py
│   ├── database.py
│   └── main.py
├── alembic/              # Database migrations
├── docs/                 # Architecture docs, ADRs, state machine diagrams
├── scripts/              # CLI scripts for seeding, simulation, load testing
├── tests/
│   ├── unit/             # Component-level tests
│   ├── integration/      # End-to-end flow tests
│   ├── concurrency/      # Race condition tests (multi-thread)
│   ├── failure/          # Failure scenario tests
│   └── simulation/       # Full simulation tests
├── docker-compose.yml
├── Dockerfile
└── Makefile
```

## Key Design Decisions

### 1. Progressive Mode
One available agent → at most one outbound call. Guarantees zero agent overload at the cost of idle time.

### 2. Predictive Mode
Uses EWMA (α=0.2) to estimate answer rate. Formula:

```
raw_desired = ceil(available_agents / effective_answer_rate)
```

In-flight calls have already reserved their own agents, so they do not compete with free agents for capacity. The Safety Controller then caps the approved count to actual `available_agents`.

**Bug fixed (audit 2026-11-25):** The original formula subtracted `in_flight` from `available_agents` before dividing, which double-counted capacity already consumed by in-flight calls. This caused predictive mode to request zero calls whenever agents were busy, making it behave no better than progressive mode.

### 3. Independent Safety Controller
The Safety Controller never trusts the pacing engine's capacity claims. It queries the database directly at evaluation time. This architectural independence prevents pacing bugs from causing agent overload.

### 4. Atomic Allocation
Agent reservation uses optimistic locking (`state_version` column). Borrower selection uses `SELECT FOR UPDATE SKIP LOCKED`. Both in one transaction — zero double-allocation.

### 5. Outbox Pattern
Provider dispatch is decoupled from allocation. The allocator writes an outbox record; a separate worker dispatches it. Worker crashes are safe.

### 6. Idempotent Event Processing
Every provider event carries a `(call_id, event_id)` pair stored with a unique constraint. Duplicate events are detected and silently ignored.

### 7. Terminal State Protection
Once a call is COMPLETED, FAILED, or CANCELLED, no event can re-open it. Out-of-order events are recorded but ignored.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | Full system design |
| [ADR](docs/architecture-decision-record.md) | Key architectural decisions |
| [Predictive Algorithm](docs/predictive-algorithm.md) | EWMA pacing math |
| [Failure Recovery](docs/failure-recovery.md) | All failure scenarios |
| [Scalability Analysis](docs/scalability-analysis.md) | Load test results & scaling guide |
| [Final Answer](docs/final-assignment-answer.md) | Assignment final question answer |
| [Agent State Machine](docs/agent-state-machine.mmd) | Mermaid diagram |
| [Call State Machine](docs/call-state-machine.mmd) | Mermaid diagram |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /campaigns | Create campaign |
| GET | /campaigns/{id} | Get campaign |
| POST | /campaigns/{id}/start | Start campaign |
| POST | /campaigns/{id}/pause | Pause campaign |
| GET | /agents | List agents |
| POST | /agents | Create agent |
| GET | /calls | List calls |
| GET | /calls/{id} | Get call details |
| POST | /dialer/{campaign_id}/tick | Manual dial tick |
| GET | /providers | List providers with health |
| POST | /simulation/run | Run simulation scenario |
