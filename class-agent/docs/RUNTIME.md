# Course Agent runtime

There is one logical agent definition: `course-agent`. Each run combines that definition with a trusted `PrincipalContext`, portable conversation events, and an already-authorized list of tool and resource IDs.

## Runtime boundary

`agent_core.AgentRuntime` remains the platform boundary. `runtime_smolagents.SmolagentsRuntime` is one adapter and is the only production package that constructs `smolagents.ToolCallingAgent`. It creates a fresh transient framework agent for a run, reconstructs recent conversation context from canonical events, and returns only `AgentResult` and `Event` contracts. Context selection keeps the 24 most recent user/agent messages and 16 useful tool-completion or workspace-interaction events. Run lifecycle and tool-request bookkeeping do not consume that budget.

The adapter reconstructs those portable user and assistant events as correctly role-scoped, ephemeral smolagents memory before each run. Dialogue is never flattened into the system instructions, and the transient memory is discarded afterward. This preserves conversational follow-ups—especially confirmations, corrections, requests to continue, and attachments—without making framework state canonical.

No smolagents agent, memory, model, `RunResult`, or pickle is canonical persistent state. `CodeAgent` is not used.

`agent_core.ModelProvider` is a small generic factory boundary. The v1 `OpenAIModelProvider` returns a transient smolagents `OpenAIModel`; another provider or runtime can replace it without migrating event history.

smolagents 1.x sends `ToolCallingAgent` function tools through Chat Completions. GPT-5.6 Terra requires `reasoning_effort="none"` for function tools on that endpoint, so the adapter sets it explicitly. A future Responses API model adapter can restore reasoning effort without changing the `AgentRuntime` contract or persisted history.

## Configuration and secrets

The CLI loads `.env` without overriding existing process variables. `OPENAI_API_KEY` is the canonical key name and follows official OpenAI environment-variable conventions. The previous `MODEL_API_KEY` name remains accepted temporarily so existing Phase 2 development files continue working. Surrounding whitespace is removed; actual line breaks and literal `\\n`/`\\r` sequences are rejected. Neither value is printed, logged, or written to events. CLI failures report only a sanitized exception-type chain plus strictly validated HTTP status, error type, code, and parameter fields. They never render provider exception messages, request bodies, headers, or tracebacks.

The initial defaults are:

```text
agent id: course-agent
runtime: smolagents-toolcalling
provider: openai
model: gpt-5.6-terra (overridable with MODEL_ID)
max steps: 10 (overridable with AGENT_MAX_STEPS)
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
web.search
web.search_images
web.visit
```

The readable resources are `course://syllabus`, `course://schedule`,
`course://repositories`, `course://faq`, `course://instructors`, and
`course://application`. Application wrappers use canonical IDs, resource URIs, and JSON
input schemas that translate directly to MCP. They are not a second wire protocol, and
an MCP server is intentionally deferred.

Authorization happens before smolagents receives tools. `PublicCapabilityPolicy`
grants only Phase 6 public course capabilities; `ToolCatalog` fails closed if trusted
context names an unregistered tool. Read and search tools independently constrain work
to authorized resource URIs during execution. Model-controlled input cannot select a
filesystem path. The schedule tool identifies its source as provisional.

Resource reads also return safe registered-asset IDs when a manifest declares them.
The runtime tells the agent to prefer those official assets, attach them to a visual
composition through the source resource URI and exact asset ID, and skip redundant web
image search. Asset ownership is revalidated by the workspace tool and HTTP endpoint.

`web.search` and `web.visit` wrap smolagents' toolkit implementations inside the same
authorized platform boundary. `web.search_images` wraps DuckDuckGo-first DDGS image
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

Each transient agent receives a title-and-description index of its authorized public
information. The index contains no backing paths or canonical resource identifiers;
full resource content is read through an authorized tool only when needed. The runtime
instructions require the model to resolve internal pointers before answering and forbid
mentioning capability names, resource identifiers, storage locations, or filenames
unless the user explicitly asks about implementation.

`course.search` uses deterministic paragraph-level lexical matching over the current
registered files, so edits are visible without a server restart. The companion
`course_server.index_resources` command maintains normalized PostgreSQL full-text data
for inspection and later MCP-backed search without requiring embeddings.

`course.submit_application` is public so prospective students do not need an account.
Its schema requires every structured application field and a principal-owned temporary
photo upload. Server-side validation rejects missing, placeholder, too-short, malformed,
expired, foreign, and non-image inputs. Safe validation failures name the affected
fields to the model so it can ask the applicant follow-up questions; unexpected tool
errors remain generic. A successful call writes the structured record and copied photo
through a private server-side store and returns a receipt UUID. Submitted content is not
a public resource and is not included in the tool-completion result persisted by the
runtime.

Application intent has a dedicated workflow. The header's Apply action opens the canonical
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
confirmation request cannot appear while tools are still running. The picture prompt says it
is for class use only and can be any JPEG, PNG, or WebP image the applicant wants to
represent them. After every field is individually confirmed, the
agent summarizes the completed form for explicit approval and only then calls
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

## CLI-first flow

`course_server.agent_cli` creates a temporary anonymous session, creates its owned conversation, runs one turn, and persists canonical events to PostgreSQL. Its orchestration accepts injected stores and runtime so automated tests use a scripted model and make no external API calls.

## Stable interfaces

The Phase 3 additions to the stable application boundary are `Conversation` and `ModelProvider`. The executable tool/resource conveniences are intentionally internal until the MCP gateway phase establishes the external executable protocol.

## Deviations

There are no architecture deviations. `Conversation` was added to schema v1 additively because it was already named as an `agent_core` type in the constitution and no existing v1 document changed. MCP server transport and skill loading remain deferred to their specified phases. Phase 5 reports the concrete adapter's portable run/tool/resource events live through an optional application observer without changing `AgentRuntime`. The same adapter can optionally run smolagents in streaming mode and expose decoded final-answer text through one application callback. Private reasoning, non-final model content, and non-final tool arguments are discarded; non-streaming runtimes retain the ordinary `run` path, and no provider object becomes a core or persistence contract.
