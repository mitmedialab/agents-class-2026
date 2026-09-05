# Course Agent runtime

There is one logical agent definition: `course-agent`. Each run combines that definition with a trusted `PrincipalContext`, portable conversation events, and already-authorized tool, resource, and skill metadata.

## Runtime boundary

`agent_core.AgentRuntime` remains the platform boundary. `runtime_smolagents.SmolagentsRuntime` is one adapter and is the only production package that constructs `smolagents.ToolCallingAgent`. It creates a fresh transient framework agent for a run, reconstructs recent conversation context from canonical events, and returns only `AgentResult` and `Event` contracts. Context selection keeps the 24 most recent user/agent messages and 16 useful tool-completion or workspace-interaction events. Run lifecycle and tool-request bookkeeping do not consume that budget.

The adapter reconstructs those portable user and assistant events as correctly role-scoped, ephemeral smolagents memory before each run. Dialogue is never flattened into the system instructions, and the transient memory is discarded afterward. This preserves conversational follow-ups—especially confirmations, corrections, requests to continue, and attachments—without making framework state canonical.

No smolagents agent, memory, model, `RunResult`, or pickle is canonical persistent state. `CodeAgent` is not used.

`agent_core.ModelProvider` is a small generic factory boundary. The v1 `OpenAIModelProvider` returns a transient smolagents `OpenAIModel`; another provider or runtime can replace it without migrating event history.

smolagents 1.x sends `ToolCallingAgent` function tools through Chat Completions. GPT-5.6 Terra requires `reasoning_effort="none"` for function tools on that endpoint, so the adapter sets it explicitly. A future Responses API model adapter can restore reasoning effort without changing the `AgentRuntime` contract or persisted history.

The runtime supplies tool definitions only through the provider's structured function-tool
field. Its small application-owned Smolagents template does not render names, descriptions,
schemas, or notional tool examples into the textual system prompt. The permanent prompt is
limited to identity, provenance, trust boundaries, conversational continuity, authorized
resource and skill metadata, and non-empty workspace state needed for follow-up actions.

## Configuration and secrets

The CLI loads `.env` without overriding existing process variables. `OPENAI_API_KEY` is the canonical model key name and follows official OpenAI environment-variable conventions. `BRAVE_API_KEY` authenticates public text search. The previous `MODEL_API_KEY` name remains accepted temporarily so existing Phase 2 development files continue working. Surrounding whitespace is removed; actual line breaks and literal `\\n`/`\\r` sequences are rejected. Secrets are never printed, logged, or written to events. CLI failures report only a sanitized exception-type chain plus strictly validated HTTP status, error type, code, and parameter fields. They never render provider exception messages, request bodies, headers, or tracebacks.

The initial defaults are:

```text
agent id: course-agent
runtime: smolagents-toolcalling
provider: openai
model: gpt-5.6-terra (overridable with MODEL_ID)
max steps: 10 (overridable with AGENT_MAX_STEPS)
skills path: ./skills (overridable with SKILLS_PATH)
```

## Tool and resource boundary

Phase 6 exposes these public tools:

```text
course.read_syllabus
course.read_public_file
course.get_schedule
course.get_application
course.show_public_files
course.search_faq
course.search
course.submit_application
course.ask_ta (configured, exact student role only)
web.search
web.search_images
web.visit
skills.read
skills.read_reference
```

The readable resources are `course://syllabus`, `course://schedule`,
`course://repositories`, `course://faq`, `course://instructors`, and
`course://application`. Application wrappers use canonical IDs, resource URIs, and JSON
input schemas that translate directly to MCP. They are not a second wire protocol, and
an MCP server is intentionally deferred.

Authorization happens before smolagents receives tools. `CourseCapabilityPolicy` grants
public resources to everyone, student resources to students and instructors, and instructor
resources plus application-review tools only to instructors; `ToolCatalog` fails closed if
trusted context names an unregistered tool. Read and search tools independently constrain
work to authorized resource URIs during execution. Model-controlled input cannot select a
filesystem path or applicant directory. The schedule tool identifies its source as
provisional.

Skills use standard `SKILL.md` directories with optional Markdown files under
`references/`. The repository-owned `skills/registry.json` is a separate authorization
registry, not a replacement skill format. It assigns each bundle one deterministic audience:
public, authenticated, students, or instructors. `CourseAgentService` filters skill metadata
from the trusted principal before constructing `AgentContext`; unauthorized skill names and
descriptions never reach the model. `skills.read` and `skills.read_reference` re-check that
same principal during execution and confine reference reads to registered files within the
skill directory. Full skill and reference contents are returned only to the current model
run; durable events keep a generic completion summary.

