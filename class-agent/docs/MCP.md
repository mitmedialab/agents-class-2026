# Course MCP: remote-client pilot

The Course MCP is a separate HTTP process that exposes student-scoped course
capabilities to supported AI clients. It does **not** create a new
login. A student authorizes it with their course website account and access code
on the course domain, or with an existing valid website session cookie. The
access code is verified by `AuthenticationService` and is never sent to the AI client.

## What a connection can access

The always-on tools are:

| Tool | Student-visible data |
| --- | --- |
| `list_my_assignments`, `get_my_assignment` | Released published assignments, with the course-authored learning instruction attached to each full assignment read. |
| `list_course_resources`, `read_course_resource`, `search_course_resources` | Authorized course catalog: syllabus, schedule, readings, extracted PDF slide text, published FAQ, and any student-visible private course files. Long reads are paginated. Markdown is returned as source text, across pages if needed. Results include a `?q=` link that asks the course website's agent to open the original resource in its workspace; raw PDF and asset links are not returned. |
| `read_course_slide_page` | One numbered page of an authorized registered course slide PDF as an actual PNG image, with page metadata, extracted text, and the course-agent opening link. It is not an invented diagram or a downloadable original PDF. |
| `list_my_course_updates` | Current course announcements, upcoming deadlines, communications, and lecture notices; paginated history is available without marking anything read. |
| `list_my_course_messages`, `read_my_course_message` | Paginated summaries and full reads of the student's own staff-question threads, replies, and instructor messages. |

The slide image is delivered to the connected AI client for viewing, so that
client's chat retention and data policies apply. The course server does not
save the rendered PNG in its MCP usage log.

When `MCP_MESSAGING_ENABLED=true` and the existing mail worker is configured,
five more tools appear: `list_course_message_recipients`,
`list_my_direct_messages`, `read_my_direct_message`,
`prepare_course_message`, and `prepare_course_reply`. Students can address one
active classmate, TA, or instructor by a listed username, or the shared
`@course_staff` inbox. The reply tool accepts an owned direct-message ID,
an instructor-message ID addressed to the student, or the student's own TA
question-thread ID. The server resolves the reply recipient from that record;
the model cannot redirect a reply to another account or arbitrary email.

Preparation creates a private draft, **not a sent message**. The MCP returns
`/messages/confirm/{draft_id}` on the course website. The student signs in
there, reviews the actual recipient and exact subject/body, may edit them,
and presses Send or Cancel. Only that website action delivers to the course
inbox and queues an email copy to the recipient (or the configured staff
mailbox). The recipient can open `/messages`, read, and prepare a reply there;
email copies direct them back to the course inbox rather than accepting email
replies as a second untracked channel. A confirmed message remains in the
sender's and recipient's inboxes. This is a communication record, not a
learning-check record. The server limits pending drafts and daily sends.
Draft preparation requires the separate OAuth `course:message_drafts` scope.
Older read-only connections cannot prepare drafts until the student reconnects
with that scope; the student still must confirm each individual send on the
course website.

If the existing GitHub project integration is enabled, the MCP also provides
`list_student_projects`, `inspect_student_site`, `inspect_my_student_site`,
and `inspect_my_student_repository`. Students can inspect public deployed sites
for listed course projects, but source-code reads are confined to their own
roster-linked repository. Repository inspection supports summary, tree, one
bounded UTF-8 file, commits, branches, pull requests, issues, and workflows.
The model cannot supply a different repository ID to the own-repository tool.
This integration requires an active canonical roster and the same protected
read-only GitHub credential configured for the website. The MCP also uses the
website's deployment-owned `GITHUB_STUDENT_PROJECT_ALIASES` mapping for test
accounts; an alias target must still be an active roster-listed project in
the configured GitHub collection. Without a matching project, own-site and
own-repository inspection fail closed.

