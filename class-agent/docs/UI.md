# Web interface through Phase 7

The web client is a static React/Vite application in `apps/web`. Its default
screen is intentionally sparse:

- MIT and MIT Media Lab marks at the left of the fixed header, with About at the right;
- a welcome message or latest agent response centered in the workspace;
- `Course Agent` and its expandable current/last action immediately above the response;
- borderless user text at the bottom while composing.

An empty or new conversation explains that the Course Agent is itself the class
website and invites visitors to ask for course information or discuss applying.
The header's Apply shortcut opens the canonical application workspace directly before
sending its prompt. Application requests typed in chat are not matched against browser or
API keywords; the agent recognizes the intent and opens the same canonical workspace with
its registered tool during the first response.

Submitting a new prompt immediately removes the prior answer and resets the
activity trace, so only the new run's process is visible until its answer begins.
Canonical history is still persisted as events and is available through the conversation drawer.
Open the About drawer from the right side of the header. It contains a concise
description, new/history navigation, and student login or logout without adding
persistent chrome to the main interface.

Response typography is continuously length-aware. Short answers retain the large
display treatment; as character and line counts grow, type size, line height, measure,
spacing, and padding interpolate toward a bounded reading layout. Responses are capped
at the smaller of 44 percent of the viewport or 30rem. The renderer safely handles
basic headings, lists, numbered lists, and bold text without injecting model-provided
HTML.

The borderless composer sits roughly 15 percent of the viewport above the bottom edge
on larger screens and uses the native system text face for a quieter writing surface.
While empty, muted placeholder text invites the visitor to start typing to interact
with the agent. An attachment control uploads supported files before sending; removable
filename chips show which principal-scoped temporary upload receipts will accompany the
next message.

Final-answer text originates incrementally from native model-provider deltas and is
projected as soon as each fragment arrives. A small block cursor marks the active edge,
and newly arrived characters use a short opacity fade while stable characters retain
their keyed DOM nodes. Length-aware typography transitions as the answer grows. The
canonical `agent.text.done` value reconciles the displayed answer; reduced-motion
preferences disable character and cursor animations.

Run activity appears immediately above the response, after the white
`Course Agent` label, as a muted icon-led monospace disclosure. Its expanded
view lists verified status, model/runtime identity, user-facing resource and tool
activity, and completion. Internal identifiers are mapped to ordinary labels; private
application arguments and tool results are not shown. The disclosure is closed by
default and, after a turn, retains the actual final action label such as `Agent run
complete` rather than substituting a generic process label. It is deliberately styled
as a process trace rather than an agent message. The trace does not claim to show or
expose hidden chain-of-thought; it shows inspectable platform operations that actually
occurred. Expanding the trace does not alter the horizontal center of its summary; the
independently centered list fades into reserved space while the response stage
transitions upward.

Non-final model prose is not shown in chat. While a run is active, the interface
shows only verified platform activity; decoded final-answer fragments replace
the prior answer when the model reaches its final response. Future workspace
tools, including a PDF viewer, can add their verified operations to the same
trace; the PDF UI tool is not yet implemented.

Press Enter to send and Shift+Enter for a newline. The composer is an ordinary
accessible textarea despite having no visible input box. Typing a printable key
while the page itself is focused moves focus into the composer.

## Data flow

The client establishes an anonymous or authenticated principal with
`GET /api/v1/auth/me`, then loads only conversations owned by that principal.
Runs use the POST SSE route and reduce typed events into the latest text and current
process trace. The status begins with context preparation and then uses live portable
runtime events to report planning and sanitized user-facing activity. Native
final-answer deltas update the response independently of those process events. This is
inspectable platform activity and user-visible output, not hidden model
chain-of-thought.
Cookies are opaque and sent with `credentials: include`; identity never comes
from client-provided user IDs.

## Development and build

Start FastAPI, then run:

```bash
pnpm dev
```

Build ordinary static assets with:

```bash
pnpm build
```

The production API base defaults to `/api/v1`. A separate deployment may set
`VITE_API_BASE_URL` at build time. CSS variables are owned by `packages/ui`, and
the application layout remains in `apps/web/src/styles.css`.

Phase 7 fills the workspace shell with registered native components. A validated
workspace event changes the desktop layout to conversation plus workspace; smaller
screens stack the active workspace below the current response. MCP Apps remain Phase 8.
Closed draft fields render as native selects using options supplied by validated
component props. Drafts can also request semantic text, email, URL, year, multiline, or
attachment-receipt presentations. Validation guidance appears beside the affected field,
and a rejected transport save retains the applicant's typed value for retry. Application
picture receipts remain internal; the field directs applicants to the existing message
attachment control.
The desktop workspace is a full-height right-side canvas without an enclosing card.
It has one current surface. Opening or focusing a different subject, artifact, or view
replaces the prior panel immediately, so stale workspaces never compete for attention.