The instructor-only `instructor.inspect_application_images` tool resolves one to four
server-issued application UUIDs inside the private applicant store and submits their validated
photo bytes to the configured multimodal model only for an explicit visual request. Provider
storage is disabled, tool arguments are redacted from events, and canonical history receives
only resource provenance and a generic completion summary. The adapter prohibits identity,
sensitive-trait, personality, emotion, and admission-suitability inference from appearance.
Each inspected photo also receives an opaque `applicant://{application_id}/photo` reference.
The workspace accepts only references issued by that tool in the current instructor turn, and
the web client resolves them through the authenticated, no-store application-photo endpoint.
This lets the agent build a real private gallery without inventing filenames or making the
applicant directory web-accessible.

Resource reads also return safe registered-asset IDs when a manifest declares them.
The runtime tells the agent to prefer those official assets, attach them to a visual
composition through the source resource URI and exact asset ID, and skip redundant web
image search. Asset ownership is revalidated by the workspace tool and HTTP endpoint.

`web.search` uses Brave's authenticated Web Search API behind the application-owned,
smolagents-visible tool boundary. Requests are serialized at the configured provider rate,
retry only bounded transport, rate-limit, and service failures, and have a hard timeout.
Provider authentication, query, quota, and temporary failures retain distinct safe categories
instead of being reported as generic invalid requests. `web.visit` remains an application-owned
public-page reader. `web.search_images` wraps DuckDuckGo-first DDGS image
search, with another DDGS public-image backend as an availability fallback, and returns
normalized direct HTTPS image candidates for registered workspace components. Results
include provider pixel dimensions when available plus derived aspect, orientation,
resolution, split-layout safety, and layout guidance; unknown dimensions are explicit
rather than silently treated as banner-safe. Over-constrained queries with site or quoted
syntax receive one automatic plain-language retry inside the same tool call. A fresh DDGS
client is created per request, so concurrent conversations do not share search state. Page
reads reject non-HTTP, credential-bearing, local, and private-network
destinations. Web result bodies are returned to the current model turn but are not
copied into durable event history; only a generic completion summary is stored.

Each transient agent receives a title-and-description index of its authorized course
information. The index contains no backing paths or canonical resource identifiers;
full resource content is read through an authorized tool only when needed. The runtime
instructions require the model to resolve internal pointers before answering and forbid
mentioning capability names, resource identifiers, storage locations, or filenames
unless the user explicitly asks about implementation.

The same progressive-disclosure rule applies to skills. At startup the application validates
the registry and scans standard frontmatter. A run initially receives authorized skill IDs
and descriptions. The agent calls `skills.read` when one matches the task and calls
`skills.read_reference` only for a reference listed by the loaded skill. Course application,
workspace presentation, visual composition, web/image/browser research, student-resource,
and instructor-review procedures therefore do not occupy every turn's system prompt.

`course.search` uses deterministic paragraph-level lexical matching over the current
registered files, so edits are visible without a server restart. The companion
`course_server.index_resources` command maintains normalized PostgreSQL full-text data
for inspection and later MCP-backed search without requiring embeddings.

`course.submit_application` is public so prospective students do not need an account.
Its schema requires every structured application field and a principal-owned temporary
photo upload. Server-side validation rejects missing, placeholder, too-short, malformed,
expired, foreign, and non-image inputs. Safe validation failures give the model every
affected field and the precise failed rule, including permitted enum values, so it can
ask the applicant a corrective question; unexpected tool errors remain generic. A
successful call writes the structured record and copied photo through a private server-side
store and returns a receipt UUID. Submitted content is not
a public resource and is not included in the tool-completion result persisted by the
runtime.

Application intent has a dedicated standard Agent Skill. The header's Apply action opens the canonical
draft directly. For ordinary conversation, there is no phrase or keyword trigger in the API:
the agent recognizes application intent, reads `course.get_application` once, and opens the
canonical draft with the workspace tool during that first turn. The workspace boundary
supplies all canonical fields even when the model omits props. Older model-created
course-application drafts are recognized, migrated to the canonical fields, and marked as
application state before the next turn. The agent retains values from conversation history
and the trusted draft and interviews in displayed field order. Each
turn discusses exactly one unconfirmed field. Existing researched candidates are shown
for confirmation instead of prompting for the value again, and later missing fields are
not previewed as a checklist. Each user reply permits one atomic application-draft
update; a second update is rejected with an instruction to return one final question and
wait. Research updates preserve every supported public email, affiliation, webpage,
interest, knowledge area, and practical skill as a sourced candidate or inference, including
fields that occur later in the form. Non-final model chatter is never streamed, so a
confirmation request cannot appear while tools are still running. Closed application
choices are carried in the draft and rendered as selects. The runtime preserves JSON
Schema enums, patterns, formats, and length bounds when adapting tools for smolagents.
The picture prompt says it is for class use only and can be any JPG/JPEG, PNG, or WebP
image the applicant wants to represent them. After every field is individually confirmed,
the agent summarizes the completed form for explicit approval and only then calls
`course.submit_application`. It must not draft an application letter or invent criteria.
Submission arguments are redacted from tool-request audit events; the private
application store remains canonical.

