# Web interface

The web client is a static React/Vite application in `apps/web`. Its default
screen is intentionally sparse:

- MIT and MIT Media Lab marks at the left of the fixed header, with About at the right;
- a welcome message or latest agent response centered in the workspace;
- `Course Agent` and its expandable current/last action immediately above the response;
- borderless user text at the bottom while composing.

An empty or new conversation explains that the Course Agent is itself the class
website and invites visitors to ask for course information or discuss applying.

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

The agent may publish a concise intermediate note such as `I’ll read the
syllabus first.` before it uses a non-final tool. Provider fragments appear as
the temporary main response, with only a neutral `Shared intermediate update`
entry in the trace. The next intermediate or final response replaces this text.
This channel is explicitly user-facing, transient, and separate from both the
canonical final response and private reasoning. Future workspace tools,
including a PDF viewer, can add their verified operations to the same trace; the
PDF UI tool is not yet implemented.

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

The current interface remains a workspace shell with temporary attachments. Registered
dynamic components, document/calendar panels, workspace commands, and MCP Apps remain
in their later phases.
