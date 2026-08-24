# Agent core schema v1

`agent-core.schema.json` is the canonical language-neutral definition of the stable wire contracts. Phase 3 adds `Conversation` without changing existing v1 documents. Definitions are addressed by JSON Pointer, for example:

```text
https://agents.media.mit.edu/schemas/v1/agent-core.schema.json#/$defs/Event
```

`examples/contracts.json` contains shared valid documents consumed by both Python and TypeScript tests. A schema change is incomplete until both language implementations and the shared examples agree.

See `docs/SCHEMA_VERSIONING.md` before changing this directory.
