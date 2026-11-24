# Final Assignment Answer

## The Core Question

> *How do you design a system where the pacing engine can be aggressive about dialing while the safety controller independently guarantees you never exceed agent capacity?*

## Answer

The key insight is **separation of concerns through architectural independence**.

### The Pacing Engine is Intentionally Naive

The pacing engine's job is to maximize throughput. It computes:

```
desired_calls = ceil((available_agents - in_flight_calls) / answer_rate)
```

It doesn't care whether the system can actually serve those calls. It just says: "given this answer rate and this many agents, we should be dialing N calls right now."

This naivety is a feature. If the pacing engine also enforced limits, it would need to handle concurrency (what if another worker already reserved agents since we last checked?), circuit breaker state, and degraded provider conditions. That coupling would make both components harder to test and reason about.

### The Safety Controller Never Trusts the Pacing Engine

The Safety Controller's independence is enforced architecturally, not just by convention:

1. **It never receives agent capacity as a parameter.** The calling code cannot pass a "trusted" agent count. The SC always queries `SELECT COUNT(*) FROM agents WHERE status = 'AVAILABLE'` itself.

2. **It queries at evaluation time, not at planning time.** Between when the pacing engine computed its estimate and when the SC evaluates it, 10ms may have passed and another worker may have reserved agents. The SC sees the current state.

3. **It has its own audit log** (`SafetyEvaluation`) that records every check, every reduction, and every rejection independently of the pacing engine's logs.

### Why This Design is Correct

Consider the failure modes:

**Bug in pacing engine** (overestimates available agents): SC queries DB, sees true count, reduces to what's actually available. Bug contained.

**Race condition** (two workers both estimate 5 agents available): Each worker passes their requests to SC. First SC evaluation approves 5. Second SC evaluation (milliseconds later) now sees 0 available, rejects. Only 5 calls placed total. No overload.

**Provider outage** (circuit breaker opens): SC checks circuit breaker health before approving. Returns REJECT or FALLBACK. Pacing engine's output is irrelevant.

**Agent drop** (40% agents go offline): SC queries DB, sees reduced count, reduces approved calls. The pacing engine doesn't need to be updated — SC catches it.

### The Deeper Point: Why Not Just Trust the Pacing Engine?

Because distributed systems have no "current state." By the time you read a value, it may have changed. The only safe approach for capacity enforcement is to **check the actual DB state at the moment of decision**, not to trust any cached or computed value.

The Safety Controller is a correctness boundary, not a performance optimization. Its DB query costs ~1ms. That's the price of safety.

### What This Enables

This design means you can:
- Develop and test the pacing engine and safety controller completely independently
- Deploy a new pacing algorithm (e.g., Erlang C-based) without changing the safety contract
- Have multiple pacing engines (one per campaign, different algorithms) all going through the same SC
- Prove safety properties by testing SC in isolation with just a DB, no pacing engine

### Summary

The answer to "how do you stay safe while being aggressive" is: **let the pacing engine be as aggressive as it wants, but put an independent gate between its output and actual call dispatch**. The gate is not a bottleneck — it's a 1ms query. The gate cannot be bypassed by any pacing engine bug. The gate is independently auditable.

This is the same principle as a [safety interlock](https://en.wikipedia.org/wiki/Interlock_(engineering)) in physical systems: the control logic and the safety logic are separate, and the safety logic has physical authority that the control logic cannot override.
