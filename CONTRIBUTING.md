# Contributing

1. Work on a branch.
2. Add or update tests for every behavior change.
3. Run `make quality` while iterating and `make verify` before opening a pull request.
4. Keep `ruff format --check .`, `ruff check .`, and `mypy daybreak daybreak_*` green repository-wide.
5. Do not commit secrets, raw credentials, production account identifiers, or live order data.
6. Deterministic modules must not access the wall clock, network, environment, or mutable global state.
7. Any change to the Daybreak evaluator contract requires synchronized schema, invariant, fixture, and specification updates.
8. Any change to a hashed model requires regeneration of dependent fixtures, schemas, attestations, and release checksums.
