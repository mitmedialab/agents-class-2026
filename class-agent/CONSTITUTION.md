# Codex Implementation Specification — MIT Cognitive Agent Course Platform

## Status

This document is the implementation specification for the initial version of an extensible AI-agent platform for an MIT Media Lab course.

Treat this document as the architectural source of truth.

Do **not** attempt to invent a different overall architecture unless a requirement is technically impossible. When an implementation choice is underspecified, favor:

1. simplicity;
2. open standards;
3. portability;
4. long-term maintainability;
5. explicit interfaces;
6. minimal vendor lock-in;
7. easy modification by students.

The initial class size is approximately 20 students, so do not over-engineer for millions of users.

---

# 1. Product goal

Build a single persistent **Course Agent** accessible at a Media Lab-hosted website.

The agent should initially work as a normal web agent with no installation required.

It must later be capable of extending itself into:

* browser tabs;
* arbitrary webpages;
* local files;
* local applications;
* local terminal/process execution;
* local models;
* cameras and microphones;
* Raspberry Pis;
* wearables;
* custom hardware;
* student-created tools;
* student-created interfaces.

Users should encounter these capabilities progressively.

Example:

> User: Organize my Downloads folder.

The Course Agent realizes that `filesystem.read` and `filesystem.write` are required but unavailable.

The website renders:

> I need access to files on this computer to do that.

> **[Enable local access]**

Installing Agent Bridge causes the capabilities to become available.

The conversation must continue without restarting.

---

# 2. One agent, not one agent per student

There is exactly one logical production agent:

```text
course-agent
```

Do not create separate agent definitions such as:

```text
alice-agent
bob-agent
charlie-agent
```

Instead, every request reconstructs:

```text
Course Agent
+
Principal Context
+
Conversation Context
+
Permitted Resources
+
Permitted Tools
+
Available Device Capabilities
```

An anonymous visitor and a logged-in student are therefore talking to the **same logical Course Agent**, but the agent sees different context and capabilities.

Conceptually:

```text
                         COURSE AGENT
                              │
                    same policy/runtime
                              │
             ┌────────────────┼────────────────┐
             │                │                │
          PUBLIC           STUDENT             TA
             │                │                │
      public resources    own history       TA queue
      public tools        own memories      FAQ tools
                          grades
                          local devices
                          ask-TA tool
```

Authorization must occur **before** tools/resources are exposed to the model.

Never expose a privileged tool and rely on prompting the model not to use it.

---

# 3. Overall architecture

```text
                         MEDIA LAB SERVER

                    agents.media.mit.edu
                              │
              ┌───────────────┼─────────────────┐
              │               │                 │
         Static React       FastAPI          Shared storage
          frontend           backend              │
              │               │                  course files
              │               │                  syllabus
              │          agent runtime            schedule
              │          MCP host/server          datasets
              │          authorization            releases
              │               │
              │          PostgreSQL
              │               │
              │          users
              │          sessions
              │          conversations
              │          roaming memories
              │          course knowledge
              │          TA questions
              │
              │
              └───────────────┬────────────────────────
                              │ HTTPS
                              │
                    OPTIONAL USER NODES
                              │
            ┌─────────────────┼──────────────────┐
            │                 │                  │
       Browser extension   Agent Bridge       Raspberry Pi
            │                 │                  │
       DOM / tabs          SQLite              camera
       page actions        files               GPIO
       injected UI         apps                sensors
                           processes
                           local models
```

The Media Lab service is the stable coordination layer.

The Media Lab server should **not require a GPU**.

LLM inference can initially use external APIs.

---

# 4. Technology stack

Use these choices unless a strong technical reason requires otherwise.

## Frontend

```text
TypeScript
React
Vite
pnpm workspaces
```

Avoid making Next.js fundamental to the architecture.

The web application should build to ordinary static assets wherever possible:

```text
index.html
assets/*.js
assets/*.css
```

This improves archival longevity and simplifies Media Lab hosting.

## UI

Use:

```text
React
CSS variables
CSS Modules or equivalent locally owned CSS
```

Build a first-party component library inside the repository.

Do not make the design system dependent on a commercial hosted service.

Headless accessibility libraries may be used where useful, but component source and styling should remain easy for students to understand and modify.

## Backend

```text
Python
FastAPI
Pydantic
```

## Agent runtime

Default:

```text
smolagents.CodeAgent
```

smolagents must exist **behind our own AgentRuntime interface**.

## Server database

```text
PostgreSQL
```

## Local Agent Bridge database

```text
SQLite
```

Use WAL mode.

## Agent/tool interoperability

```text
MCP specification 2026-07-28
```

## Interactive agent-provided interfaces

```text
MCP Apps
```

Use the official MCP Apps TypeScript SDK where appropriate.

## Procedural agent knowledge

```text
Agent Skills / SKILL.md
```

## Coding-agent repository instructions

```text
AGENTS.md
```

---

# 5. Architectural rule: frameworks are adapters

This rule is extremely important.

```text
FastAPI is not the platform.
React is not the platform.
smolagents is not the platform.
PostgreSQL is not the platform.
SQLite is not the platform.
MCP SDK implementations are not the platform.

agent_core + platform protocols are the platform.
```

All external libraries should sit behind application-owned interfaces where doing so is reasonable.

The project must survive replacing:

* smolagents;
* a model provider;
* PostgreSQL;
* FastAPI;
* frontend styling libraries;
* hosting infrastructure.

Do not serialize opaque framework objects as canonical persistent state.

---

# 6. Monorepo structure

Create approximately:

```text
class-agent/
│
├── AGENTS.md
├── README.md
├── CONTRIBUTING.md
├── LICENSE
├── .env.example
├── docker-compose.yml
├── pnpm-workspace.yaml
├── pyproject.toml
│
├── apps/
│   │
│   ├── web/
│   │   ├── src/
│   │   ├── index.html
│   │   ├── vite.config.ts
│   │   └── package.json
│   │
│   ├── extension/
│   │   ├── src/
│   │   ├── manifest.json
│   │   └── package.json
│   │
│   └── bridge-ui/
│       └── optional future desktop UI
│
├── packages/
│   │
│   ├── ui/
│   │   ├── src/
│   │   └── package.json
│   │
│   ├── workspace/
│   │   ├── src/
│   │   └── package.json
│   │
│   ├── protocol/
│   │   ├── src/
│   │   └── package.json
│   │
│   └── mcp-app-host/
│       ├── src/
│       └── package.json
│
├── python/
│   │
│   ├── agent_core/
│   │
│   ├── runtime_smolagents/
│   │
│   ├── course_server/
│   │
│   ├── bridge/
│   │
│   └── nodes/
│   │
│   └── tests/
│
├── mcp/
│   │
│   ├── course/
│   │
│   ├── workspace/
│   │
│   ├── local_computer/
│   │
│   └── browser/
│
├── skills/
│   │
│   ├── course-help/
│   │   ├── SKILL.md
│   │   └── references/
│   │
│   ├── socratic-teaching/
│   │   └── SKILL.md
│   │
│   └── README.md
│
├── shared/
│   │
│   ├── schemas/
│   │
│   ├── course/
│   │
│   └── registry/
│
├── database/
│   ├── migrations/
│   └── seeds/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── EVENTS.md
│   ├── MCP.md
│   ├── UI.md
│   ├── AUTH.md
│   ├── STORAGE.md
│   ├── PRIVACY.md
│   ├── BRIDGE.md
│   └── EXTENSION.md
│
└── examples/
    ├── add-tool/
    ├── add-ui-component/
    ├── add-skill/
    ├── browser-agent/
    └── raspberry-pi/
```

---

# 7. `AGENTS.md`

Create a root `AGENTS.md`.

This file is specifically for Codex and other coding agents modifying the repository.

It should prominently state:

