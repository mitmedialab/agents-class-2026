# Agent core schema v1

`agent-core.schema.json` is the canonical language-neutral definition of the stable agent wire contracts. Phase 3 adds `Conversation` without changing existing v1 documents. `workspace.schema.json` adds the Phase 7 component manifest, workspace state, semantic document anchor, and command contracts. Definitions are addressed by JSON Pointer, for example:

```text
https://agents.media.mit.edu/schemas/v1/agent-core.schema.json#/$defs/Event
https://agents.media.mit.edu/schemas/v1/workspace.schema.json#/$defs/WorkspaceCommand
```

`examples/contracts.json` contains shared valid documents consumed by both Python and TypeScript tests. A schema change is incomplete until both language implementations and the shared examples agree.

See `docs/SCHEMA_VERSIONING.md` before changing this directory.
