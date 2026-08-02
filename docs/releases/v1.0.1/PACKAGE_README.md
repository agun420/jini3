# Project Daybreak v1.0.1 Remediation Package

This package supersedes the v1.0.0/v6.2 release evidence.

## Contents

- `Project_Daybreak_v1_0_1.zip` — complete source repository
- `project_daybreak-1.0.1-py3-none-any.whl` — installable wheel
- `Project_Daybreak_v1_0_1_migrations.sql` — combined PostgreSQL migrations
- `Project_Daybreak_v1_0_1_schemas.zip` — 57 generated JSON Schemas
- `Project_Daybreak_v6.3_Final.md` and `.docx` — canonical refined specification
- `Project_Daybreak_v6.2_Audit_Report.md` — nine-finding audit reconstruction
- verification report, configuration freeze, build attestation, evidence manifest, release manifest, and checksums

## Verification

The release passed 285 source tests and 285 extracted-source tests. It contains 77 evaluator invariants. Live capital remains disabled. Target-VM paper acceptance remains required.

Verify all files with:

```bash
sha256sum -c Project_Daybreak_v1_0_1_SHA256SUMS.txt
```