```text
# Architecture invariants

1. There is one logical Course Agent.
2. Authentication/authorization is enforced in application code,
   never only through prompts.
3. MCP is the canonical executable tool/resource boundary.
4. Agent Skills use standard SKILL.md directories.
5. Interactive third-party agent UIs use MCP Apps.
6. First-party workspace components use the registered component protocol.
7. agent_core must not import FastAPI, React, or PostgreSQL.
8. smolagents must remain behind AgentRuntime.
9. Never persist smolagents internal objects as canonical history.
10. Local file contents must not be uploaded automatically.
11. Privileged tools must derive identity from PrincipalContext rather
    than model-controlled user IDs.
12. Run all contract tests before modifying stable interfaces.
```

Include development commands.

---

# 8. Authentication design

Do **not** implement Touchstone.

Students will receive credentials individually.

Each enrolled user has:

```text
username
access code
```

The access code should behave like a password technically, even if the UI calls it an **access code**.

Do not use short numeric PINs.

Generate at least approximately 128 bits of entropy.

Example user-facing code:

```text
maze-river-82-N7qm-cobalt
```

or an equivalent randomly generated high-entropy string.

## Database

Create:

```text
users
────────────────────────────
id
username
display_name
email
role
access_code_hash
active
created_at
updated_at
```

Roles:

```text
student
ta
instructor
admin
```

Anonymous users have no user row.

## Password hashing

Store only a slow cryptographic hash.

Use:

```text
Argon2id
```

Never store access codes in plaintext.

## Admin creation

Provide an admin CLI:

```bash
python -m course_server.admin create-user \
    --username alice \
    --name "Alice Example" \
    --email alice@mit.edu \
    --role student
```

The command should:

1. create a random access code;
2. store only its hash;
3. print the code exactly once;
4. optionally send the credentials using the course email adapter.

Example output:

```text
User created.

Username: alice
Access code: maze-river-82-N7qm-cobalt

This code will not be displayed again.
```

Also provide:

```bash
reset-user-code
deactivate-user
activate-user
list-users
change-role
```

---

# 9. Login session

The access code should not be required on every page load.

Upon successful login:

1. validate username;
2. verify Argon2id access-code hash;
3. create a random server-side session;
4. place an opaque session identifier in a cookie.

Cookie requirements:

```text
HttpOnly
Secure
SameSite=Lax
```

Sessions should be revocable.

Database:

```text
auth_sessions
────────────────────────────
id
user_id
token_hash
created_at
expires_at
last_seen_at
revoked_at
```

Do not store raw session tokens.

Suggested initial expiry:

```text
30 days
```

with activity extension if desired.

Students can explicitly log out.

Rate-limit failed authentication.

---

# 10. Anonymous users

Public visitors require no account.

Create a random:

```text
anonymous_session_id
```

Store it in a browser cookie/local storage as appropriate.

Anonymous conversations must not share state with one another.

Anonymous history should expire automatically.

Suggested initial retention:

```text
7 days
```

Make this configurable.

Anonymous users receive:

```text
role = public
```

conceptually, but do not create permanent user accounts.

---

# 11. PrincipalContext

Every agent request must resolve a `PrincipalContext`.

Python model:

```python
class PrincipalContext(BaseModel):
    authenticated: bool

    user_id: UUID | None
    anonymous_session_id: UUID | None

    username: str | None
    display_name: str | None

    roles: list[str]

    session_id: UUID
```

Examples.

Public:

```json
{
  "authenticated": false,
  "user_id": null,
  "roles": ["public"]
}
```

Student:

```json
{
  "authenticated": true,
  "user_id": "...",
  "username": "alice",
  "roles": ["public", "student"]
}
```

TA:

```json
{
  "authenticated": true,
  "roles": ["public", "ta"]
}
```

---

# 12. Tool authorization

Available tools are calculated from:

```text
PrincipalContext
+
connected nodes
+
granted permissions
+
course configuration
```

The model must only receive tools it is genuinely authorized to call.

For example:

```text
course.read_syllabus      public
course.get_schedule       public
course.search_faq         public

course.ask_ta             student
grades.get_mine           student
memory.get_mine           student

ta.list_questions         ta
ta.publish_faq            ta

filesystem.read           only if Bridge connected
                           and permission granted
```

Do not expose:

```text
grades.get_student(student_id)
```

to a student.

Expose:

```text
grades.get_mine()
```

Identity must come from trusted execution context:

```python
user_id = tool_context.principal.user_id
```

not from model arguments.

---

# 13. One Course Agent configuration

Create a global Course Agent configuration.

Example:

```yaml
id: course-agent
name: Class Agent

runtime: smolagents-toolcalling

model:
  provider: openai
  model: configurable

max_steps: 10

skills:
  - course-help
  - socratic-teaching
```

The exact model should be configurable using environment/config files.

Do not encode model-specific behavior into stored conversation history.

---

# 14. Agent core package

Create:

```text
python/agent_core/
```

It must contain domain models and abstract interfaces only.

It must not import:

```text
FastAPI
SQLAlchemy-specific application logic
smolagents
frontend code
```

Core types:

```text
Event
Conversation
Message
Memory
PrincipalContext
AgentContext
Capability
Permission
Node
AgentInput
AgentResult
ToolExecution
ResourceReference
```

---

# 15. AgentRuntime interface

Define:

```python
class AgentRuntime(Protocol):

    async def run(
        self,
        *,
        context: AgentContext,
        input: AgentInput,
    ) -> AgentResult:
        ...
```

No other system component should depend directly on smolagents.

---

# 16. Smolagents runtime

Implement:

```text
runtime_smolagents/
```

Default runtime:

```python
ToolCallingAgent
```

Do not make `CodeAgent` the public/default production runtime.

Reason:

`CodeAgent` generates executable Python.

It can be offered later for class experiments, but any generated-code execution must use a deliberate sandbox.

Adapter responsibilities:

1. convert platform tools/MCP capabilities into smolagents tools;
2. build runtime prompt/context;
3. convert platform conversation/history into runtime-compatible input;
4. execute the agent;
5. translate runtime results into platform events/results.

Do not persist:

```text
smolagents Agent object
smolagents memory object
Python pickles
```

as canonical state.

---

# 17. Model provider interface

Define:

```python
class ModelProvider(Protocol):
    ...
```

Support adapters eventually for:

```text
OpenAI
Anthropic
Hugging Face
Ollama
local transformers
other APIs
```

v1 can implement only the provider actually used.

The persisted agent state must not depend on any one provider.

---

# 18. Canonical event history

Use an event system as the durable history representation.

Do not make a raw `messages[]` array the entire data model.

Define:

```python
class Event(BaseModel):
    id: UUID
    schema_version: int = 1

    timestamp: datetime

    type: str
    actor: str

    principal_user_id: UUID | None
    anonymous_session_id: UUID | None

    conversation_id: UUID | None
    node_id: UUID | None

    payload: dict[str, Any]
    metadata: dict[str, Any]
```

Event names:

```text
user.message
agent.message

agent.run.started
agent.run.completed

agent.tool.requested
agent.tool.completed
agent.tool.failed

resource.read

capability.requested
capability.available
capability.revoked

permission.requested
permission.granted
permission.denied
permission.revoked

node.connected
node.disconnected

workspace.panel.opened
workspace.panel.updated
workspace.panel.closed

memory.created
memory.updated

email.ta_question.created
email.ta_answer.received

system.error
```

---

# 19. Conversation representation

Create explicit conversations.

```text
conversations
────────────────────────────
id
user_id nullable
anonymous_session_id nullable
created_at
updated_at
title nullable
archived_at nullable
```

Authenticated students get persistent conversation history.

Public anonymous histories are temporary.

Messages should either be derived from events or stored in a normalized message table while still emitting canonical events.

---

# 20. Data classification

