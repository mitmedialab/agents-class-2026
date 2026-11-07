# Shared registries

`resources.json` is the generated, versioned Phase 6 registry for public course
resources. Do not edit it directly. Edit or add a `resource.json` sidecar under
`shared/course/`, then run `python -m course_server.index_resources` or restart the
production backend. Each generated entry maps a canonical `course://` URI to a
repository-owned file and includes public title, description, media type, visibility,
and publication status. Paths are resolved under `shared/`; entries that escape that
root are rejected.

Published slide entries also carry a deck-local `accessibility_path` when the source
manifest declares `accessibility_file`. These page descriptions join extracted PDF text
for reads and search; the sidecar is not a downloadable asset.
Slide entries can also carry a deck-local `caption_path` from `caption_file`.
Numbered contextual captions join the same page text for reads and search; text-only
pages can have no caption. This optional field extends registry schema version 1 without
changing existing entries.

This registry maps directly to future MCP resources without defining a competing
external protocol.