Chat attachments are uploaded before a message is sent. The user message includes only
the temporary receipt metadata—not file bytes or a server path—so an authorized tool can
refer to the upload. Upload ownership is reconstructed from the trusted principal rather
than accepted as a tool argument. Owned document receipts become temporary `upload://`
resources: the upload reader extracts their text for reasoning and DocumentViewer fetches
the exact private artifact. The agent does not replace an available upload with a public
web copy.

smolagents requires Python-identifier tool names, so the adapter maps `course.read_syllabus` to `course_read_syllabus` only inside the transient runtime. Events and persistent state always retain the canonical dotted ID.

When a successful tool emits a trusted presentation event—opening or updating a workspace panel,
or requesting an external-effect confirmation—the adapter appends a transient presentation
instruction to that tool result. The final-answer prompt reinforces the same general contract: UI
is the primary carrier of its visible content, while chat supplies only complementary context, a
brief handoff, or the next question. Text-only tool results do not receive this additional
instruction. The same rule is part of the Course Agent's core runtime instructions, independently
of which optional skill is loaded. Final text remains the model's output and streams normally; the
runtime does not inspect, remove, or substitute response prose.

`course.ask_ta` is an external-effect workflow with deterministic separation between permission
and confirmation. The agent can prepare a question only when mail is configured and the trusted
principal is a student. The tool writes a pending record and opens the platform confirmation
surface; it cannot queue or send the email. Only the owned confirmation API can queue it, and only
the separate `course_server.mail_worker` talks to the configured Gmail or Microsoft Graph API.
After Send or Cancel, an allowlisted trusted action event—not client-authored prose—triggers a
single idempotent agent continuation. The completed action and exact question become the trusted
runtime context. The current input is only a neutral description of the completed action; the
model decides whether and how to acknowledge it and may continue any other unfinished work
without a prewritten browser response, duplicated question text, or a fabricated `user.message`.
The staff-question tool is withheld only for that continuation turn to prevent recursive
confirmation loops. A private staff reply event is included among recent supporting events so the
agent can discuss the answer on the student's next turn. The authorized staff reply places the
bounded `PUBLISH` or `PRIVATE` decision on a standalone line immediately before or after the answer.
After notifying the student, `PUBLISH` advances a durable publication outbox into `faq_entries`;
`PRIVATE` creates no shared knowledge. The coordinated publisher adds approved public fields to
the local FAQ JSON; `course://faq` reads and lexical search use that file without restarting the
runtime. The course-help skill directs the agent to check these later staff-approved clarifications
before relying on broader static course materials. If the answer remains undocumented and the
current student has the staff-question capability, the same skill directs the agent to offer that
capability rather than merely telling the student to contact staff independently.

## CLI-first flow

`course_server.agent_cli` creates a temporary anonymous session, creates its owned conversation, runs one turn, and persists canonical events to PostgreSQL. Its orchestration accepts injected stores and runtime so automated tests use a scripted model and make no external API calls.

## Stable interfaces

The Phase 3 additions to the stable application boundary are `Conversation` and `ModelProvider`. The executable tool/resource conveniences are intentionally internal until the MCP gateway phase establishes the external executable protocol.

## Deviations

There are no architecture deviations. `Conversation` was added to schema v1 additively because it was already named as an `agent_core` type in the constitution and no existing v1 document changed. MCP server transport remains deferred to its specified phase. Skill loading uses the constitution's standard directory shape and existing `AgentContext` fields and metadata, so it adds no wire-contract version or persistence migration. Phase 5 reports the concrete adapter's portable run/tool/resource events live through an optional application observer without changing `AgentRuntime`. The same adapter can optionally run smolagents in streaming mode and expose decoded final-answer text through one application callback. Private reasoning, non-final model content, full skill contents, and non-final tool arguments are discarded; non-streaming runtimes retain the ordinary `run` path, and no provider object becomes a core or persistence contract.