Explicitly classify data into three main categories.

## A. Media Lab shared/public

Store on Media Lab server:

```text
course syllabus
course schedule
assignment descriptions
public datasets
course FAQ
student repository overview
shared tools
released components
documentation
course resources
```

## B. Media Lab user-specific lightweight state

Store on Media Lab server:

```text
account
conversation text
conversation metadata
user memories intentionally stored by agent
activity summaries
agent preferences
grades
TA questions
TA answers
connected-device metadata
permission metadata
```

Do not include raw local documents by default.

## C. Local-only high-resolution data

Store through Agent Bridge:

```text
local file contents
local filesystem index
raw browser snapshots if sensitive
screenshots
local application context
sensor streams
large raw tool outputs
local model caches
private detailed event traces
```

The Bridge may send a compact result or summary to the Course Agent when required for a task.

---

# 21. Server PostgreSQL schema

Create migrations for at least:

```text
users
auth_sessions

conversations
events
memories
activity_summaries

nodes
permissions

course_resources
faq_entries

ta_questions
ta_answers

grades

schema_migrations
```

Potential later tables:

```text
assignments
student_projects
tool_usage
```

---

# 22. Memories

Memories are not the same as event history.

Define:

```python
class Memory(BaseModel):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    kind: str
    content: str

    source_event_ids: list[UUID]

    privacy: Literal[
        "personal",
        "course_private"
    ]

    metadata: dict[str, Any]
```

Examples:

```text
Alice is building a gaze-aware study agent.
Alice prefers hints before full answers.
Alice's current final project uses Raspberry Pi.
```

Do not build a complicated memory architecture in v1.

Use:

```text
recent conversation
+
selected memories
+
activity summaries
```

initially.

---

# 23. Activity summaries

Provide lightweight summaries over longer periods.

Example:

```json
{
  "period": "2026-W39",
  "summary": "Alice worked primarily on the browser-agent assignment and frequently used the DOM inspection tool.",
  "metrics": {
    "agent_interactions": 47,
    "tool_calls": 31
  }
}
```

These are intended to provide continuity without requiring all high-resolution local data to be uploaded.

---

# 24. Shared course resources

Store durable files on the Media Lab server.

Suggested filesystem:

```text
/srv/class-agent/shared/
│
├── course/
│   ├── syllabus/
│   │   ├── syllabus.pdf
│   │   └── syllabus.md
│   │
│   ├── schedule/
│   │   ├── schedule.pdf
│   │   ├── schedule.json
│   │   └── schedule.ics
│   │
│   ├── repositories/
│   │   ├── repositories.md
│   │   └── repositories.json
│   │
│   ├── faq/
│   │
│   └── assignments/
│
├── datasets/
├── tools/
├── releases/
└── registry/
```

Whenever possible, maintain both:

```text
human-facing format
+
machine-readable format
```

Examples:

```text
schedule.pdf + schedule.json
syllabus.pdf + syllabus.md
repositories.md + repositories.json
```

---

# 25. MCP as the canonical agent capability standard

Use MCP for the agent-facing boundary.

Do not invent a competing proprietary tool format as the canonical representation.

The Course Agent should interact with:

```text
MCP tools
MCP resources
MCP Apps
```

Internal convenience wrappers are acceptable, but they must translate cleanly to MCP concepts.

---

# 26. MCP topology

There may eventually be multiple capability providers:

```text
course MCP server
workspace MCP server
local-computer MCP provider
browser capability provider
device providers
```

From the Course Agent's perspective, these should appear as one authorized capability catalog.

Implement an internal **MCP Capability Gateway** that aggregates/filter tools and resources.

Conceptually:

```text
                    COURSE AGENT
                         │
                    MCP gateway
                         │
        ┌────────────────┼────────────────┐
        │                │                │
      course          workspace         devices
       MCP               MCP              MCP
```

---

# 27. Course MCP resources

Expose resources conceptually such as:

```text
course://syllabus
course://syllabus.pdf

course://schedule
course://schedule.pdf

course://repositories

course://faq
course://faq/{entry_id}

course://assignment/{assignment_id}
```

Authorization can affect resource visibility.

---

# 28. Course MCP tools

Initial examples:

```text
course.search
course.get_schedule
course.search_faq
course.get_assignment

course.ask_ta

memory.get_mine
memory.save_mine

grades.get_mine
```

Staff:

```text
ta.list_questions
ta.get_question
ta.publish_faq

instructor.manage_course_resource
```

---

# 29. Agent Skills

Use standard Agent Skills directory structure.

Example:

```text
skills/
└── course-help/
    ├── SKILL.md
    └── references/
        └── policies.md
```

Example:

```yaml
---
name: course-help
description: Answer questions about the course, assignments, policies, schedule, and student resources. Use when a user asks about course logistics or expectations.
---

Use official course resources as the source of truth.

When a question cannot be answered confidently from course resources:
1. say that the answer is not documented;
2. if the user is an authenticated student, offer the ask-TA tool;
3. do not invent course policy.
```

Another:

```text
skills/socratic-teaching/SKILL.md
```

The skill loader should:

1. scan skill metadata at startup;
2. make name/description available to the runtime;
3. load the full skill only when relevant;
4. support skill references.

Do not invent another proprietary skill file format.

---

# 30. Frontend product model: conversation + workspace

The web app must not be only a chat column.

Build it as:

```text
┌─────────────────────────────────────────────────────────┐
│ Course Agent                                        ... │
├───────────────────────┬─────────────────────────────────┤
│                       │                                 │
│ Conversation          │ Workspace                       │
│                       │                                 │
│ User                  │ active panels/components        │
│ Agent                 │                                 │
│ Tool status           │                                 │
│                       │                                 │
│                       │                                 │
├───────────────────────┴─────────────────────────────────┤
│ message composer                                        │
└─────────────────────────────────────────────────────────┘
```

Responsive mobile layouts may collapse workspace to tabs.

---

# 31. First-party React component library

Create:

```text
packages/ui/
```

Components should be independently importable.

Start with:

```text
Button
IconButton
Input
Textarea
Card
Dialog
Popover
Tooltip
Tabs
Badge
Spinner
Toast

SplitPane
Panel
Toolbar

ChatMessage
ToolCallIndicator
PermissionCard
CapabilityRequest

DocumentViewer
PDFViewer
WebpageViewer
Calendar
DataTable
JSONViewer
CodeViewer
ImageViewer
Timeline
```

Later students can add:

```text
ArgumentMap
ConceptGraph
Quiz
GazeVisualization
SensorPlot
AgentTrajectory
etc.
```

---

# 32. UI design tokens

Use CSS variables.

Example:

```css
:root {
  --color-background: ...;
  --color-surface: ...;
  --color-surface-raised: ...;

  --color-text: ...;
  --color-text-muted: ...;

  --color-border: ...;
  --color-accent: ...;

  --radius-sm: ...;
  --radius-md: ...;
  --radius-lg: ...;

  --space-1: ...;
  --space-2: ...;
  --space-3: ...;
}
```

Do not hard-code styling independently in every agent component.

---

# 33. Workspace state

Define a typed workspace model.

```ts
export interface WorkspaceState {
  panels: WorkspacePanel[]
  focusedPanelId?: string
}

export interface WorkspacePanel {
  id: string
  componentId: string
  title?: string

  resourceUri?: string

  props: unknown
  state: unknown

  layout?: {
    width?: number
    height?: number
  }
}
```

Persist workspace state per conversation where useful.

---

# 34. Registered component protocol

The Course Agent should be able to manipulate first-party components semantically.

Define a registry:

```ts
interface ComponentManifest {
  id: string
  version: string

  title: string
  description: string

  propsSchema: JSONSchema

  supportedOperations: string[]

  defaultSize?: {
    width: number
    height: number
  }
}
```

Examples:

```text
calendar
document-viewer
visual-composition
data-table
code-viewer
timeline
image-viewer
```

The agent should not need React implementation details.

---

# 35. Workspace tools

Expose UI actions to the Course Agent as MCP tools.

Examples:

```text
workspace.list_components

workspace.open_component

workspace.update_component

workspace.focus_component

workspace.close_component
```

Example call:

```json
{
  "component_id": "visual-composition",
  "props": {
    "root_id": "overview",
    "elements": [
      {
        "id": "overview",
        "type": "text",
        "text": "A synthesized course overview"
      }
    ]
  }
}
```

Another:

```json
{
  "component_id": "calendar",
  "resource_uri": "course://schedule",
  "props": {
    "view": "month",
    "focus_date": "2026-10-08"
  }
}
```

---

# 36. Artifact and knowledge routing

Choose the workspace surface from the user's intent, not merely the source format. The
workspace has one current surface: a new subject, artifact, or view replaces the prior
panel instead of retaining stale UI.

Open a specific paper, PDF, text file, or other concrete artifact in DocumentViewer
when the user wants to read it, navigate it, search it, or discuss particular passages.
An artifact uploaded in chat remains the canonical artifact: the agent reads and opens
that exact principal-scoped upload rather than silently substituting a public copy.
Open a specific website in WebpageViewer, or use the remote browser when the user wants
to interact with the live site. A direct user click updates the canonical browser panel,
so the URL, title, and clicked session are available to the next agent turn.

For knowledge questions, summaries, comparisons, and overviews, the agent reads
authorized source material, selects the useful information, and synthesizes it into a
registered visual component even when the source happens to be Markdown. Prefer clear
hierarchy, structured groups, headings, text, facts, and links. Include images only
when relevant imagery would materially improve understanding, identity, comparison,
or engagement. For people, physical projects, places, interfaces, devices, and other
visually identifiable subjects, find and use suitable verified imagery without waiting
for the user to request it. For abstract or administrative topics, create schematic
process, comparison, timeline, or metric structures rather than adding decorative images.
Avoid long paragraph stacks in either case.
The trusted workspace layer enforces the concrete-subject rule: it requires an image
search before opening the composition and, when that search yields usable candidates,
requires the composition to include suitable imagery. No-result searches may fall back
to a schematic composition.
Visual imagery supports bounded semantic presentations: panoramic banner, editorial
feature, repeated card, and profile avatar. The agent chooses among banner-led, split,
gallery, profile, process, timeline, and comparison structures according to the answer;
it does not repeat one centered hero layout for every query.
A new question or analytical angle receives a fresh purpose-built composition; update
the existing composition only when the user is explicitly iterating on that UI.

---

# 37. MCP Apps

Support official MCP Apps in the frontend host.

Use MCP Apps for:

* student-created interactive interfaces;
* external MCP servers with rich views;
* complex interactive visualizations;
* tool-specific interfaces.

MCP Apps should render inside their intended sandboxed iframe boundary.

Do not directly inject arbitrary third-party React into the trusted host.

Conceptually:

```text
Trusted built-in component
    → native React component

External/student MCP App
    → sandboxed MCP Apps iframe
```

---

# 38. Agent-generated UI security

Default behavior:

Allowed:

```text
select component
open component
close component
set validated props
update component state
highlight text
choose resource
```

Not allowed by default:

```text
generate arbitrary JavaScript and execute it
generate arbitrary React and mount it
inject arbitrary HTML with scripts
modify host authentication UI
access secrets through UI components
```

A developer-only experimental mode may later relax this.

---

# 39. Example dynamic UI flow

User:

> When is the midterm project review and what do I need to submit?

Agent:

1. reads `course://schedule`;
2. reads assignment resource;
3. answers in text;
4. calls `workspace.open_component` with `calendar`;
5. calendar opens focused on review date;
6. synthesizes the assignment requirements into `visual-composition`;
7. the visual overview opens beside the conversation.

All of this happens in one conversation.

---

# 40. Public knowledge search

Implement a simple:

```text
course.search
```

tool.

Initial search can use:

```text
PostgreSQL full-text search
```

over normalized text resources.

Do not require a vector database for v1.

Later embeddings/pgvector may be added.

Index:

```text
syllabus.md
schedule.json normalized text
assignments
repository overview
FAQ
```

---

# 41. Grades

Provide a future-ready table:

```text
grades
────────────────────────────
id
user_id
assignment_id
grade
feedback
updated_at
```

Tool:

```text
grades.get_mine()
```

must derive user identity from authenticated context.

Never accept:

```text
user_id
username
student_name
```

as model-provided parameters.

Grade values should not be written into public event logs or analytics logs.

---

# 42. TA email workflow

Assume the course can obtain a Media Lab email account.

Example conceptual mailbox:

```text
course-agent@media.mit.edu
```

Do not assume a specific SMTP/IMAP implementation until NeCSys confirms what is available.

Create:

```python
class MailAdapter(Protocol):

    async def send_message(...):
        ...

    async def fetch_new_messages(...):
        ...
```

Implement whichever backend NeCSys supports.

Likely possibilities include:

```text
SMTP + IMAP
or
institutional mail API
```

Keep this outside `agent_core`.

---

# 43. Student asks TA

Authenticated students receive MCP tool:

```text
course.ask_ta
```

Parameters:

```text
subject
question
optional context
```

Do not take the student's email/name as arguments.

Resolve them from PrincipalContext.

On invocation:

1. create a `ta_questions` row;
2. assign stable question ID;
3. send email to TA mailbox/list;
4. record outbound Message-ID;
5. return confirmation to agent.

Question ID example:

```text
Q-2026-00417
```

---

# 44. TA question schema

```text
ta_questions
────────────────────────────
id
public_question_code
student_user_id
conversation_id
subject
question_text
context_text nullable
status
outbound_message_id
created_at
resolved_at
```

Statuses:

```text
open
answered
closed
```

---

# 45. Email sent to TA

Example:

```text
Subject:
[Course Agent Q-2026-00417] Local models for Assignment 3

Student:
Alice

Question:

Can we use a locally fine-tuned model for Assignment 3?

Conversation context:
[small relevant context if explicitly selected]

Put PUBLISH or PRIVATE on the first nonblank line, then write the answer below it.
```

Avoid sending entire conversations unless necessary.

---

# 46. Receiving TA replies

Create a background email worker separate from the request-serving FastAPI process.

For example:

```text
course_server.mail_worker
```

Depending on mailbox capabilities:

* use push/webhooks if available and simple;
* otherwise poll for new messages periodically.

For a 20-person class, one-minute polling is entirely adequate.

Match replies using:

1. `In-Reply-To`;
2. `References`;
3. stored Message-ID;
4. fallback question code in subject.

Avoid subject matching alone.

---

# 47. TA answer handling

On matching a reply:

1. sanitize/extract reply text;
2. create `ta_answers` record;
3. associate with question;
4. mark question answered;
5. email answer to original student;
6. insert a private event into that student's relevant conversation;
7. make the answer available to the Course Agent in that student's context.

---

# 48. TA answers are private by default

Do **not** automatically convert email replies into global course knowledge.

Default:

```text
visibility = private
```

Use the first authorized staff reply as both the answer and the moderation decision. The first
nonblank line must be one of:

```text
PUBLISH
PRIVATE
```

The answer follows on subsequent lines. `PUBLISH` sends the answer to the student and approves the
redacted question and answer for shared course knowledge. `PRIVATE` sends the answer only to the
student.

The platform:

1. derives the candidate from the exact question and staff answer;
2. excludes private conversation context and redacts the known student name and email;
3. requires the decision as the first nonblank line of the answer;
4. requires a reply from an authorized TA, instructor, or admin;
5. inserts only a `PUBLISH` answer into the public FAQ.

