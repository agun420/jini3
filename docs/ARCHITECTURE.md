# Project Daybreak Architecture

```text
Phase 1 append-only recorder
    → immutable raw events
    → deployment-specific normalization
    → Phase 2 deterministic feature engine
    → immutable FeatureSnapshot / strict DaybreakInput
    → Phase 3 Structured Outputs evaluator
    → 77 invariants and Python truth replay
    → Phase 4 deterministic risk engine and reservation
    → Phase 5 paper-only Alpaca execution
    → trade updates, protection, and broker reconciliation
```

## v0.5.0 execution boundary

Only an approved risk decision with an active reservation can produce an order command. The execution service cannot alter quantity, entry, stop, or target values. It permits only Alpaca paper trading, serializes in-process execution events, and fails closed when broker identity or state cannot be proven.

Multi-process leadership, integrated session orchestration, end-of-day flattening, production alerts, and live-money execution remain outside this release.

## v0.6.0 orchestration boundary

The orchestration package coordinates timing and safety but does not absorb domain logic from the recorder, feature, evaluator, risk, or execution packages. `SessionHooks` is the typed integration seam. Leadership is fenced, audit records are append-only, kill switches require explicit reset, and flattening is restricted to provable Daybreak-owned quantities.
