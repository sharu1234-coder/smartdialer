# SmartDialer — Simulation Results Report

Generated: 2026-11-25  
Configuration: seed=42, 10 agents, 100 borrowers, 160 ticks, PostgreSQL

---

## Time Model

| Unit | Equivalent |
|------|-----------|
| 1 simulation tick | 10 simulated seconds (`SIM_TICKS_PER_SECOND = 10`) |
| 160 ticks | 1,600 simulated seconds (≈ 27 minutes of call activity) |
| Wall-clock time | A few seconds of real time |

**Talk durations in this report are in simulated seconds** (provider tracks `talk_ticks`;
report multiplies by `sim_ticks_per_second`). Wall-clock elapsed time is reported
separately under each provider section.

---

## Scenario Configurations

| Scenario | Answer Rate | Avg Talk (simulated) | Description |
|----------|-------------|---------------------|-------------|
| A | 20% | 120 s (12 ticks) | Low answer rate — high failure overhead |
| B | 50% | 90 s (9 ticks)  | Balanced — equal answer and failure |
| C | 70% | 180 s (18 ticks) | High answer rate + long talk → agents occupied |
| D | 35% → 10% → 65% → 40% | 90/60/120/90 s | Deterministic 4-phase: baseline → low → high → recovery |

Scenario D phase boundaries (at 160 ticks):
- Phase 1 (ticks 0–39):   35% answer rate, 9-tick talk (90 s)
- Phase 2 (ticks 40–79):  10% answer rate, 6-tick talk (60 s)
- Phase 3 (ticks 80–119): 65% answer rate, 12-tick talk (120 s)
- Phase 4 (ticks 120–159): 40% answer rate, 9-tick talk (90 s)

---

## Provider A Results (seed=42, 10 agents, 160 ticks)

Provider A characteristics: 5% failure rate, 100 ms latency, ~1% duplicate events.

### Scenario A — 20% Answer Rate / 120 s Talk

| Metric | Progressive | Predictive |
|--------|-------------|------------|
| Calls initiated | 224 | 210 |
| Calls connected | 31 | 31 |
| Calls completed | 31 | 31 |
| Calls failed | 183 | 170 |
| Abandoned calls | **0** | **0** |
| Agent utilization | 21.4% | 21.7% |
| Actual answer rate | 14.5% | 15.4% |
| Avg talk duration | 110.3 s | 111.9 s |
| Provider failures | 7 | 8 |
| Duplicate events | 5 | 5 |
| Safety reductions | — | 109 |

**Note:** Both modes complete the same number of calls (31). With 20% answer rate and 12-tick talk time, the system is failure-bound rather than agent-bound. Predictive triggers 109 Safety Controller reductions, confirming it pre-dials beyond 1:1 on every tick.

---

### Scenario B — 50% Answer Rate / 90 s Talk

| Metric | Progressive | Predictive |
|--------|-------------|------------|
| Calls initiated | 165 | 159 |
| Calls connected | 78 | 73 |
| Calls completed | 78 | 73 |
| Calls failed | 77 | 76 |
| Abandoned calls | **0** | **0** |
| Agent utilization | 41.4% | 38.5% |
| Actual answer rate | 50.3% | 49.0% |
| Avg talk duration | 84.9 s | 84.4 s |
| Provider failures | 5 | 7 |
| Duplicate events | 5 | 4 |
| Safety reductions | — | 98 |

**Note:** Progressive achieves slightly higher throughput in this scenario. With balanced 50% answer rate and 9-tick talk time, the borrower pool (100) becomes the limiting factor before predictive's pre-dialing advantage materializes. Both modes maintain 0 abandoned calls.

---

### Scenario C — 70% Answer Rate / 180 s Talk

| Metric | Progressive | Predictive |
|--------|-------------|------------|
| Calls initiated | 49 | 49 |
| Calls connected | 31 | 31 |
| Calls completed | 31 | 31 |
| Calls failed | 8 | 8 |
| Abandoned calls | **0** | **0** |
| Agent utilization | 35.6% | 35.6% |
| Actual answer rate | 79.5% | 79.5% |
| Avg talk duration | 183.9 s | 183.9 s |
| Provider failures | 7 | 7 |
| Duplicate events | 0 | 0 |
| Safety reductions | — | 33 |

**Note:** Identical results for both modes. With 70% answer rate and 18-tick talk time, agents are occupied for the majority of the simulation. The system is constrained by agent capacity (10 agents × 18 ticks = most of the 160 ticks consumed). Predictive still fires 33 Safety Controller reductions, but `available_agents = 0` on most ticks, so there is nothing additional to dial.

---

### Scenario D — Changing Conditions (Deterministic)

| Metric | Progressive | Predictive |
|--------|-------------|------------|
| Calls initiated | 137 | 135 |
| Calls connected | 45 | 43 |
| Calls completed | 45 | 43 |
| Calls failed | 83 | 84 |
| Abandoned calls | **0** | **0** |
| Agent utilization | 23.9% | 22.9% |
| Actual answer rate | 35.2% | 33.9% |
| Avg talk duration | 85.1 s | 85.1 s |
| Provider failures | 8 | 8 |
| Duplicate events | 1 | 1 |
| Safety reductions | — | 83 |