The native component set includes DocumentViewer, Calendar, VisualComposition, the
isolated BrowserViewer, PageCards, WebpageViewer, and DraftDocument. PageCards presents two to six website
candidates as compact adjacent columns. Platform-generated captures fill each column,
each preview scrolls independently under the pointer, and selecting a card emits a
`workspace.interaction` event. The agent uses `browser.compare` to populate real previews;
generic `workspace.open_component` calls may also create metadata-only cards that retain
safe external links.

VisualComposition provides the lower-level vocabulary beneath specialized viewers. It
combines registered groups, images, headings, text, badges, links, facts, charts, inputs,
textareas, dividers, and spacers using semantic design-token variants. A profile page,
for example, is a grid group containing raised profile groups, each composed from a
rounded image, heading, badge, facts, biography, and link. The agent cannot supply CSS
classes or arbitrary style declarations.

DocumentViewer opens a specific Markdown, text, or PDF artifact for close reading and
focused discussion. It is not the default for knowledge extracted from documents: the
agent synthesizes that knowledge into a VisualComposition. Calendar provides agenda and
month views over a normalized resource without embedding schedule data in component
code. Panel focus and close use semantic operations rather than arbitrary DOM or
JavaScript.

VisualComposition treats its workspace as the detailed answer, so chat provides only a
short handoff instead of repeating the same facts. Fractional media widths do not shrink
inside feature rows; a primary image receives roughly one-third to one-half of the row,
while narrow layouts stack media and copy. Compositions use short text blocks and visual
units rather than full-width paragraph stacks: surfaced stages for methods, optional
side-by-side treatment for direct comparisons, ordered sections for timelines, and facts
for measures. Stack, row, and grid are equal options; columns are not the default, and a
composition should not repeat multiple two-column bands without a real parallel relationship.
Image search is
automatic for subjects with meaningful visual identity—such as people, physical projects,
places, interfaces, and devices—but remains off for merely decorative uses.
The workspace tool enforces that distinction for concrete subjects: it requires an image
search before opening the composition and requires an image when usable candidates were
returned. A completed search with no usable candidate permits a schematic-only fallback.

Images expose semantic presentation modes rather than arbitrary styling: `banner` for a
wide top-of-page visual or paper figure, `feature` for an editorial split, `card` for a
gallery or repeated examples, and `avatar` for compact profiles. The agent selects among
banner-led editorial, split-feature, gallery, profile, process, timeline, and comparison
patterns instead of repeating one oversized hero layout. Diagram and screenshot imagery
uses contain-fit to preserve labels; photographic treatments may crop with cover-fit.
Image search results state whether intrinsic dimensions are known and, when available,
include width, height, aspect ratio, orientation, resolution tier, and a layout hint. The
agent copies known dimensions into `source_width` and `source_height` on the image element.
The workspace rejects small or unknown-dimension searched images when used as banners or
feature media, preventing tiny sources from being stretched into primary visuals. Results
also identify whether a split layout is safe. Contained images at least 2:1 wide must use a
full-width banner or standard figure in a stack, avoiding empty space caused by pairing a
shallow figure with a much taller text card.

Charts are declarative visual elements rather than executable plotting code. They support
bar charts for categorical comparisons, line charts for ordered change, and area charts
for magnitude or accumulation, with up to sixteen labels and four series. Chart data must
come from a trusted source. Each new chart declares its data kind, exact source, shared
unit, and why all plotted values are comparable on the same quantitative scale. The tool
boundary rejects qualitative rank encodings, directional placeholder values, and explicitly
non-comparable measures. The agent uses another visual structure when defensible numeric
data is unavailable. Every chart includes accessible SVG labels, visible provenance, and a
screen-reader data table.
Visually, charts inherit the same restrained monochrome palette, editorial hierarchy,
metadata typography, spacing, and rule-based section structure as the rest of the
workspace. They are normally full-width sections rather than nested analytics cards.
Data marks use a vivid, high-contrast accent set—coral, sky, mint, amber, violet, and ivory. A tone
can apply to a complete series, while categorical bars may provide one tone per value.
Small single-series bar comparisons receive contrasting accents automatically; larger
datasets remain visually restrained rather than becoming a rainbow.

Each new question or analytical angle opens a fresh composition and replaces the prior
one. The current composition is updated in place only when the user explicitly iterates
on that UI. Thus a project overview and a later methods question receive different,
purpose-built visual structures rather than one accumulating page of generic cards.