Email receipt and decision state must be durable and idempotent. A missing or unrecognized decision
leaves the question open for a corrected staff reply. No model output may publish directly.

---

# 49. Public FAQ

Table:

```text
faq_entries
────────────────────────────
id
question
answer
source_question_id nullable
published_by_user_id
created_at
updated_at
active
```

Expose via:

```text
course://faq
course://faq/{id}
```

and index via:

```text
course.search
```

This allows the Course Agent to become more useful throughout the semester.

Publishing also creates an unread course notification for every authenticated student. Read state
is per user; the published FAQ remains global course knowledge after notifications are dismissed.

Keep staff-approved evolving FAQ knowledge in one versioned local JSON file at
`var/course-knowledge/published-faq.json`. An authorized `PUBLISH` decision updates this file
automatically and atomically. The Course Agent reads it only through `course://faq`; model-controlled
input never receives or selects the backing path. The file contains no student identity, private
context, staff identity, provider metadata, or notification-read state. PostgreSQL retains the
workflow, idempotency, and notification bookkeeping needed to complete publication safely.

---

# 50. Agent Bridge

The Bridge is optional.

Users should never be told to install it until a task needs local capabilities.

User-facing term:

```text
Agent Bridge
```

Not:

```text
daemon
```

The Bridge should eventually install as a simple application.

Initial developer prototype may run as:

```bash
uv run class-agent-bridge
```

Later package it into a macOS app.

---

# 51. Bridge responsibilities

The Bridge provides:

```text
local SQLite history
filesystem access
process execution
local application adapters
local models
sensor access
physical-device adapters
local capability registry
local permission enforcement
server connection
```

The Bridge imports the same:

```text
agent_core
```

package as the server.

---

# 52. Bridge local data

Suggested location on macOS:

```text
~/Library/Application Support/ClassAgent/
```

Contents:

```text
agent.db
config.json
cache/
logs/
exports/
```

Do not move or duplicate users' personal files into this directory.

The Bridge only receives scoped access to them.

---

# 53. Local SQLite schema

At least:

```text
events
memories
permissions
nodes
settings
sync_state
```

Use WAL mode.

Persist raw detailed local tool events locally when appropriate.

---

# 54. Local filesystem permissions

A user should explicitly approve directories.

Example:

```text
~/Downloads
```

Permission:

```json
{
  "capability": "filesystem.read",
  "scope": {
    "paths": [
      "/Users/alice/Downloads"
    ]
  }
}
```

Separate:

```text
filesystem.read
filesystem.write
```

permission.

---

# 55. Capability acquisition

Capabilities may have statuses:

```text
available
obtainable
unavailable
```

Example without Bridge:

```json
{
  "id": "filesystem.read",
  "status": "obtainable",
  "acquisition": {
    "type": "install_bridge"
  }
}
```

Example with Bridge but no folder permission:

```json
{
  "id": "filesystem.read",
  "status": "obtainable",
  "acquisition": {
    "type": "grant_permission"
  }
}
```

---

# 56. Capability request flow

User:

> Organize my Downloads folder.

Agent determines:

```text
filesystem.read
filesystem.write
```

are required.

Platform sees Bridge absent.

Agent emits semantic request:

```text
capability.requested
filesystem.write
```

Frontend renders trusted installation card:

```text
Local access is required.

[Enable local access]
```

The model does not construct the installer URL.

After install/pairing:

```text
filesystem.read = obtainable
filesystem.write = obtainable
```

User grants Downloads access.

Then:

```text
filesystem.read = available
filesystem.write = available
```

Agent continues previous task automatically.

---

# 57. Tool risk levels

Classify actions:

```text
read
write
execute
external_effect
```

Examples:

```text
filesystem.list        read
filesystem.read        read

filesystem.move        write
filesystem.rename      write

computer.run_process   execute

course.ask_ta          external_effect
```

---

# 58. Confirmation versus permission

Do not conflate:

```text
permission
```

with:

```text
confirmation
```

Example:

User may grant:

```text
filesystem.write ~/Downloads
```

but bulk-moving 300 files can still require:

> Proposed changes:

> 120 files → Documents
> 80 files → Images
> ...

> **[Apply changes]**

This is preferable to silently performing large destructive changes.

---

# 59. Browser extension

Browser functionality must remain optional.

Use:

```text
TypeScript
Chrome Manifest V3
```

Initial capabilities:

```text
browser.current_page
browser.get_selection
browser.get_tabs
browser.get_page_text
browser.get_dom_snapshot

browser.highlight
browser.inject_ui

browser.click
browser.type
browser.navigate
```

Add read-only capabilities before action capabilities.

---

# 60. Extension-only mode

The browser extension must be able to work without Agent Bridge.

Architecture:

```text
extension
   ↓ HTTPS authenticated device channel
Media Lab server
   ↓
Course Agent
```

If Agent Bridge is also installed, richer local coordination may occur.

---

# 61. Browser security

Do not expose arbitrary generated JavaScript execution by default.

Prefer semantic tools:

```text
browser.click(selector)
browser.type(selector, text)
browser.highlight(anchor)
browser.navigate(url)
```

Any raw-script experimental capability must be clearly separated and disabled in production by default.

---

# 62. Nodes

Represent runtime endpoints as Nodes.

```python
class Node(BaseModel):
    id: UUID
    user_id: UUID | None

    type: Literal[
        "web",
        "browser_extension",
        "local_bridge",
        "raspberry_pi",
        "device"
    ]

    name: str

    capabilities: list[str]

    online: bool

    last_seen_at: datetime
```

Examples:

```text
Alice MacBook
Alice Chrome
Dorm Room Pi
```

---

# 63. Device pairing

Do not make Bridge or extension store a student's username/access code.

Use pairing.

Flow:

```text
Website:
[Connect Agent Bridge]
        ↓
Server issues short-lived pairing token
        ↓
Bridge receives token through deep link / local handshake
        ↓
Bridge exchanges it for device credential
        ↓
Device registered
```

Device credentials must be independently revocable.

Provide UI:

```text
Connected devices

Alice's MacBook          [Disconnect]
Chrome                   [Disconnect]
Raspberry Pi             [Disconnect]
```

---

# 64. Internal device transport

MCP should be the **agent capability abstraction**.

However, do not contort every browser-extension transport into a literal standalone HTTP MCP server if that makes implementation brittle.

It is acceptable to use an internal protocol such as:

```text
NodeRPC
```

between:

```text
server ↔ extension
server ↔ bridge
```

as long as the agent-facing capability is represented as MCP tools/resources.

This distinction is intentional.

---

# 65. Node tool execution

Example:

Agent calls:

```text
filesystem.list
```

Gateway resolves provider:

```text
Alice MacBook / Bridge node
```

Server sends internal execution request.

Bridge validates local permission again.

Bridge executes.

Bridge returns result.

Gateway converts it to MCP tool result.

Agent continues.

Both server and node should treat authorization defensively.

---

# 66. MCP Apps host

Implement MCP Apps support in:

```text
packages/mcp-app-host/
```

Use official packages where appropriate.

The React Course Agent application acts as an MCP Apps host.

Support:

```text
ui://...
```

resources.

Render third-party/student MCP Apps sandboxed.

---

# 67. Course UI versus MCP Apps

Use this rule.

## Native component

Use native `packages/ui` component when:

* part of core course UX;
* trusted;
* reused frequently;
* deeply integrated into workspace;
* needs consistent styling.

Examples:

```text
VisualComposition
Calendar
DataTable
CourseSchedule
PermissionCard
```

## MCP App

Use MCP App when:

* created by a student;
* distributed with a tool;
* external;
* complex tool-specific visualization;
* should be portable to other MCP hosts.

---

# 68. Public website default experience

A completely new visitor should be able to:

