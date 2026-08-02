# Phase 4 Deterministic Position-Risk Engine

Project Daybreak v0.4.0 adds `position_risk_policy_v1` as a pure Python sizing and account-risk layer. The module accepts only evaluator-approved setups and cannot submit, cancel, replace, or monitor broker orders.

## Runtime boundary

```text
Validated Daybreak approved setup
        │
        ▼
Fresh account + quote + liquidity snapshots
        │
        ▼
Account, market, stream, database, and cutoff gates
        │
        ▼
Decimal stop, target, slippage, and risk calculations
        │
        ▼
Independent quantity caps
        │
        ▼
Approved reservation artifact or fail-closed rejection
```

Inputs from `qualified_not_selected`, `excluded_tickers`, and `schema_failures` are not accepted by the sizing request model.

## Deterministic profiles

Two built-in policy profiles are included:

- `paper_v1`: 0.25% base risk per trade, up to three concurrent positions.
- `live_pilot_v1`: 0.10% base risk per trade, one position and one entry per day.

Both profiles disable margin, fractional sizing, and overnight holding.

## Quantity caps

The final whole-share quantity is the minimum of:

1. Per-trade risk budget
2. Remaining aggregate open-risk capacity
3. Remaining hard daily-loss capacity
4. Cash-supported buying power after reserve
5. Position-notional limit
6. Gross-long-exposure limit
7. ADV participation limit
8. Premarket-volume participation limit

Ties are reported using the policy's fixed binding-cap precedence.

## Risk flags

The engine consumes the canonical v6.3 risk flags. Reducing flags use the minimum applicable multiplier, not a product:

- `parabolic_vwap_extension`: 0.50
- `low_float`: 0.50
- `spiky_volume`: 0.60
- `secondary_source`: 0.75
- borrow flags: 1.00 for long trades in v1

## Persistence

The Phase 4 migration adds append-only tables for:

- sizing requests
- sizing decisions
- risk reservations
- reservation lifecycle events

The risk service stores the request first, then atomically stores an approved decision with its initial reservation. No broker submission exists in this release.

## Replay

`verify_risk_replay()` recomputes the decision from the frozen request and requires byte-identical canonical output.

## CLI

```bash
daybreak risk-size request.json --output decision.json
daybreak risk-size-batch batch.json --output batch-result.json
daybreak risk-schema decision --output schemas/risk_decision.schema.json
```

## Safety boundary

v0.4.0 does not provide:

- Alpaca account or quote adapters
- broker order construction
- order submission
- fill or partial-fill handling
- cancellation or replacement
- emergency liquidation
- live kill-switch actions

It emits deterministic decisions and reservation artifacts only. Those artifacts are inputs to the future v0.5.0 execution and reconciliation release.
