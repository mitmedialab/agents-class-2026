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

Response typography uses the largest display scale that fits its rendered bounds without
scrolling. The browser measures actual content overflow and continuously adjusts type size, line
height, measure, spacing, and padding when text or the surrounding notification/workspace layout
changes. A length-based estimate prevents an oversized first paint before measurement; scrolling
remains only when the smallest reading scale still cannot fit. Responses are capped at the smaller
of 44 percent of the viewport or 30rem. The renderer safely handles basic headings, lists, numbered
lists, and bold text without injecting model-provided HTML.

The borderless composer sits roughly 15 percent of the viewport above the bottom edge
on larger screens and uses the native system text face for a quieter writing surface. It occupies
an auto-sized layout row: multiline drafts and attachment receipts grow that row while the response
row yields the same amount of space, so the two surfaces never overlap.
While empty, muted placeholder text invites the visitor to start typing to interact
with the agent. An attachment control uploads supported files before sending; removable
filename chips show which principal-scoped temporary upload receipts will accompany the
next message.

When an authenticated student asks something the maintained site and appropriate research cannot
answer, the agent may prepare a course-staff email. A platform-owned confirmation appears beneath
a model-authored response and shows the content-only question as borderless editable text in the
existing preview. The
runtime preserves the agent's final wording instead of substituting a platform-authored handoff.
Optional context needed by staff remains part of the prepared request but is not rendered as a
second explanation in the student interface. Internal tracking codes, subject lines, greetings,
sign-offs, and transport formatting stay out of the student interface. The composer pauses
until the student chooses **Send** or **Cancel**. The Course Agent is instructed not to repeat the
detailed question already visible in the confirmation. Send only queues the dedicated mail worker;
the UI closes the confirmation and asks the Course Agent to continue from the trusted action event.
The agent receives the completed action and exact submitted question and decides what to say next,
including whether to acknowledge the send or continue other unfinished work. The browser contains
no prewritten success response. The composer reopens when that continuation finishes.
The confirmation also offers **Hide my name from course staff**. This substitutes an anonymous
staff-facing label and redacts the account's known name and email from the question/context;
platform code retains the authenticated owner for private reply delivery. Staff FAQ review remains
in the original email thread.

An instructor-authored student message uses the same platform-owned confirmation pattern without
email transport. The confirmation shows editable subject and body fields plus the resolved,
read-only recipient snapshot in the existing preview layout; a response prepared from a pending
question uses a trusted server-side reply reference instead of making the agent guess the student.
Anonymous questions display an anonymous recipient label while retaining private delivery to the
stored owner. A pending-question reply presents **Private** and **Public** as a separate visibility
choice beside the editable answer; moderation commands are not part of the displayed or submitted
answer body. Only the answer content is shown back to the student. The composer pauses until Send
or Cancel. The browser cannot supply
identity, role, or additional
recipients. A confirmed message then appears only in each addressed student's Communications stack
and authorized Course Agent context. A confirmed question reply instead replaces that student's
pending question with the existing staff-reply presentation, avoiding a duplicate message card.

Authenticated course members automatically see a narrow macOS-inspired right-edge surface made
from separate, compact notification cards rather than a dashboard or model-generated workspace.
It has no header tab, modal backdrop, or enclosing panel. When no active items remain, it keeps only
a small **See more** history control without shifting the conversation layout or intercepting the
surface beneath it. The site's own monochrome tokens, type, and restrained motion remain
authoritative. Updates cards are first; Communications and Upcoming appear as stacked groups
when they have active items. Updates contains staff-approved FAQ knowledge and explicit
course-resource
release notes. Communications shows a student's queued/open staff questions and addressed
instructor messages, replacing a pending question item with the private answer when one arrives;
TAs and instructors instead see questions that still
need a staff reply. Upcoming contains authorized structured assignments only during the fourteen
days before their stored deadline and computes the countdown from the server projection time. Course
updates and replies can be marked read; pending threads and deadlines remain visible while active.
After a successful authenticated page welcome, the Updates visible for that opening are
acknowledged so they do not reappear on the next visit. The current browser snapshot remains visible
for that opening, while Communications and Upcoming continue to reflect their active state.
Read updates and messages, resolved question threads, staff replies, and past deadlines remain in
the authorized history projection. **See more** replaces the active projection with the newest three
items in each non-empty category, ordered newest first; each category can then expand to its full
retained history or return to the three-item preview.

