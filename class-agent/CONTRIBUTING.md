# Contributing

Read the repository-root [AGENTS.md](../AGENTS.md), this package's
[AGENTS.md](AGENTS.md), every nearer scoped `AGENTS.md`, and the relevant sections of
[CONSTITUTION.md](CONSTITUTION.md) before making changes. The constitution defines the
architecture and implementation order; the agent files make its day-to-day constraints
explicit.

Keep contributions focused on the current phase. Framework-specific code must not leak into `agent_core`, and stable contract changes must update both language bindings, the canonical schema, shared examples, tests, and documentation.

Use the pull request template. Explain which decisions remain semantic Course Agent
choices, which are deterministic platform policy, which values belong to configuration,
registries, resources, or design tokens, and why any new hardcoded value is an intentional
invariant or bound. Reuse existing extension points and avoid adding unrelated special
cases to large orchestration modules.

AI assistance does not reduce the author's review responsibility. The contributor must
inspect every generated change, verify that it integrates with repository architecture and
visual conventions, remove unsupported or speculative code, and report exactly which
checks were run.

Before opening a pull request, run:

```bash
make check
```

Do not commit credentials, private student data, generated model-provider state, local file contents, virtual environments, or package installation directories.
