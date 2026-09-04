# Adding an Agent Skill

Course Agent skills use the standard Agent Skills directory shape:

```text
skills/example-skill/
├── SKILL.md
└── references/
    └── optional-detail.md
```

`SKILL.md` requires standard YAML frontmatter and a non-empty Markdown body:

```markdown
---
name: example-skill
description: Explain when the agent should load this skill.
---

Use the authorized course resources as the source of truth.
```

The name must be lowercase kebab-case and must match the ID registered in
`skills/registry.json`. Keep the description concise because every principal authorized for
the skill receives it at the start of a run. Keep detailed procedures in the body and large or
specialized detail in `references/*.md`; link those references from `SKILL.md` so the agent
knows when they are useful.

Add a registry entry with one audience:

```json
{
  "id": "example-skill",
  "directory": "example-skill",
  "audience": "students"
}
```

Audiences are `public`, `authenticated`, `students`, and `instructors`. Students includes
instructors, matching private course-resource policy. TA and admin do not inherit student or
instructor access. Do not place secrets, user data, or authentication claims in a skill;
authorization always comes from the trusted login session and deterministic platform policy.

The application validates the registry and scans frontmatter plus reference names at startup;
full bodies and reference contents are read only on demand. Restart the API after changing the
registry, metadata, or reference layout. Run `uv run pytest python/tests/test_skills.py` and add
positive and negative audience tests for any new privileged workflow.
