# Schema versioning

Canonical serialized contracts live in directories named `shared/schemas/v{major}`. Phase 1 defines `v1`.

## Compatibility rules

A change is **backward compatible within v1** only when all existing v1 documents remain valid and retain the same meaning. Examples include documentation improvements, adding a new example fixture, or adding a new independent schema definition without changing existing definitions. Phase 3's `Conversation` contract is such an additive definition.

A change requires a **new major schema directory** when it removes or renames a field, changes a field's meaning or type, strengthens validation so existing documents fail, or changes an authorization-relevant interpretation.

Before a new major version is accepted:

1. keep the older schema in Git;
2. document the old-to-new transformation;
3. add migration fixtures and tests;
4. update Python and TypeScript bindings;
5. decide how readers negotiate or reject unsupported versions;
6. add persistence migration steps when storage exists.

`Event.schema_version` identifies the event payload contract. For all other Phase 1 models, the enclosing API, file, or future protocol declaration must identify the schema major version. Silent reinterpretation is forbidden.

Phase 7 adds the independent `workspace.schema.json` in the existing v1 directory.
This is additive: it does not change any existing agent-core document. Workspace event
payloads reference its `WorkspaceCommand` definition, while the trusted component
registry references `ComponentRegistry`. Breaking either representation requires a new
major schema directory and event migration plan.
