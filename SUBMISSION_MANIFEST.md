# SmartDialer — Submission Manifest

**Candidate:** Sharath Kumar  
**Assignment:** SmartDialer Tech Assignment — Hiring 2026  
**Submission date:** 2026-11-25  
**Archive:** `SmartDialer_Submission_Sharath_Kumar.zip`

---

## Verification Results

| Check | Result |
|-------|--------|
| Test suite | **106/106 passed** (79.5 s) |
| Simulation runs | **16/16 — 0 abandoned calls** |
| Agent recycling | **✓** (168 completions, 20 agents, 120 ticks) |
| DB connections after load test | **1** (no leaks) |
| Exposed credentials | **None** (.env excluded) |
| Known test failures | **None** |

---

## Included Deliverables

### Source Code

| Path | Description |
|------|-------------|
| `app/api/` | FastAPI routers — campaigns, agents, calls, dialer, providers, simulation |
| `app/core/` | Enums, exceptions, state machines |
| `app/models/` | SQLAlchemy ORM models — Agent, Borrower, Call, Campaign, Outbox, Reservation, ProviderEvent, CampaignMetrics |
| `app/repositories/` | DB access layer — agent, borrower, call, campaign repositories |
| `app/services/` | Business logic — ProgressiveDialer, PredictivePacingEngine, SafetyController, CallAllocator, EventProcessor, ReconciliationService, MetricsService |
| `app/providers/` | Mock telecom providers — ProviderA, ProviderB, CircuitBreaker, ProviderFactory |
| `app/workers/` | Background workers — DialWorker, EventWorker, RecoveryWorker |
| `app/simulation/` | Simulation engine, scenarios, reports |
| `app/database.py` | SQLAlchemy engine and session factory |
| `app/main.py` | FastAPI application entry point |

### Tests (106 total)

| Category | Count | Description |
|----------|-------|-------------|
| Unit | 38 | Circuit breaker, event deduplication, predictive pacing, safety controller, state machines |
| Integration | 13 | Call lifecycle, predictive dialing, progressive dialing |
| Concurrency | 10 | Agent reservation races, capacity limits, connection management |
| Failure | 22 | Agent drop, duplicate events, out-of-order events, provider outage, worker crash |
| Simulation | 12 | All 4 scenarios, both providers, safety invariants, talk duration, determinism |
| **Total** | **106** | **All pass** |

### Scripts

| Script | Description |
|--------|-------------|
| `scripts/run_simulation.py` | Run 1–16 simulation scenarios with configurable parameters |
| `scripts/run_load_test.py` | Burst and sustained load tests |
| `scripts/run_workers.py` | Start background workers |
| `scripts/seed_demo.py` | Seed demo data for manual API exploration |

### Documentation

| File | Description |
|------|-------------|
| `README.md` | Complete setup, usage, and troubleshooting guide |
| `docs/architecture.md` | System design — components, data model, concurrency, workers |
| `docs/architecture-diagram.mmd` | Mermaid flowchart of full system |
| `docs/agent-state-machine.mmd` | Mermaid agent state machine |
| `docs/call-state-machine.mmd` | Mermaid call state machine |
| `docs/architecture-decision-record.md` | ADR-001 through ADR-007 |
| `docs/predictive-algorithm.md` | EWMA pacing math + corrected formula |
| `docs/failure-recovery.md` | 9 failure scenarios with detection and recovery |
| `docs/scalability-analysis.md` | 100 → 1K → 10K agents analysis |
| `docs/simulation-results.json` | Machine-readable results for all 16 simulation runs |
| `docs/simulation-results.md` | Human-readable simulation report with analysis |
| `docs/final-assignment-answer.md` | Answer to page-10 SmartDialer question |
| `docs/submission-acceptance-matrix.md` | Requirement-by-requirement audit matrix |

### Configuration and Infrastructure

| File | Description |
|------|-------------|
| `.env.example` | Environment variable template (no secrets) |
| `requirements.txt` | Python dependencies |
| `pyproject.toml` | Project metadata and pytest config |
| `alembic.ini` | Alembic migration config |
| `alembic/` | Database migrations (001_initial_schema.py) |
| `Dockerfile` | Container image definition |
| `docker-compose.yml` | Local development stack |
| `Makefile` | Common developer commands |

---

## Excluded Files

| Excluded | Reason |
|----------|--------|
| `.env` | Contains database credentials |
| `__pycache__/` | Python bytecode — not required |
| `.pytest_cache/` | Test cache — not required |
| `.git/` | Version control history |
| `venv/`, `.venv/` | Virtual environment — not required |

---

## Quick Start for Reviewer

```bash
# 1. Extract archive
unzip SmartDialer_Submission_Sharath_Kumar.zip
cd SmartDialer_Submission

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure database
cp .env.example .env
# Edit DATABASE_URL in .env to point to your PostgreSQL instance

# 5. Run migrations
python -m alembic upgrade head

# 6. Run tests (requires PostgreSQL with smartdialer_test database)
python -m pytest tests/ -q

# 7. Run all 16 simulation scenarios
python scripts/run_simulation.py --scenario all --provider all --agents 10 --ticks 160

# 8. Start API server
python -m uvicorn app.main:app --reload
# Visit http://localhost:8000/docs
```

---

## SHA-256 Checksum

See archive footer or run: `certutil -hashfile SmartDialer_Submission_Sharath_Kumar.zip SHA256`
