# Isolated remote browser

The remote browser is a trusted first-party workspace capability for public websites
that reject iframe embedding. It supports direct user-driven clicking and navigation,
while agent-driven typing, login, uploads, downloads, and form submission remain absent.

```text
Course Agent → browser.* tool → BrowserSessionService
                                      ↓
                              Playwright / Chromium
                                      ↓
                   authenticated live viewport stream
                                      ↓
                            native browser-viewer
```

`BrowserSessionService` is the application-owned boundary. Playwright is an adapter,
not a platform contract, and can later be moved behind a worker or NodeRPC transport
without changing tool IDs, workspace events, or the frontend component.

## Supported controls

- `browser.open` creates an isolated context and opens `browser-viewer`.
- `browser.compare` captures two to four pages and opens `page-cards`, with one
  independently scrollable column per candidate.
- `browser.navigate` changes the public HTTPS page in the active browser panel.
- `browser.scroll` scrolls the active panel and refreshes the view.
- `browser.highlight_text` finds visible text, scrolls it into view, and marks the
  first matching element using fixed platform code.
- The user can click the rendered page. The host maps the selected screenshot point to
  the isolated browser, refreshes the capture, and persists the resulting URL and title.
- The user can scroll with the mouse wheel over the image, the keyboard, or the native
  workspace toolbar.

The browser panel subscribes to a same-origin, authenticated SSE endpoint that carries Chromium
screencast JPEG frames. CSS, scripts and animations execute in the isolated browser, without
iframe sandbox-origin changes. One screencast serves at most two viewers per browser session;
each viewer retains only its latest pending frame. Acknowledgements throttle production near
20 fps. Closing the last viewer stops the screencast, and closing or expiring the browser session
releases it. Streams reconnect every minute to revalidate HTTP authentication and conversation
ownership. Frame bytes are ephemeral and never workspace events.

The viewer forwards wheel, touch scrolling and toolbar controls to the existing authorized scroll
endpoint. Clicks use the displayed frame's viewport dimensions and scroll offset. These controls
still persist canonical URL/title/panel updates, while frame arrival itself does not. The viewport
resizes to the panel. This is visual streaming, without audio, text selection, keyboard typing,
or new form/login capabilities. It retains the existing 16,000-pixel document click bound.

When streaming is unavailable, the panel explicitly labels its snapshot fallback. That fallback
uses a full-page PNG and local scrolling as before; comparison previews remain static.

Follow-up control tools do not accept a model-provided session ID. Platform code resolves
the focused browser panel from trusted workspace state. A redundant `browser.open` reuses
that panel and live session; after an API restart it replaces the stale session in place
instead of accumulating duplicate panels. Scroll, navigation, highlighting, clicking,
and direct user scrolling also recover a stale context in-place before applying the
requested action. Because a click updates the canonical workspace panel, the next agent
turn receives the page the user reached. Calling `browser.open` with the panel's current
URL snapshots that existing clicked session and returns its current readable text; it
does not create a duplicate panel or start the page over.

The model cannot execute arbitrary JavaScript, provide an identity, choose a screenshot
endpoint, or bypass component validation. Only the user can initiate a screenshot click;
agent-driven type, login, uploads, downloads, and form submission are deliberately absent.

Comparison previews are static and short-lived. Chromium closes immediately after each
capture; only the principal- and conversation-scoped PNG and safe page metadata remain
in memory. This makes side-by-side research practical without reserving a live browser
context for every card. At most 12 previews are retained per principal and 120 globally,
and normal session expiry clears them. A missing or expired capture degrades to the
candidate's external HTTPS link.

## Isolation and capacity

Every remote-browser session belongs to the trusted `PrincipalContext.session_id` and
one conversation. The stream, screenshot and scroll routes validate both before accessing the
session. Browser contexts do not share cookies, storage, cache state, or service workers.
Sessions are ephemeral and expire after 15 minutes by default.

The default capacity is 20 simultaneous contexts, limited to two per principal. This
supports ten people on separate computers with two panels each on a single class-sized
deployment. The practical limit still depends on page complexity and VM memory; tune:

```text
BROWSER_MAX_SESSIONS
BROWSER_MAX_SESSIONS_PER_PRINCIPAL
BROWSER_SESSION_TTL_SECONDS
```

The initial deployment uses one API process, a dedicated browser-controller event-loop
thread, and a separate Chromium subprocess. The controller boundary safely accepts both
HTTP calls and agent tools executed by the runtime worker thread. Do not run multiple
API replicas until browser sessions are moved
to a dedicated worker or requests are routed consistently. That constraint is suitable
for the approximately 20-person initial class and is explicit rather than hidden.

## Network and privacy policy

Only public HTTPS URLs on port 443 are permitted. Credential-bearing URLs, local names,
loopback, private, link-local, reserved, and other non-global IP destinations are
rejected. Redirect targets and browser subrequests are checked again. This is a useful
SSRF defense for the initial deployment; production egress firewall rules should provide
an additional boundary.

Frames, screenshots and detailed browser state remain in memory and are returned with
`Cache-Control: private, no-store`. They are not course resources and are not written to
ordinary logs or canonical event payloads. Workspace history stores the URL, title,
opaque session ID, dimensions, and revision. Page text is returned to the agent only as
part of the user-requested browser task and is subject to the tool's summary policy.
Page-card history similarly stores URLs, titles, descriptions, opaque preview IDs, and
revisions—not PNG bytes.

## Installation

Playwright is installed with the Python project. On macOS development, the adapter uses
an existing Google Chrome executable when present. Otherwise install the managed binary:

```bash
uv run playwright install chromium
```

Production can set `BROWSER_EXECUTABLE_PATH` explicitly. If Chromium cannot start, the
API remains available but omits all browser tools from the authorized catalog.
Chromium's process sandbox remains enabled; production hosts must support it rather than
adding a `--no-sandbox` workaround.

## Phase note

The constitution schedules generalized browser work after Phase 7. This narrow remote
viewer was pulled forward by explicit product direction after iframe experiments failed.
It does not implement the Phase 14 extension, arbitrary computer use, or agent-driven
browser actions.
The MCP-aligned tool boundary, registered component protocol, and application-owned
adapter preserve the intended later architecture.

## Deployment and compatibility

The stream route is `GET /api/v1/conversations/{conversation_id}/browser/{session_id}/stream`.
It uses existing session cookies and checks both conversation ownership and browser-session ownership.
Responses use `Cache-Control: private, no-store` and `X-Accel-Buffering: no`. The existing Nginx
`/api/` location already disables buffering and permits a 300-second response; no iframe CSP
exception or public Chromium debugging port is needed. Chromium and its sandbox must be available,
and the API needs restarting after this change. The existing single-controller deployment applies.

This is an additive, ephemeral HTTP transport. No versioned workspace props, schemas, core contracts,
or persisted records change; no migration is required. Snapshot endpoints remain compatible.