1. open site;
2. ask Course Agent questions;
3. access public syllabus/schedule/FAQ;
4. see dynamic workspace components;
5. use public tools;
6. never install anything.

Header can offer:

```text
Log in
```

but must not block basic use.

---

# 69. Student experience

Student logs in once using:

```text
username
access code
```

Then sees:

```text
Course Agent

My conversations
My course information
My connected devices
My activity
```

The Course Agent can now access:

```text
personal history
personal memories
student-only tools
grades
TA support
connected device capabilities
```

---

# 70. Course repository overview

Maintain:

```text
course://repositories
```

Machine-readable example:

```json
[
  {
    "student": "Alice",
    "project": "Socratic Browser",
    "repository": "https://...",
    "description": "..."
  }
]
```

Provide matching human-readable Markdown.

The overview can be updated manually initially.

Later automated GitHub synchronization may be added separately.

---

# 71. Shared tool registry

Create a public registry file:

```text
shared/registry/tools.json
```

Example:

```json
{
  "schema_version": 1,
  "tools": [
    {
      "id": "course.search",
      "provider": "course"
    }
  ]
}
```

Eventually student-released MCP servers/tools can be registered here.

---

# 72. Course resource registry

Create:

```text
shared/registry/resources.json
```

Example:

```json
{
  "resources": [
    {
      "uri": "course://syllabus",
      "title": "Course Syllabus"
    },
    {
      "uri": "course://schedule",
      "title": "Course Schedule"
    }
  ]
}
```

---

# 73. FastAPI backend

Suggested routes:

```text
GET  /api/v1/health

POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me

GET  /api/v1/conversations
POST /api/v1/conversations
GET  /api/v1/conversations/{id}

POST /api/v1/agent/run
GET  /api/v1/agent/capabilities

GET  /api/v1/memories

GET  /api/v1/nodes
POST /api/v1/nodes/pair
DELETE /api/v1/nodes/{id}

GET  /api/v1/course/resources

GET  /api/v1/ta/questions
POST /api/v1/ta/questions/{id}/publish

GET  /api/v1/admin/users
```

Exact routing can evolve.

---

# 74. Streaming agent output

Support streaming agent responses.

Use:

```text
Server-Sent Events
```

or an equivalent simple HTTP streaming mechanism where sufficient.

Do not introduce persistent WebSockets merely because agents exist.

The latest MCP architecture is increasingly HTTP/stateless; follow ordinary HTTP patterns where they work.

Device channels may use persistent connections if needed for real-time execution.

---

# 75. Workspace events

Agent execution stream should be able to carry typed events such as:

```json
{
  "type": "agent.text.delta",
  "text": "..."
}
```

```json
{
  "type": "workspace.command",
  "command": {
    "type": "open",
    "component": "calendar",
    "props": {}
  }
}
```

```json
{
  "type": "tool.started",
  "tool": "course.search"
}
```

```json
{
  "type": "capability.request",
  "capability": "filesystem.read"
}
```

Frontend renders each appropriately.

---

# 76. Workspace command validation

Every workspace command must be schema validated.

Unknown component:

```text
reject
```

Invalid props:

```text
reject
```

Unsupported operation:

```text
reject
```

The agent must not be able to crash the application by inventing arbitrary UI structure.

---

# 77. User-editable UI state

User interactions with workspace components should produce events.

Example:

User clicks date.

```text
workspace.interaction
```

The agent may use this in subsequent reasoning.

MCP Apps interactions similarly communicate back through their standard host bridge.

---

# 78. Local persistence/export

Agent Bridge should eventually support:

```text
Export local agent data
```

Portable archive:

```text
class-agent-export.zip
│
├── manifest.json
├── local.sqlite
├── memories.jsonl
└── attachments/
```

Use open formats.

Avoid opaque serialization.

---

# 79. Longevity requirements

Persisted state should favor:

```text
PostgreSQL dumps
SQLite
JSON
JSONL
Markdown
PDF
standard images/audio/video
```

Avoid critical reliance on:

```text
pickle
opaque SaaS export
framework-specific serialized state
```

The system should be reconstructable years later.

---

# 80. Media Lab deployment

Target a very boring infrastructure stack.

Ask NeCSys for roughly:

```text
agents.media.mit.edu

Linux host/VM
persistent application directory
persistent shared storage
PostgreSQL
HTTPS/reverse proxy
backup support
```

Deployment:

```text
reverse proxy
    │
    ├── /                  static Vite build
    ├── /shared/           public shared files
    └── /api/              FastAPI
```

---

# 81. Docker Compose reference deployment

Use Docker Compose where NeCSys permits.

Services:

```text
api
mail-worker
postgres
```

Potentially:

```text
nginx
```

if NeCSys does not already handle reverse proxy/TLS.

Do not introduce Kubernetes.

---

# 82. Separate email worker

Do not run polling logic as a background thread inside every FastAPI worker.

Create dedicated process:

```text
mail-worker
```

Responsibilities:

```text
retrieve TA replies
parse message threading
write database records
send student notifications
```

This prevents duplicate handling when API replicas increase.

---

# 83. Database backups

Provide documented commands for:

```text
pg_dump
pg_restore
```

NeCSys backups should cover:

```text
PostgreSQL
shared course storage
```

Keep schema migrations in Git permanently.

---

# 84. Privacy defaults

Never automatically upload:

```text
entire Downloads directory
raw document collection
complete browser history
microphone recordings
camera recordings
local credentials
```

A tool may send necessary excerpts/results to the model when the user intentionally invokes a task.

Record high-level server-side metadata rather than sensitive raw local content where practical.

---

# 85. Event redaction

Tool results should support:

```text
storage_policy
```

Example:

```text
server_full
server_summary
local_only
ephemeral
```

Filesystem reads should normally be:

```text
local_only or server_summary
```

unless document content must be sent to the model for the requested operation.

---

# 86. Logging

Separate:

```text
application logs
```

from:

```text
agent history
```

Never dump entire prompts or private local file contents into ordinary server logs.

Production logs should prioritize:

```text
request IDs
errors
latency
tool IDs
status codes
```

not sensitive payloads.

---

# 87. Security: model is untrusted

Treat LLM outputs as untrusted instructions.

The model may request:

```text
tool
resource
UI component
capability
```

but must not determine:

```text
authentication
authorization
folder scope
credential validity
installer URL
database ownership
```

These belong to platform code.

---

# 88. Secrets

Server API keys:

```text
environment variables / server secret store
```

Never expose them to:

```text
browser bundle
browser extension
public shared files
event payloads
student repositories
```

Local personal keys may later be stored using OS secure keychain mechanisms.

---

# 89. Code execution

Do not permit arbitrary student/model-generated Python to execute inside the production API process.

If CodeAgent is used:

```text
sandbox it
```

Potential implementations later:

```text
Docker sandbox
E2B
another isolated executor
```

The default production Course Agent remains ToolCallingAgent.

---

# 90. Admin UI

A minimal instructor/admin panel should eventually support:

```text
users
reset access code
deactivate user

course resources
FAQ entries

TA questions

connected-node metadata

service status
```

Do not make grades generally visible to admin roles unless intended.

---

# 91. Capability inspector

Build this early.

Example:

```text
Capabilities
────────────────────────────────

Course
✓ syllabus
✓ schedule
✓ FAQ

Browser
○ not connected
[Enable]

Computer
○ not connected
[Enable]

Devices
0 connected
[Add device]
```

For a Bridge user:

```text
Computer
✓ Agent Bridge

✓ Downloads — read
✓ Downloads — write
○ Terminal
```

This is both user-facing and useful for teaching.

---

# 92. Developer inspector

Provide optional developer mode showing:

```text
current PrincipalContext

available MCP tools

available MCP resources

active skills

connected nodes

workspace state

recent events

model/tool timing
```

Do not show hidden secrets.

This will be extremely useful for student debugging.

