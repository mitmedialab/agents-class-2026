# Registered workspace protocol

Phase 7 adds a trusted first-party workspace beside the conversation. The agent can
select and control registered components, but it cannot generate JavaScript, React,
HTML, or host UI.

## Stable contracts

The language-neutral authority is `shared/schemas/v1/workspace.schema.json`. Treat
these definitions as stable:

- `ComponentManifest`
- `WorkspaceState`
- `WorkspacePanel`
- `WorkspaceCommand`
- `DocumentHighlightAnchor`

`packages/workspace` contains readable TypeScript bindings and the browser reducer.
`course_server.workspace` contains matching Pydantic bindings and server validator.
`shared/registry/components.json` is the trusted built-in manifest catalog. Contract
tests compare these representations and reject unknown fields.

## Command lifecycle

```text
authorized workspace tool
        ↓
server command validation
        ↓
canonical workspace.panel.* event
        ↓ SSE / conversation history
browser command validation
        ↓
trusted native component map
```

`workspace.list_components`, `workspace.open_component`,
`workspace.update_component`, `workspace.focus_component`, and
`workspace.close_component` use MCP-compatible names, descriptions, JSON input
schemas, and JSON results. They are application wrappers around the canonical MCP
concepts, not a competing tool protocol. The standalone MCP transport/gateway remains
separate from this stable contract.

When workspace tools are authorized, runtime policy treats registered components as
the preferred presentation surface. The agent should display schedules, documents,
and other suitable structured results in a component rather than paste their complete
contents into chat, while still giving a concise direct answer. This preference never
bypasses component, prop, operation, or resource authorization validation, and it does
not permit generated JavaScript or arbitrary UI.

On desktop, the right column is the workspace canvas itself rather than a framed panel
inside the column. A single open panel receives the full available height and omits tab
chrome; its close action floats unobtrusively over the canvas. The tab strip appears
only when two or more panels need navigation. Component content remains independently
scrollable, so profile descriptions and other material below the initial viewport are
not clipped. Mobile uses the same active-panel model below the conversation area.

The server reconstructs workspace state from all prior panel events before a run.
Commands reject unknown components, invalid props, unsupported operations, duplicate
panels, missing panels, and unauthorized resource URIs. The browser validates again
before changing UI state. User focus/close actions return to the server for the same
validation and durable event append.
Calendar selection/view changes and document page/find actions emit validated
`workspace.interaction` events, which are available to the next agent turn without
storing DOM details.

## Resource separation

A panel stores a `resource_uri`; it does not permanently embed syllabus or schedule
data in props. The browser resolves public content through the authorized resource
content endpoint and supplies it to the trusted renderer:

```text
course://schedule → Calendar
course://syllabus → DocumentViewer
```

The endpoint accepts only a registered URI already visible to the principal. It never
accepts or returns a backing server path.

Tool results expose their authorized resource URI to the runtime as trusted follow-up
metadata so the model can pass it to a component without presenting it to the user.
For resilience, the calendar tool and browser host both resolve an omitted calendar
resource to `course://schedule` only when that resource is authorized. The browser
fallback also repairs incomplete calendar events already stored in development
conversations; it does not weaken the resource-content endpoint's authorization.

## Built-in components

`document-viewer` accepts `page`, `find_text`, and a semantic `highlight`. Highlights
contain a resource URI, one-based page number, exact quote, and optional prefix/suffix
for disambiguation. Markdown is rendered as React text nodes rather than injected HTML.
PDF.js renders PDF bytes locally and exposes searchable page text.

`calendar` accepts `view` (`month` or `agenda`), `focus_date`, and
`selected_event_id`. It consumes normalized event JSON. The Phase 6 weekly schedule is
adapted for display; missing dates remain explicitly unconfirmed.

`webpage-viewer` accepts a required HTTPS `url`, plus `mode` and optional readable
`content`. Reader mode is the safe default: the agent first uses `web.visit`, then the
component renders the returned Markdown as text nodes without an iframe or injected
HTML. This works when sites such as Google or the Media Lab prohibit embedding.

Live mode uses a sandboxed iframe only when explicitly requested. It permits scripts,
forms, modals, and popups for ordinary page compatibility, but deliberately omits
`allow-same-origin`, top navigation, downloads, storage, and host privileges. It sends
no referrer and warns that the remote site's CSP or `X-Frame-Options` may still refuse
the frame. A legacy URL-only panel renders a clean external-link fallback instead of
attempting a predictably broken iframe.

The trusted host can focus the entire webpage panel, but it cannot inspect, focus, or
mark arbitrary elements inside a cross-origin iframe. Same-origin browser security
intentionally prevents that access. Element-level page highlighting will use the
browser extension's semantic DOM tools in Phase 14, or an explicit cooperative-page
`postMessage` protocol; the host does not weaken the iframe sandbox to simulate it.

`browser-viewer` is the preferred visual surface when a public site blocks embedding.
It displays an authenticated screenshot from an isolated server-side browser session,
so Google, the Media Lab, and similarly configured sites do not need to consent to being
framed. Its session ID is issued by platform code and scoped to one principal and
conversation. The agent can navigate, scroll, and highlight visible text through the
read-only `browser.*` tools; the user can scroll with native controls. See
[`BROWSER.md`](BROWSER.md) for lifecycle, capacity, privacy, and network safeguards.

`draft-document` is a general evolving-document surface, not an application-specific
form. It renders safe Markdown prose, up to 50 structured fields, or both, without HTML
injection. It can hold proposals, reports, notes, letters, outlines, plans, forms, and
applications. Fields may be marked `missing`, `candidate`, `inferred`, or `confirmed`.
The runtime receives current trusted workspace state and instructs the agent to update
the existing panel rather than open duplicates. Updates are canonical workspace events
and survive conversation reloads. A rendered draft never counts as submission,
publication, or approval.

`visual-composition` is the trusted composable surface for results that do not belong
in one specialized viewer. It uses a flat object graph: every element has a stable ID,
and `group` elements reference their children by ID. Groups provide semantic stack,
row, and grid layouts plus bounded spacing, alignment, surface, padding, radius, and
width variants. Leaf elements are `image`, `heading`, `text`, `badge`, `link`, `facts`,
`input`, `textarea`, `divider`, and `spacer`.

This can represent instructor/student profiles, directories, image-and-text summaries,
lightweight forms, and other composed visuals without turning model output into code.
The registry rejects unknown properties and variants. Both Python and TypeScript hosts
also require one unique root, unique element IDs, valid references, a single parent per
element, no cycles, and no unreachable objects. The renderer accepts no HTML, CSS,
Tailwind classes, JavaScript, event handlers, or arbitrary style values. Remote images
must use HTTPS and are loaded without a referrer. Editable inputs remain local while
typing and emit a bounded `visual.change` workspace interaction on blur; they do not
submit or cause external effects.

## Phase boundary and deviations

There are no architecture deviations in Phase 7. Workspace tools are currently
executed through the existing application-owned tool adapter, as prior phases require;
their MCP-compatible contracts can be published by the capability gateway without
changing persisted events or UI state. MCP Apps, arbitrary external interfaces, and
workspace database snapshots are intentionally deferred. Canonical events already
provide sufficient persistence for the current class scale.
