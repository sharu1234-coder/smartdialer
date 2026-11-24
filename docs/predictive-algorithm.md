# Predictive Pacing Algorithm

## Problem Statement

In Progressive mode, one call is placed per available agent. If only 30% of calls are answered, agents spend 70% of their time idle. Predictive mode compensates by launching calls *before* agents become free, so that by the time a call is answered, an agent is likely available.

## EWMA Answer Rate Estimation

We use an Exponentially Weighted Moving Average (EWMA) to estimate the answer rate. EWMA weights recent observations more heavily, allowing the system to adapt to changing conditions.

```python
EWMA_ALPHA = 0.2

def update_answer_rate(current_estimate: float, new_observation: float) -> float:
    return EWMA_ALPHA * new_observation + (1 - EWMA_ALPHA) * current_estimate
```

**Alpha = 0.2** means each new observation contributes 20% to the estimate, and the existing estimate retains 80% of its weight. This provides a good balance between responsiveness and stability.

### Cold Start

We require `MIN_SAMPLE_SIZE = 5` observations before trusting the EWMA. Until then, we use a conservative fallback: `CONSERVATIVE_FALLBACK_RATE = 0.5` (assume 50% answer rate). This prevents over-dialing when we have insufficient data.

## Desired Calls Formula

```
raw_desired = ceil(available_agents / effective_answer_rate)
```

`effective_answer_rate` is the EWMA estimate, or `CONSERVATIVE_FALLBACK_RATE = 0.5` during cold start.

**Intuition**: If 5 agents are free and the answer rate is 50%, we need to dial 10 calls to fill all 5 agents. Each call has a 50% chance of answering; 10 dials → 5 answers → 5 agents occupied.

**Why in-flight calls are not subtracted:**  
Every in-flight call (RESERVED, INITIATED, RINGING, ANSWERED, CONNECTED) has *already reserved its own agent*. Those agents are not in the `available_agents` count. Subtracting `in_flight` again would double-count consumed capacity and produce zero requests in a busy system.

> **Bug fixed (audit 2026-11-25):** The original formula was  
> `capacity_buffer = available_agents - in_flight_calls`  
> which caused predictive mode to request zero calls whenever agents were busy — identical behaviour to progressive mode. The fix removes the in-flight subtraction entirely; the Safety Controller still enforces `approved ≤ available_agents` as the hard ceiling.

## Safety Caps

### Hard Cap: MAX_DIAL_RATIO
```
hard_cap = available_agents * MAX_DIAL_RATIO (3.0)
desired_calls = min(desired_calls, hard_cap)
```

This prevents catastrophic over-dialing if the EWMA is miscalibrated. Even with a 1% estimated answer rate, we will never dial more than 3× the number of available agents.

### Provider Health Adjustment
```
factor = {HEALTHY: 1.0, DEGRADED: 0.5, UNHEALTHY: 0.0}
desired_calls = floor(desired_calls * factor)
```

When the provider is degraded, we halve our desired call count. When unhealthy, we dial zero.

## Safety Controller Gate

The pacing engine output is *advisory*. The Safety Controller then validates it against live DB state:

1. Query `SELECT COUNT(*) FROM agents WHERE status = 'AVAILABLE'` (never trust the caller)
2. If requested > available: REDUCE to available
3. If requested ≤ available: APPROVE
4. Provider health checks override all of the above

This independence ensures that a pacing engine bug (e.g., cached stale counts) cannot cause agent overload.

## Adaptation to Changing Conditions (Scenario D)

Scenario D uses **deterministic** phase transitions (not random) to test EWMA adaptation reproducibly:

| Phase | Tick range | Answer rate | Avg talk (ticks) | Avg talk (simulated s) |
|---|---|---|---|---|
| 1 — Baseline  | 0 – 25%   | 35% | 9  | 90  |
| 2 — Low       | 25 – 50%  | 10% | 6  | 60  |
| 3 — High      | 50 – 75%  | 65% | 12 | 120 |
| 4 — Recovery  | 75 – 100% | 40% | 9  | 90  |

When the answer rate changes mid-campaign, the EWMA converges to the new rate over time. With α=0.2 and an answer rate that halves from 0.5 to 0.25:

- After 1 tick: 0.2 × 0.25 + 0.8 × 0.5 = 0.45
- After 5 ticks: ≈ 0.37
- After 10 ticks: ≈ 0.31
- After 20 ticks: ≈ 0.27 (approaches 0.25 asymptotically)

The system over-dials slightly during the transition period (the Safety Controller's REDUCE decisions absorb this overshoot without abandons), then self-corrects. A lower alpha adapts more slowly but is more stable; a higher alpha adapts faster but is noisier.

## Abandon Rate

The abandon rate is `max(0, (answered_calls - available_agents) / answered_calls)`. This occurs when the system dials more calls than can be served by available agents. The Safety Controller's REDUCE decision caps this.

**Measured result across all 16 simulation runs (4 scenarios × 2 providers × 2 modes):** abandoned calls = 0 in every run. The Safety Controller's REDUCE path fired in all predictive runs (83–109 reductions for Provider A), confirming it is active and suppressing over-dial correctly.

## Simulation Results Reference

Full machine-readable results are in `docs/simulation-results.json`. Summary (seed=42, 10 agents, 160 ticks, provider_a):

| Scenario | Mode | Completed | Utilization | Abandoned |
|---|---|---|---|---|
| A — 20% / 120s | Progressive | 31 | 21.4% | 0 |
| A — 20% / 120s | Predictive  | 31 | 21.7% | 0 |
| B — 50% / 90s  | Progressive | 78 | 41.4% | 0 |
| B — 50% / 90s  | Predictive  | 73 | 38.5% | 0 |
| C — 70% / 180s | Progressive | 31 | 35.6% | 0 |
| C — 70% / 180s | Predictive  | 31 | 35.6% | 0 |
| D — variable   | Progressive | 45 | 23.9% | 0 |
| D — variable   | Predictive  | 43 | 22.9% | 0 |