---

# 93. Event inspector

Example:

```text
16:12 user.message

16:12 resource.read
      course://schedule

16:12 workspace.panel.opened
      calendar

16:12 agent.message
```

For local task:

```text
16:18 capability.requested
      filesystem.read

16:19 node.connected
      Alice MacBook

16:19 permission.granted
      ~/Downloads

16:19 agent.tool.requested
      filesystem.list

16:19 agent.tool.completed

16:20 agent.message
```

---

# 94. Testing strategy

Use:

```text
pytest
```

for Python.

Use:

```text
Vitest
React Testing Library
```

for TypeScript/React.

Use browser end-to-end tests using:

```text
Playwright
```

for core flows.

---

# 95. Core contract tests

At minimum test:

```text
Event serialization roundtrip

PrincipalContext public/student/TA behavior

anonymous isolation

student history isolation

student tool filtering

TA tool filtering

grades.get_mine cannot access other users

MCP catalog authorization

workspace schema validation

SQLite event storage

Postgres event storage

access-code hashing

session revocation
```

---

# 96. Integration test: public agent

Automated flow:

1. open website;
2. no authentication;
3. ask about syllabus;
4. Course Agent reads public resource;
5. answer appears;
6. conversation assigned anonymous session;
7. privileged tools absent.

---

# 97. Integration test: student login

1. create test student;
2. login using username/code;
3. receive session;
4. `/auth/me` identifies correct user;
5. student tools appear;
6. TA tools remain absent;
7. conversation history is user-specific.

---

# 98. Integration test: grade privacy

Create:

```text
Alice grade = 90
Bob grade = 40
```

Login Alice.

Call:

```text
grades.get_mine
```

Must return:

```text
90
```

There must be no model-callable path allowing Alice to specify Bob's identity.

---

# 99. Integration test: dynamic UI

User:

> Show me the schedule.

Expected:

1. Course Agent reads schedule resource;
2. calls workspace calendar component;
3. calendar appears;
4. relevant date can be focused;
5. UI action recorded as event.

---

# 100. Integration test: Agent Bridge

User:

> What files are in Downloads?

Without Bridge:

```text
capability request
```

Install/register mock Bridge.

Grant:

```text
filesystem.read("~/Downloads")
```

Agent continues.

Mock files returned.

Response shown.

No local file contents persisted to public/shared course storage.

---

# 101. Integration test: TA workflow

Student asks:

> Can I use a local model for Assignment 3?

Agent cannot find answer.

Agent offers:

```text
Ask a TA?
```

Student agrees.

Expected:

1. `course.ask_ta`;
2. DB question created;
3. email generated;
4. mock inbound TA reply processed;
5. private answer attached to student's conversation;
6. email sent to student;
7. answer not public by default;
8. TA includes `PUBLISH` or `PRIVATE` in the first answer;
9. after `PUBLISH`, the next public query can retrieve the FAQ.

---

# 102. CI

CI should run:

```text
Python lint
Python type checking
Python tests

TypeScript lint
TypeScript type checking
React tests

schema validation

integration tests that don't require external services
```

External model tests should be mocked by default.

---

# 103. Local development

One developer command should start most of the system.

Target:

```bash
docker compose up -d postgres
pnpm dev
uv run course-server
```

Better later:

```bash
make dev
```

or:

```bash
./scripts/dev
```

Document clearly.

---

# 104. Seed development users

Development database may seed:

```text
public
alice / student
tom / ta
prof / instructor
```

Use obviously fake development credentials.

Never commit production access-code hashes or real student data.

---

# 105. Initial course resources

Seed:

```text
sample syllabus
sample schedule
sample repositories overview
sample FAQ
```

Provide documented process for replacing them with real course files.

---

# 106. Initial native UI components

Implement only these first:

```text
Chat
Calendar
DocumentViewer
VisualComposition
WebpageViewer
DataTable
CapabilityRequestCard
PermissionRequestCard
ToolActivityIndicator
DeveloperEventInspector
```

Do not build ten speculative visualizations before basic architecture works.

---

# 107. DocumentViewer and VisualComposition v1

DocumentViewer must support:

```text
specific Markdown, text, and PDF artifacts
page or section navigation
find within the artifact
semantic highlighting for focused discussion
```

It must not be selected merely because knowledge was sourced from a document.

VisualComposition must support:

Must support:

```text
groups
headings and text
facts and links
images
bounded bar, line, and area charts with accessible data
bounded editable fields
```

Functions:

```text
open composition
update composition
validate a single-parent element tree
reject arbitrary HTML, CSS, and JavaScript
```

---

# 108. Calendar v1

Input should be normalized calendar JSON.

Example:

```json
{
  "events": [
    {
      "id": "assignment-3",
      "title": "Assignment 3 due",
      "start": "2026-10-08T23:59:00-04:00",
      "type": "deadline"
    }
  ]
}
```

It should support:

```text
month
agenda/list
focus date
selected event
```

---

# 109. Agent resource/UI relationship

Prefer this pattern:

```text
resource contains data
component displays data
tool controls action
```

Example:

```text
course://schedule
        │
        ▼
Calendar
```

Do not embed course schedule data permanently inside Calendar component code.

---

# 110. Future Raspberry Pi support

Not required for launch, but architecture must permit:

```text
class-agent-node
```

to register:

```text
camera.capture
speaker.play
gpio.write
sensor.read
```

The Pi is another Node.

Agent core should need no Pi-specific modification.

---

# 111. Future local models

Bridge architecture should eventually permit model capability:

```text
model.local.generate
```

or a ModelProvider implemented locally.

Do not require cloud inference at the data-schema level.

---

# 112. Future student experimentation

Students should be able to submit PRs that independently add:

```text
new MCP tool
new MCP resource
new Agent Skill
new React component
new MCP App
new memory strategy
new model adapter
new Node capability
new browser interaction
```

without rewriting core infrastructure.

---

# 113. Developer guides to produce

Create:

```text
docs/ADDING_A_TOOL.md
docs/ADDING_A_RESOURCE.md
docs/ADDING_A_SKILL.md
docs/ADDING_A_COMPONENT.md
docs/ADDING_AN_MCP_APP.md
docs/ADDING_A_NODE.md
docs/ADDING_A_MODEL_PROVIDER.md
```

Each guide should include one minimal working example.

---

# 114. Example student contribution: native component

Example:

```text
ArgumentMap
```

Student adds:

```text
packages/ui/src/ArgumentMap/
```

and manifest:

```json
{
  "id": "argument-map",
  "title": "Argument Map",
  "description": "Visualizes claims, evidence, and counterarguments."
}
```

Workspace registry automatically makes it discoverable.

---

# 115. Example student contribution: MCP App

Student creates:

```text
mcp/student-visualizer/
```

Tool:

```text
visualize_reasoning
```

UI resource:

```text
ui://reasoning-map
```

Course Agent may call it.

React host renders it through MCP Apps sandbox.

No modification to trusted workspace code required.

---

# 116. Example student contribution: Skill

```text
skills/check-causal-reasoning/
    SKILL.md
```

Course Agent discovers metadata.

Runtime loads skill when relevant.

---

# 117. Example student contribution: Browser capability

Student adds:

```text
browser.detect_reading_regression
```

Extension implements handler.

Capability gateway exposes MCP tool only when extension version supports it.

No server agent rewrite required.

---

# 118. Deployment configuration

Environment variables might include:

```text
DATABASE_URL

MODEL_PROVIDER
MODEL_API_KEY

SESSION_SECRET

PUBLIC_BASE_URL

SHARED_DATA_PATH

MAIL_PROVIDER
MAIL_USERNAME
MAIL_PASSWORD
MAIL_HOST

ADMIN_BOOTSTRAP_USER
```

Never include secrets in `.env.example`.

Use placeholder values only.

