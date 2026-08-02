# Evaluator application

Phase 3 is implemented in `daybreak_evaluator`.

Use `EvaluatorService.evaluate_primary()` for the time-critical primary path. Use `EvaluatorService.evaluate_shadow()` in a separate background task for non-authorizing disagreement analysis.

The CLI command `daybreak evaluate` runs only the primary path by default. `--await-shadow` is an explicit research mode and must not be used for timed order eligibility.
