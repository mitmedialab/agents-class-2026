# Contributing

Read [CONSTITUTION.md](CONSTITUTION.md) and [AGENTS.md](AGENTS.md) before making changes. The constitution defines the architecture and implementation order.

Keep contributions focused on the current phase. Framework-specific code must not leak into `agent_core`, and stable contract changes must update both language bindings, the canonical schema, shared examples, tests, and documentation.

Before opening a pull request, run:

```bash
make check
```

Do not commit credentials, private student data, generated model-provider state, local file contents, virtual environments, or package installation directories.
