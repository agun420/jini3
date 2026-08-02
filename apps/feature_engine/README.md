# Feature Engine Application

The v0.2.0 feature engine is exposed through the unified CLI:

```bash
daybreak build-features INPUT_CONTEXT.json --output SNAPSHOT.json
```

The command validates the strict `FeatureContext`, builds the deterministic snapshot, and writes canonical JSON. It performs no network calls, LLM calls, or broker actions.