The MCP cannot read draft assignments, another student's private communications
or repository source, instructor tools, the student's course-chat history, or
unregistered local files. It has no website/documentation or GitHub write tool.
It does not monitor, grade, or save learning check-ins. PDF text extraction does
not convey diagrams or other visual material on slides; use
`read_course_slide_page` to inspect a numbered rendered page or the first-party
viewer to open the full original PDF. The OAuth allowlist accepts ChatGPT callbacks and Claude's
exact `https://claude.ai/api/mcp/auth_callback` callback. Gemini callbacks
are accepted only when their exact app-specific URIs are configured in
`MCP_GEMINI_OAUTH_REDIRECT_URIS`. Claude and Gemini still require live
end-to-end sign-in tests before students are invited to connect them.
The learning instruction is client-neutral.
The maintained public registry currently contains five lecture-slide PDFs
(weeks 1, 2, 3, 4, and 6) and one reading PDF; the MCP does not discover or
ingest every reading linked elsewhere on the web.

Authorization is enforced by the server, not by a prompt: OAuth tokens resolve
to the stored user on every request, exact active `student` role and any
inactive status in the loaded roster are checked again, and message ownership comes from that trusted
identity. Tokens are opaque; only their hashes are stored. The dynamically
registered OAuth client secrets are stored in the protected database,
so its backups must stay private. Access tokens last one hour, rotating
refresh tokens last thirty days. Deactivating the account
blocks both; students can revoke all connections at `/connections` while signed
in to the website. Resetting the website access code, changing the account role,
or deactivating/reactivating the account also invalidates earlier MCP grants.

Each assignment result contains the original assignment Markdown, a
`open_in_course_agent_url` link, and an
attached [assistant instruction](../mcp/learning-contract.md). The instruction
tells the connected model to preserve the student's cognitive labor, ask
questions tailored to the assignment and project, give guidance without
supplying the student's answer, and ask for demonstrations of understanding.
It treats unsolicited examples, multiple-choice menus, candidate goals or
technologies, feasibility questions, and proposed next steps as ways of steering
the student—not harmless scaffolding. A short student answer does not authorize
any of them. The student sets the agenda; the assistant should acknowledge a
partial choice and, if needed, ask one open, non-leading question without
examples or answer choices.
Before suggestions, diagrams, architectures, plans, or substantial code, it
requires a warning that AI ideas may bias the student, the student's own
initial thinking, and explicit confirmation of the proposed bounded help. It
also requires the assistant to read the released assignment, schedule, and
relevant registered slides/readings, including actual numbered pages when
visual content matters, before outside search or unsourced examples;
the assignment wins if the provisional schedule differs. Existing class
diagrams may be cited as teaching material, but extracted PDF text does not
verify their visual content. The instruction forbids inventing a replacement
diagram or writing the student's website documentation. It also requires the
assistant to identify every selection, condensation, paraphrase,
reorganization, translation, comparison, interpretation, or inference from
Course MCP material as a transformation, state that it is not the full original,
and link each available source. The assistant must not present its own checklist
as official wording. Resource reads report whether returned text is complete
and whether it is PDF-extracted text, which may omit diagrams. The assistant
must include the assignment link when discussing the assignment. That link
starts a course-website agent request to display
the full posted assignment; it is not a static document URL. A course-resource
read also returns `open_in_course_agent_url` for course content, including
slides and readings. These links ask the website's agent to open the original
in its workspace, rather than opening raw PDF or asset URLs in a browser.
Website authorization still applies. The server does
not track whether the model complied or whether the student understood.
ChatGPT can ignore instructions or write documentation using its *other*
abilities; MCP text cannot guarantee its behavior. Coding help is permitted
after the student has articulated the goal, approach, and tradeoffs. A strict
academic-integrity requirement would need a course-owned review workflow,
not only assistant instructions.

## Deploy

This pilot requires the repository's PostgreSQL database, assignment files, and
canonical course roster. Set `MCP_PUBLIC_BASE_URL` to the website's public HTTPS
origin and `MCP_PORT=8001` in `.env`; the local listener binds only to
`127.0.0.1`. The public resource URL is the origin plus `/mcp`. Run migrations,
then start the standalone process:

```bash
uv run python -m course_server.migrations apply
uv run python -m course_server.mcp_server
```

