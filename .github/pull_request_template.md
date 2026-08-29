## Summary

<!-- What user-visible or architectural outcome does this PR produce? -->

## Why this design fits the repository

<!--
Name the existing component, adapter, policy, schema, registry, resource, or token system
this change reuses. If a new abstraction is necessary, explain its single responsibility.
Identify the relevant CONSTITUTION.md and docs sections.
-->

### Decision ownership

<!-- Complete each applicable line. -->

- Course Agent choices:
- Deterministic platform decisions:
- Configuration/registry/resource/token changes:
- Deliberately hardcoded values and why they are invariants, bounds, safe defaults, or
  trusted allowlists:

## Architecture checklist

- [ ] I read the root and applicable scoped `AGENTS.md` files and the relevant constitution
      and documentation sections.
- [ ] The change is limited to the requested scope/current authorized phase and contains no
      speculative feature, abstraction, dependency, or unrelated cleanup.
- [ ] Free-form user intent remains an agent-owned semantic choice; it is not implemented as
      browser/API keyword matching.
- [ ] Authentication, authorization, identity, validation, redaction, sandboxing,
      confirmation, and external effects remain deterministic platform responsibilities.
- [ ] Changeable values live in typed configuration, registries, maintained resources, or
      design tokens rather than scattered literals.
- [ ] Existing extension points were reused, and coherent logic was not appended as
      unrelated special cases to a large orchestrator.
- [ ] No maintained course data, private data, secret, backing path, provider object, or
      framework-owned state was put in the wrong layer or persisted representation.

## Stable interfaces and durable data

- [ ] No stable interface, versioned schema, or durable data representation changed.
- [ ] Or: the PR explains the schema-version decision, synchronized Python/TypeScript
      bindings, fixtures/tests, migration/backfill/rollback impact, and documentation.

<!-- Delete one of the two lines above and explain applicable compatibility consequences. -->

## UI review

<!-- Remove this section when no visible UI is affected. -->

- [ ] The change uses first-party components, semantic variants, and existing design tokens.
- [ ] It preserves the sparse monochrome editorial visual language rather than introducing
      generic dashboard/card-grid styling or a competing visual system.
- [ ] Desktop, narrow/responsive, keyboard, focus, loading/error, and reduced-motion states
      were checked as applicable.
- [ ] Before/after screenshots or recordings are attached below.

## Verification

<!-- List exact commands and their results. Never mark a command as run if it was not. -->

```text

```

- [ ] Focused regression tests cover the changed behavior and important failure cases.
- [ ] `git diff --check` passes and the complete diff was reviewed.
- [ ] `make check` passes, or the reason it was not run is stated below.

Checks not run and why:

## AI-assisted work

- [ ] I personally reviewed every AI-generated change for integration with repository
      conventions, not only compilation or test success.
- [ ] I verified that generated code did not duplicate an existing abstraction, invent an
      unsupported component/tool/resource, or hardcode a choice in the wrong layer.
- [ ] I removed placeholders, fabricated claims, unused abstractions, and unverified
      comments/documentation.

## Deviations and follow-ups

<!-- State any deliberate constitution deviation, known limitation, or separately scoped follow-up. -->
