# Phase 9 — Production-Candidate Review

## Purpose

Phase 9 converts the accumulated Daybreak evidence into one deterministic paper-release-candidate decision. It does not change trading logic and cannot authorize an order.

## Evidence chain

The review request binds six required release artifacts: source archive, wheel, combined migration SQL, generated schema bundle, verification report, and the frozen Daybreak v6.3 specification. Each artifact has a unique canonical name, byte size, and SHA-256 hash.

The artifact manifest hash is the package reviewed by every approval role. Approvals referring to any other manifest hash are invalid.

## Configuration freeze

The configuration freeze requires:

- `environment = paper`
- `live_execution_enabled = false`
- release `1.0.1`
- specification `6.3`
- migration head `0009_phase9_release`
- a deterministic public configuration hash
- the exact specification hash
- sorted component versions

Development or live configurations cannot be frozen as production candidates.

## Review gates

The default policy requires a green test suite, minimum test and schema counts, clean installation, extracted-source reproducibility, successful compilation, wheel smoke validation, zero secret findings, qualified paper evidence, verified rollback controls, completed independent review, all role approvals, and no open medium-or-higher findings.

Low and informational findings may remain as warnings. High, critical, failed-test, secret, live-configuration, or explicit approval-rejection evidence produces a blocked report. Missing operational evidence produces an incomplete report.

## Status meanings

- `incomplete`: required evidence or approvals have not been supplied or verified.
- `blocked`: supplied evidence contains an explicit safety or quality failure.
- `paper_release_candidate`: every paper release gate passed.

`live_capital_eligible` is always false.

## Persistence

Phase 9 adds append-only tables for evidence manifests, build attestations, configuration freezes, and candidate reports. Existing rows cannot be updated or deleted through normal database operations.

## External acceptance

The offline package can verify software behavior, schemas, fixtures, hashes, and release logic. Target-VM credentials, authenticated broker behavior, production PostgreSQL operations, real market sessions, and independent human approvals must be collected outside the build environment.