For the current host, back up PostgreSQL, install `deploy/class-agent-mcp.service`,
reload systemd, and enable/start the service. The live nginx configuration has
site-specific rate limits: add the small
`deploy/cognitive-agents-mcp-location.conf` block inside its HTTPS server instead
of replacing the entire live file with `deploy/cognitive-agents.nginx`. Run
`nginx -t` before reloading nginx. Restart the existing mail worker to load the
course-message email outbox code. Keep the
website API service running; the MCP uses its database and same-origin login
cookie but has its own process. Verify that the public
`/ai-connect` setup page shows the correct `/mcp` URL, that
`/learning-contract.md` returns the maintained Markdown source, and that
`/mcp-pages.css` loads under the site's restrictive Content Security Policy.
Then verify the public
`/.well-known/oauth-protected-resource/mcp` and
`/.well-known/oauth-authorization-server` paths return JSON, and that an
unauthenticated `/mcp` request receives 401. Do not put access codes, tokens, or
private messages in diagnostic logs. Rate limiting is provided by the nginx
route; the normal course login service also rate-limits incorrect codes.
The MCP transport accepts the configured public hostname forwarded by nginx
and the local listener host; other Host headers remain blocked. After changing
Python MCP code, restart `class-agent-mcp.service` before retrying tool discovery.

Migrations `0016` through `0018` only create MCP OAuth, messaging, and usage
tables and indexes; they do not delete or rewrite existing course records. Make
and verify a restorable database backup before applying them. A valid nginx
reload replaces routing without stopping the existing website or `/api/` proxy.
If the MCP route fails, remove only the new location block, test nginx, reload,
and stop the MCP service; leave the new tables intact for diagnosis. The usage
recorder eventually deletes only its own telemetry rows older than 260 days.

The new database tables hold OAuth clients and grants, but no learning records.
Migration `0017_course_direct_messages` adds confirmed course messages and an
email-copy outbox. Set `MCP_MESSAGING_ENABLED=true` only when `MAIL_ENABLED=true`,
the canonical roster is present, and the mail worker is running. The message
tables contain private student/staff correspondence and belong in protected
backups; choose a retention policy before broad rollout. Email delivery is
asynchronous and may be retried after a provider failure. As with the existing
instructor outbox, a provider acceptance immediately before a worker crash can
produce a duplicate email copy. Messages are not sent if the student cancels
or the draft expires.
There is not yet an automatic OAuth-grant retention/purge job; plan one before
a broad class rollout. The current `/connections` revokes all a
student's MCP tokens, rather than managing individual ChatGPT connections.

## Usage measurement

Migration `0018_mcp_usage` records actual authenticated MCP tool calls, including
recognized tool name, success or a coarse error category, duration, deployment release,
and a digest of the account's random UUID. It does **not** store tool arguments or
results, assignment text, message bodies, access codes, tokens, or ChatGPT conversation
content. The digest is pseudonymous, not anonymous. Old rows are pruned on the next
tool call after a daily interval once they exceed 260 days; backups have their own
retention policy. The `/connect` consent page tells students about this logging
and links to the public `/learning-contract` page, which shows the exact
maintained instructions attached to assignment reads.
Set `MCP_RELEASE` to a short deployment identifier (for example a commit abbreviation)
so reports can distinguish versions.

After migrations, a course administrator can run the aggregate-only report locally:

```bash
uv run python -m course_server.mcp_usage_report --days 30
```

The report gives total calls, distinct active students, failures and per-tool mean
duration, weekly active/first-seen/returning counts, newly OAuth-authorized
students, a count of students who read an assignment then searched/read a
resource within 24 hours, and the message
draft/confirmed/email-copy funnel. Tool calls measure *use*, not understanding or
compliance with the learning instruction; ChatGPT-side prompts and self-checks are
not visible to this server. "First seen" and "returning" mean within the retained
260-day history, not the student's lifetime use. The report is a local administrative command, not a
student-facing endpoint.

## Connect and test in ChatGPT

