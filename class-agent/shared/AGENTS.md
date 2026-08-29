# Shared contracts and resources instructions

These rules apply to `shared/` in addition to the repository-root and `class-agent`
instructions.

## Schemas

- Versioned JSON Schema is the language-neutral authority for serialized contracts.
- A schema change must be classified as compatible/additive or breaking before editing.
- Keep Python models, TypeScript types, shared examples/fixtures, validators, tests, and
  schema-version documentation synchronized.
- Use explicit bounded schemas. Reject unknown fields where the existing contract does;
  do not weaken validation merely to accept one generated payload.
- Persisted-data implications require migration and backward-compatibility analysis.

## Course resources

- `shared/course/` contains maintained course information. Runtime code references it by
  registered opaque URI and asset ID, never by exposing its backing path.
- Keep resource metadata beside its source through `resource.json`. Maintain human-readable
  and machine-readable forms together when both are canonical.
- Do not copy syllabus, schedule, application, instructor, FAQ, or repository content into
  Python, React, prompts, tests, or component props as a second maintained source.
- Course workflow guidance belongs in the relevant maintained guide or standard Skill;
  global runtime prompts should not become the content store.
- Never place applicant data, student-private content, credentials, uploads, or generated
  provider state in public shared resources.

## Registries and assets

- `shared/registry/components.json` is the trusted native component catalog. Changes must
  remain synchronized with renderer support, Python/TypeScript validators, operations,
  tests, and documentation.
- `shared/registry/resources.json` is generated from resource manifests. Change the source
  manifest/content and run the documented indexing process; do not maintain the aggregate
  manually.
- Asset IDs are exact registered identifiers scoped to their resource. Do not invent IDs,
  publish backing paths, or convert relative file paths into public URLs.
- Registries describe discoverable capabilities; they do not replace authorization at
  execution time.

Run the schema, course-resource, workspace, and indexing tests relevant to the change and
review generated diffs before handoff.
