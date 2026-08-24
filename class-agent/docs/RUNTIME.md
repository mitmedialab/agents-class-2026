# Phase 3 Course Agent runtime

There is one logical agent definition: `course-agent`. Each run combines that definition with a trusted `PrincipalContext`, portable conversation events, and an already-authorized list of tool and resource IDs.

## Runtime boundary

`agent_core.AgentRuntime` remains the platform boundary. `runtime_smolagents.SmolagentsRuntime` is one adapter and is the only production package that constructs `smolagents.ToolCallingAgent`. It creates a fresh transient framework agent for a run, reconstructs recent conversation context from canonical events, and returns only `AgentResult` and `Event` contracts. Phase 3 passes at most the 50 most recent events into a run.

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

Phase 3 implements one public tool, `course.read_syllabus`, and one public resource, `course://syllabus`. Application wrappers use canonical IDs, resource URIs, and JSON input schemas that translate directly to MCP. They are not a second wire protocol, and an MCP server is intentionally deferred.

Authorization happens before smolagents receives tools. `PublicCapabilityPolicy` grants only the Phase 3 public capability; `ToolCatalog` fails closed if trusted context names an unregistered tool. The syllabus tool also checks the authorized resource URI during execution. Model-controlled input cannot select a filesystem path.

smolagents requires Python-identifier tool names, so the adapter maps `course.read_syllabus` to `course_read_syllabus` only inside the transient runtime. Events and persistent state always retain the canonical dotted ID.

## CLI-first flow

`course_server.agent_cli` creates a temporary anonymous session, creates its owned conversation, runs one turn, and persists canonical events to PostgreSQL. Its orchestration accepts injected stores and runtime so automated tests use a scripted model and make no external API calls.

## Stable interfaces

The Phase 3 additions to the stable application boundary are `Conversation` and `ModelProvider`. The executable tool/resource conveniences are intentionally internal until the MCP gateway phase establishes the external executable protocol.

## Deviations

There are no architecture deviations. `Conversation` was added to schema v1 additively because it was already named as an `agent_core` type in the constitution and no existing v1 document changed. MCP server transport and skill loading remain deferred to their specified phases. Phase 5 reports the concrete adapter's portable run/tool/resource events live through an optional application observer without changing `AgentRuntime`. The same adapter can optionally run smolagents in streaming mode and expose decoded final-answer text through one application callback. A separate optional callback receives only ordinary assistant content deliberately written as a brief user-facing progress message before a non-final tool action. Private reasoning and non-final tool arguments are discarded, progress is not persisted as conversation history, non-streaming runtimes retain the ordinary `run` path, and no provider object becomes a core or persistence contract.