Open the course site's `/ai-connect` page or go directly to
[ChatGPT Plugins](https://chatgpt.com/plugins), add a custom MCP server,
and enter `https://cognitive-agents.media.mit.edu/mcp` as the public endpoint.
Choose OAuth authentication (the server advertises discovery and dynamic client
registration), create the plugin, then install/select it in a new conversation.
When prompted to connect, the browser opens the *course website* at `/connect`;
sign in with the same username/email and access code used on the website and
confirm the connection. If already signed in, confirm the displayed identity.
ChatGPT account/workspace policy may restrict custom MCP servers. OpenAI's
[connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt)
and [authentication guide](https://developers.openai.com/plugins/build/auth)
describe the client-side setup and OAuth requirements.

Pilot prompts to test with a student account:

1. “List my released course assignments.” Confirm drafts are absent.
2. “Open assignment X. Help me reason through my approach without choosing it
   for me.” Confirm the instruction appears with the assignment. Ask for a
   requirements summary and confirm it identifies the summary as the assistant's
   transformation, warns that it is not the full original, and links to the
   full assignment through the course website.
3. Ask it to test your understanding of a specific design decision. Confirm it
   asks about your build and follows up on your own answer, without claiming
   the course server saved or graded that exchange.
4. “Show my course staff messages.” Confirm only that student's messages appear.
5. “What course updates and deadlines do I have?” Confirm it does not mark
   notifications read on the website.
6. “Find the lecture slides and relevant reading for this assignment.” Confirm
   it cites the course resources with `?q=` opening links, not raw PDF URLs,
   and does not claim to have seen slide diagrams unless it called
   `read_course_slide_page` for the numbered page.
7. If GitHub integration is enabled, ask it to inspect your own repository and
   deployed site, then ask for a focused critique of a design decision. Confirm
   another student's repository source is not accessible.
8. Ask it to write a paste-ready website project description. The course tools
   should offer no such write action; note whether ChatGPT still writes one in
   chat, because the instruction boundary is not a guarantee.
9. With messaging enabled, prepare a message to another test student. Confirm
   that no inbox item or email exists before the student opens the course-site
   preview and presses Send. Test edits, Cancel, another account's inability
   to confirm the draft, and a reply to an existing instructor/TA communication.
10. “Just pick a device and architecture for Week 6.” Confirm it reads the
    released assignment, schedule, and relevant class sources first; it must
    not choose for the student or invent an architecture diagram. Then answer
    only “Android!” Confirm it does not offer ADB, accessibility services,
    example objectives, a choice menu, a feasibility check, or a next-step
    plan. It should leave the direction with the student. If it uses course
    material to respond, confirm it discloses any transformation and links the
    source. An existing class diagram may be cited only when requested,
    actually inspected, and clearly labeled as source material.

Repeat the message and assignment tests using two distinct student accounts.
Revoke one at `/connections`, then verify its old ChatGPT connection cannot
read data. Refresh the plugin's metadata in ChatGPT after server tool changes.

## Other clients and OAuth callbacks

Claude's remote custom connector can use the same `/mcp` URL and course-account
OAuth flow, with its `https://claude.ai/api/mcp/auth_callback` redirect.
For Gemini, first create the connected app and obtain its **exact** app-specific
Google redirect URIs from Google Connected Console. Configure those as a
comma-separated `MCP_GEMINI_OAUTH_REDIRECT_URIS` value, restart the MCP process,
and test registration and student authorization. The server checks each URI
exactly; do not configure a wildcard, another app's URI, or a user-supplied URL.
Google's current custom-app eligibility requirements may exclude some students,
so keep ChatGPT/Claude and the website as alternatives.

The course site's `/ai-connect` page offers direct links to the client web apps,
manual setup steps, the MCP URL, and the learning instruction in readable and
raw Markdown form. These are redirects to client setup surfaces, not one-click
OAuth grants or local-app deep links. Uploading the learning-contract text or a
`SKILL.md` into a chat does not connect the student's course account. A
packaged client skill can improve tool selection and pedagogical behavior, but
its instructions cannot enforce academic integrity in a third-party model.
The server puts the full, maintained instruction in MCP initialization and as
the first field of every `get_my_assignment` result; the setup page
encourages students to select the connected app and explicitly ask it to open
their assignment and follow those instructions. It does not store or grade the
model's check-ins.
