# Web application instructions

These rules apply to `apps/web/` in addition to the repository-root and `class-agent`
instructions. Read `docs/UI.md`, `docs/WORKSPACE.md`, and `docs/API.md` for changes that
touch their respective behavior.

## Responsibility

`apps/web` composes the Course Agent product. It owns browser-side orchestration, API/SSE
integration, conversation presentation, and placement of trusted first-party renderers.
It does not own wire contracts, workspace validation, reusable design primitives, course
content, identity, authorization, or agent intent recognition.

- Import protocol types from `@class-agent/protocol`; do not recreate wire types locally.
- Use `@class-agent/workspace` for workspace parsing/reduction and `@class-agent/ui` for
  reusable renderers and controls.
- Keep authentication authoritative on the server. The client sends opaque cookies and
  must never construct a user ID, role, permission, or privileged tool request.
- Project canonical events and validated workspace commands. Do not store React trees,
  model-provider objects, raw tool internals, or a second canonical history in browser
  state.
- Keep API endpoints behind the existing API adapter and configurable base URL rather than
  scattering request construction through components.

## Agent-owned behavior

Free-form intent belongs to the Course Agent. Never add keyword, regex, phrase-list, or
route-level heuristics that inspect chat text to decide which application workflow, tool,
resource, or workspace component to use. An explicit UI control may invoke its documented
canonical action; ordinary typed language must travel through the agent.

The browser renders only verified platform activity and final user-facing output. Do not
display hidden reasoning, non-final model prose, private tool arguments/results, internal
resource IDs, filesystem paths, or unsanitized provider errors.

## Workspace behavior

- Preserve the conversation-plus-workspace product model and one current workspace
  surface. A new subject or view replaces the previous surface; update in place only when
  the user is iterating on that same surface.
- Use the explicit trusted renderer map for registered native components. Reject unknown
  components or invalid props; never fall back to generated React, HTML, CSS, JavaScript,
  or arbitrary iframe privileges.
- Resource-backed panels retain an authorized URI and resolve through the API. Do not copy
  maintained course data into application code or workspace props.
- Browser interactions that matter to the next turn must become bounded semantic
  workspace interactions, not serialized DOM state.

## Visual direction

Match the existing sparse MIT Media Lab editorial character:

- black/near-black ground, ivory text, muted gray metadata, fine dividing rules;
- restrained monochrome surfaces with vivid color reserved for meaningful data marks;
- Helvetica/Arial system sans for editorial text and monospace only for operational trace;
- large but controlled type hierarchy, generous negative space, minimal persistent chrome;
- a full-height workspace canvas without an enclosing dashboard card;
- content-led composition rather than repeated hero blocks, card soup, or arbitrary
  two-column bands.

Use variables and semantic variants from `packages/ui/src/styles.css`. Application CSS
may own page composition and app-shell behavior; reusable component styling belongs in
`packages/ui`. Do not introduce literal colors, a new font, shadows, gradients, pills,
radii, or spacing values as a new visual system. Reuse a token or add a genuinely reusable
token at the design-system source.

## Interaction and verification

- Preserve semantic HTML, accessible names, focus visibility, keyboard operation, and
  textarea behavior.
- Preserve reduced-motion handling and do not make animation necessary to understand or
  operate the interface.
- Check workspace-open and conversation-only layouts at desktop and narrow widths.
- Add interaction tests for observable behavior and regression tests for stream/event
  reconciliation. Do not rely only on snapshots.
- Run the relevant web test file and `pnpm typecheck`; run broader checks before submission
  when feasible.

Keep `App.tsx` an orchestrator. When a change introduces a coherent state machine, parser,
policy, or reusable view, place it in a focused module instead of adding another unrelated
branch to `App.tsx`.