Every item has a bounded details action that starts an ordinary Course Agent turn. That turn may
retrieve additional facts from an authorized source, but it must not solve the issue, draft a
response, recommend or take an action, or infer the user's intent. It ends by asking what the user
wants to do. Selecting a Communications item also presents that complete trusted card in the
conversation, without its stack truncation or repeated action control, with the Course Agent's
streamed response immediately underneath. The notification stack yields its presentation slot while
that communication is in the conversation so it cannot cover the full card at narrow widths or
duplicate it at desktop widths. A later ordinary message or different notification action clears
that transient presentation and restores the stack; durable communication data remains server-owned.
Ordinary cards are borderless and use a large, semantic color tile for their trusted type
icon beside the site's sans-serif text treatment. Staff replies and instructor messages show only
the trusted sender's first name in the muted metadata row. They use the sender's registered course
portrait in the tile when its asset resolves; otherwise the semantic message icon remains. Upcoming assignments use a distinct calendar-date
layout with the countdown and exact due time. Dismiss controls appear on pointer hover or keyboard
focus and remain visible on touch-only devices. Details actions follow the same hover/focus rule
and appear as compact, brighter button-shaped controls without directional arrows, with a persistent
touch fallback. Cards reserve the action's final height before reveal so hovering never resizes a
card or shifts the stack. Update timestamps use locale-aware relative time while the exact
date remains available as native time metadata. The stack scrolls over the fixed header and recedes
through an opacity mask into the page's black top edge instead of clipping against a hard boundary;
once scrolling begins, the header shortcuts from Apply onward fade completely out of its path.

Every authenticated page load starts one fresh conversation and invokes a dedicated Course Agent
greeting operation. The generated greeting receives the same trusted, role-filtered items as the
visible surface. Its wording, prioritization, and whether to suggest an action are entirely
agent-authored; the platform supplies trusted, semantically categorized content plus an approximate
70-word brevity guardrail, not response copy. With active items, the agent uses a compact Markdown
list to distinguish new changes from pending communications and assignments. When no new Updates
exist, it assumes the remaining items were already seen and presents them only as pending reminders
with useful next actions. The platform records
an `agent.greeting.requested` trigger and the generated response without inventing a `user.message`.
Anonymous visitors retain the static public welcome to avoid spending model quota on reloads. The
authenticated loading state does not reuse that public welcome, and a failed greeting request is
retried once against the idempotent greeting route.

At desktop widths, opening the notification stack transitions both the agent response and composer
into the horizontal space that remains to its left, centered within that region in the same manner
as the workspace transition. At widths of 900 pixels or less, the notification stack is hidden by
default and an explicit **Chat / Updates** switch presents only one opaque surface at a time. Chat is
the default whenever the page opens, a prompt starts, or a notification action begins. This switch
controls browser presentation only and does not create or persist workspace state. When a registered
workspace opens at the same narrow widths, the control becomes **Chat / Workspace**, selects
Workspace automatically, and gives that surface the full available content height above the shared
composer. Switching to Chat keeps the validated workspace mounted but hidden until the user returns.
Reduced-motion preferences disable the desktop transition.
The notification center and registered workspace share one mutually exclusive right-side
presentation slot. Opening a workspace temporarily hides the center without acknowledging or
discarding its items; closing the workspace restores the same notification projection.
While an authenticated page remains open, the browser checks for notification updates once per
minute. Polls add new items and refresh matching items without removing the page's current snapshot;
a full page refresh starts a new authoritative snapshot and drops items that are no longer active.
While the stack is at its initial position, visible header shortcuts remain in the top interaction
layer and are clickable through the stack's transparent header area. As cards scroll over that area,
the shortcuts fade out and stop receiving pointer events.

This non-duplication rule applies to every trusted platform presentation, not only email
confirmations. When a tool opens or updates UI, that UI is the primary carrier of its visible
content. The rule is part of the Course Agent's core instructions and the runtime repeats a
contextual reminder with UI-presenting tool results. Chat should therefore add only complementary
context, a brief handoff, or the next question. Application code does not inspect or rewrite the
agent's response text.

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
the prior answer when the model reaches its final response. Workspace tools add
their verified operations to the same trace; DocumentViewer supports registered
PDF resources with page navigation and document search.

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
Authorized assignment reads open the exact stored Markdown assignment in the workspace. No
assignment editor is registered.
The read-only surface presents the assignment title once, omitting only an equivalent leading
Markdown H1 from the rendered body. It shows no internal document-status label. The complete
**Due** line uses the assignment-deadline color for the authored local date and time without exposing
the raw UTC-offset suffix. The stored assignment and the complete content returned to the Course
Agent remain unchanged. The read-only document owns vertical scrolling so the full brief remains
reachable at desktop and narrow workspace sizes.
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
focused discussion. PDF pages preserve their aspect ratio and fit inside the usable workspace
area; the viewer rerenders them offscreen when the desktop pane or narrow Workspace surface changes
size, then swaps in the completed frame so composer and layout changes do not flash a blank page.
While its resource request is pending, the workspace centers the opening label and a thin
monochrome loading bar in the available viewer pane. The bar reports downloaded bytes against the
response content length when available and remains indeterminate when the server omits that length.
It is not the default for knowledge extracted from documents: the agent synthesizes that knowledge
into a VisualComposition. Calendar provides agenda and
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
