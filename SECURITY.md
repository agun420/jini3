# Security Policy

- Store Alpaca, OpenAI, database, and vendor credentials only in environment variables or an external secret manager.
- Never commit `.env` files.
- Use a dedicated Alpaca paper account for Daybreak; do not share its positions with another strategy or manual trading.
- Treat all broker timeouts as indeterminate until reconciled.
- Live execution is unavailable in v1.0.2. Do not weaken endpoint, environment, or `live_execution_enabled` guards.
- Treat fencing tokens as mandatory write preconditions in every concrete downstream hook.
- Authenticate human approvers outside the JSON evidence record; reviewer IDs alone are not digital signatures.
- Report suspected credential exposure by rotating the credential immediately before investigating logs.
