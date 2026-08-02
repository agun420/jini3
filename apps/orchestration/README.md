# Orchestration application

The reusable implementation lives in `daybreak_orchestration`.

A target deployment supplies a `SessionHooks` implementation that maps persisted Phase 1 events into a Phase 2 `FeatureContext`, calls the Phase 3 evaluator, constructs Phase 4 risk requests from fresh account/quote state, and submits approved Phase 5 paper executions.

Run `daybreak acceptance-check --online-paper --confirm-paper` before starting a target-specific session runner.