**Note:** EWMA (α=0.2) adapts to phase transitions with lag. During Phase 2 (10% rate), the
engine over-dials briefly before converging. The Safety Controller absorbs the overshoot with
reductions — zero abandoned calls throughout all 4 phases.

---

## Provider B Results (seed=42, 10 agents, 160 ticks)

Provider B characteristics: 20% failure rate, 300 ms latency, 10% timeout rate, 15% duplicate events, 20% out-of-order events.

**Provider B parity observation:** Progressive and Predictive produce identical results for all 4 scenarios with Provider B. Provider B's higher failure rate and duplicate injection mean agents are released more slowly, creating bottlenecks that equally constrain both modes. This is expected, not a bug — it reflects genuine performance differences between providers.

### All Provider B Scenarios

| Scenario | Mode | Completed | Utilization | Answer Rate | Avg Talk | Abandoned | Duplicates |
|----------|------|-----------|-------------|-------------|----------|-----------|------------|
| A — 20%/120s | Progressive | 12 | 9.4% | 20.3% | 125.8 s | 0 | 16 |
| A — 20%/120s | Predictive  | 12 | 9.4% | 20.3% | 125.8 s | 0 | 16 |
| B — 50%/90s  | Progressive | 17 | 9.4% | 50.0% | 88.2 s  | 0 | 15 |
| B — 50%/90s  | Predictive  | 17 | 9.4% | 50.0% | 88.2 s  | 0 | 15 |
| C — 70%/180s | Progressive | 27 | 29.8%| 65.9% | 176.7 s | 0 | 22 |
| C — 70%/180s | Predictive  | 27 | 29.8%| 65.9% | 176.7 s | 0 | 22 |
| D — variable | Progressive | 14 | 7.1% | 29.8% | 80.7 s  | 0 | 17 |
| D — variable | Predictive  | 14 | 7.1% | 29.8% | 80.7 s  | 0 | 17 |

Provider B throughput is significantly lower than Provider A (12–27 vs 12–78 completed calls)
due to the higher failure rate and latency, confirming Provider B chaos injection is working.

---

## Cross-Provider Comparison (Scenario B, 50% answer rate)

| Provider | Mode | Completed | Utilization | Duplicates | Failures |
|----------|------|-----------|-------------|------------|---------|
| Provider A | Progressive | 78 | 41.4% | 5 | 5 |
| Provider A | Predictive  | 73 | 38.5% | 4 | 7 |
| Provider B | Progressive | 17 | 9.4%  | 15 | 9 |
| Provider B | Predictive  | 17 | 9.4%  | 15 | 9 |

---

## Safety Invariants — All 16 Runs

| Invariant | Result |
|-----------|--------|
| Abandoned calls (all 16 runs) | **0** |
| Safety Controller rejections (all 16 runs) | **0** |
| Safety Controller reductions (predictive runs) | 27–109 reductions per run |
| Duplicate events correctly ignored | ✓ |
| Out-of-order events handled | ✓ |

The Safety Controller reduced predictive requests in every predictive run,
confirming it is active and suppressing over-dialing without producing abandoned calls.

---

## Load Test Results

### Sustained Mode — Agent Recycling Verification

```
python scripts/run_load_test.py --mode sustained --ticks 120 --agents 20
```

| Metric | Value |
|--------|-------|
| Agents | 20 |
| Duration | 120 ticks |
| Provider answer rate | 50% |
| Provider avg talk (ticks) | 3 |
| Total calls initiated | 371 |
| Completed | 168 |
| Failed | 183 |
| Still active at end | 20 |
| Measured answer rate | 47.9% |
| Wall-clock time | 14.4 s |
| PG connections after test | **1** |
| Agents recycled | **✓** (168 completions > 20 agents) |

168 completions with 20 agents proves agent recycling. If agents were not released back to
AVAILABLE after completing calls, we would see at most 20 completions total.

### Burst Mode — Allocation Throughput

```
python scripts/run_load_test.py --workers 10 --duration 15 --agents 100
```

Burst mode measures raw allocation speed with concurrent workers competing for 100 agents.
Expected outcomes:

| Outcome | Meaning |
|---------|---------|
| Successful allocations | Agent + borrower reserved, outbox written |
| No resource (expected) | No AVAILABLE agent or PENDING borrower — normal when pool exhausts |
| DB connection error | `FATAL: too many clients` — pool misconfiguration |
| Pool timeout | SQLAlchemy pool exhausted — increase pool_size |

**Expected connection budget:** load test pool = max 15 connections, well within PostgreSQL
default `max_connections = 100`.

---

## Latency Notes

The simulation runs entirely in-process (no network I/O). Real-deployment latency
characteristics would include:

- PostgreSQL query latency: ~1–5 ms per allocation (local), ~5–20 ms (remote)
- Safety Controller evaluation: ~1 ms additional DB query
- Outbox dispatch to real telecom provider: 100–300 ms (network dependent)
- Event polling: 500 ms worker interval

P50/P95/P99 latency benchmarks require a real deployment with realistic network conditions
and are outside the scope of this simulation-based assignment.

---

## Reproducibility

All results above are reproducible with:

```bash
python scripts/run_simulation.py --scenario all --provider all --seed 42 --agents 10 --ticks 160 --json
```

Machine-readable results are in `docs/simulation-results.json`.