---

# 119. Server resource requirements

Initial server workload is lightweight:

```text
FastAPI
MCP coordination
Postgres
document/search indexing
email worker
external model API calls
```

No GPU is required.

A modest Media Lab VM should be sufficient for approximately 20 enrolled students plus public visitors, depending mainly on concurrent request volume.

---

# 120. Search/indexing resource refresh

When course files change:

```text
shared/course/...
```

provide command:

```bash
python -m course_server.index_resources
```

It should:

1. scan resource manifests;
2. extract normalized text;
3. update metadata;
4. rebuild PostgreSQL full-text search index.

Do not require embeddings initially.

---

# 121. Course resource manifests

Each resource can optionally have:

```yaml
uri: course://syllabus
title: Course Syllabus
visibility: public

files:
  human: syllabus.pdf
  machine: syllabus.md
```

This keeps metadata near the files.

---

# 122. Error behavior

The Course Agent must never fake access.

If capability unavailable:

```text
request capability
```

If capability cannot be obtained:

```text
state limitation
```

If course information cannot be found:

```text
state that it is not documented
```

Authenticated students may be offered:

```text
Ask a TA
```

---

# 123. Do not expose internal failures as confusing agent messages

Tool failures should contain structured categories:

```text
permission_denied
capability_offline
resource_not_found
temporary_failure
invalid_request
```

Agent runtime receives useful error representation and can explain appropriately.

---

# 124. Explicit architecture boundaries

These modules should be particularly stable:

```text
PrincipalContext
Event
Capability
Permission
Node
AgentContext
AgentRuntime
WorkspaceCommand
ComponentManifest
```

Changing them should require:

```text
migration
tests
documentation
```

Student PRs should generally not change them casually.

---

# 125. Things NOT to build in v1

Do not implement:

```text
Kubernetes

distributed event streaming

Kafka

custom vector database

multi-agent social network

agent marketplace

full autonomous desktop computer use

complex federated learning

automatic model fine-tuning

arbitrary generated frontend code

automatic public sharing of student conversations

automatic ingestion of full local filesystem

full Canvas integration

GitHub OAuth

Touchstone

passkeys

complex enterprise authorization
```

unless specifically requested later.

---

# 126. Development phases

Implement in this order.

## Phase 1 — repository and core contracts

Create:

```text
monorepo
AGENTS.md
agent_core
tests
schemas
```

Implement:

```text
PrincipalContext
Event
Memory
Capability
Permission
Node
AgentContext
AgentInput
AgentResult
AgentRuntime
```

No UI/backend implementation yet beyond skeleton.

---

## Phase 2 — database + authentication

Implement:

```text
PostgreSQL migrations
users
access-code authentication
server sessions
anonymous sessions
```

Add contract/security tests.

---

## Phase 3 — minimal Course Agent runtime

Implement:

```text
smolagents adapter
model provider
one public tool
one public resource
conversation persistence
```

CLI test first.

---

## Phase 4 — FastAPI

Implement:

```text
login
logout
me
conversations
agent run
streaming output
```

---

## Phase 5 — React frontend

Implement:

```text
login
chat
workspace shell
conversation list
```

No fancy UI yet.

---

## Phase 6 — course resources

Implement:

```text
syllabus
schedule
repository overview
show_public_files
FAQ
course.search
something that allows them to register for the class with what they sent being stored in an applicant folder on the api side.
```

---

## Phase 7 — native workspace UI

Implement:

```text
component registry
WorkspaceState
workspace MCP tools
DocumentViewer
VisualComposition
Calendar
```

Validate dynamic UI flow.

---

## Phase 8 — MCP Apps support

Implement official MCP Apps host support.

Add one trivial example MCP App.

Confirm sandboxing.

---

## Phase 9 — user capabilities

Implement:

```text
student tool filter
TA tool filter
grades.get_mine mock implementation
memory.get_mine
```

Validate privacy.

---

## Phase 10 — Media Lab email

Implement:

```text
MailAdapter
course.ask_ta
mail worker
private TA reply
student notification
FAQ publishing
```

---

## Phase 11 — deploy to Media Lab

Deploy:

```text
static Vite build
FastAPI
PostgreSQL
shared filesystem
mail worker
```

Confirm backups.

---

## Phase 12 — Agent Bridge

Implement:

```text
local SQLite
pairing
filesystem.list
filesystem.read
permission model
capability acquisition
```

---

## Phase 13 — local writes

Add:

```text
mkdir
move
rename
```

Add proposed-action confirmation.

Test Downloads organization flow.

---

## Phase 14 — browser extension

Implement read-only:

```text
current page
selected text
tabs
page text
```

Then:

```text
highlight
injected UI
```

Then later:

```text
click
type
navigate
```

---

## Phase 15 — generalized device nodes

Add Raspberry Pi example.

---

# 127. Definition of v1 success

The first meaningful class-ready release is successful when:

```text
✓ Public visitor opens website with no install.

✓ Public visitor can ask syllabus/schedule questions.

✓ Agent can open DocumentViewer for specific artifacts, VisualComposition for synthesized knowledge, and Calendar for schedules during conversation.

✓ Student logs in with username/access code.

✓ Student gets persistent personal conversation history.

✓ Public users cannot access student tools.

✓ Student can use get_my_grades without specifying identity.

✓ Student can ask TA by email.

✓ TA reply returns privately to student.

✓ TA can explicitly publish sanitized answer to FAQ.

✓ FAQ becomes available to future users.

✓ MCP tools/resources are the capability boundary.

✓ Agent Skills use SKILL.md.

✓ MCP Apps render correctly.

✓ Student can add a new UI component via PR.

✓ Student can add a new MCP tool via PR.

✓ Agent Bridge can be installed only when needed.

✓ Agent Bridge can read an approved folder.

✓ Local filesystem contents are not automatically uploaded.

✓ Course Agent resumes task after permission installation.

✓ Media Lab server requires no GPU.

✓ Entire deployment can run from ordinary Linux + PostgreSQL + shared files.

✓ Persisted data is portable and not smolagents-specific.
```

---

# 128. First task for Codex

Do **not** implement this entire specification in a single coding pass.

The first Codex implementation task should be:

> Implement Phase 1 only.
>
> Create the monorepo structure and stable core contracts described in the architecture specification.
>
> Set up:
>
> * pnpm workspace;
> * Python project;
> * root `AGENTS.md`;
> * `python/agent_core`;
> * `packages/protocol`;
> * schema/versioning strategy;
> * automated tests.
>
> Implement:
>
> * `PrincipalContext`
> * `Event`
> * `Memory`
> * `Capability`
> * `Permission`
> * `Node`
> * `AgentContext`
> * `AgentInput`
> * `AgentResult`
> * `AgentRuntime`
>
> Add serialization and contract tests.
>
> Do not yet implement:
>
> * FastAPI;
> * React application logic;
> * smolagents;
> * PostgreSQL;
> * login;
> * MCP servers;
> * Agent Bridge;
> * browser extension.
>
> Before completing the task:
>
> 1. run all tests;
> 2. document the architecture decisions;
> 3. explain any deviations from this specification;
> 4. identify interfaces that should be treated as stable;
> 5. do not make speculative abstractions for features that have not yet been implemented.

After Phase 1 is reviewed, proceed sequentially.

---

# 129. Final instruction to coding agents

Optimize this project for **composability rather than cleverness**.

Students should eventually be able to understand:

```text
What does the agent know?
What tools does it have?
Why does it have them?
Where did this data come from?
Where will this action execute?
What permission authorized it?
What UI can it display?
Where is the history stored?
```

from explicit code and inspectable state.

If a framework makes those questions harder to answer, wrap or remove it.

The architecture should make radical student experiments possible while keeping identity, privacy, permissions, history, and interoperability stable.

That is the core objective.
