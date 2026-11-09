# Learning trail

The Course Agent as a study coach with a memory the student owns. A student keeps one reflection per
weekly build, tagged with the course topics it practiced. Staff feedback reaches an entry in two
ways: a TA or instructor writes it on an entry the student shared, or the student pastes it from an
email. The Course Agent reads those entries on every run, so that help with a later assignment can
build on earlier weeks and say where it got that from.

What the original agent could not do, and this adds:

- **Debrief.** The agent interviews the student about a build in three short questions, then
  proposes an entry in the student's words with `memory.propose_mine`. The draft waits in
  **My builds** until the student edits and saves it, or discards it. The agent never writes an entry.
- **Skills map.** An open learner model: course topics (slide decks and readings) down the side,
  builds across the top. The platform tells the agent which topics the student's builds have
  practiced and which none has touched, so it can suggest where a new assignment could stretch.
- **Pre-brief.** The page greeting connects a pending assignment to something the student wrote
  down earlier, such as a plan or feedback they have not acted on.
- **Check what stuck.** Retrieval practice on an earlier build: the agent asks one question, waits,
  then compares the answer with the student's note and staff feedback.
- **Connections.** How each build relates to the student's other builds, class materials, and
  classmates who chose to share.

Status: initial version. `make check` passes. Scope and open questions are at the end.

## How it fits together

```mermaid
flowchart LR
    S[Student] -->|writes, edits, deletes, shares| P[LearningTrail panel<br/>apps/web + packages/ui]
    C[TA or instructor] -->|reads shared entries, writes feedback| P
    P -->|/api/v1/learning-trail| R[routes.py]
    R --> V[service.py<br/>owner comes from the session]
    V --> F[(store.py<br/>var/learning-trail/&lt;user_id&gt;.json)]

    V -->|select_memories| T[retrieval.py<br/>relevant, newest first, bounded]
    T -->|AgentContext.selected_memories| A[Course Agent<br/>runtime prompt + learning-trail skill]
    A -->|memory.get_mine, read-only| G[tools.py]
    G --> V
    A -->|opens component| P
```

Two paths reach the agent. On every run, `CourseAgentService` fills the existing
`AgentContext.selected_memories` slot, and the runtime prompt presents those as student-written data.
For anything more, such as a truncated entry or one the student set aside, the agent calls
`memory.get_mine`. The stable `Memory` contract is unchanged: an entry maps onto it with
`kind = "learning_trail.reflection"`.

## Where to change what

| To change | Edit | Depends on |
| --- | --- | --- |
| Data and memory logic | `models.py`, `store.py`, `service.py`, `retrieval.py` | `TrailStore` protocol; `select_trail_memories` |
| Topics, coverage, drafts | `service.py` (`topics`, `coverage`, `propose`, `accept_draft`), `FileDraftStore` in `store.py`, `MemoryProposeMineTool` in `tools.py` | Course slides and readings in the resource catalog |
| The panels | `packages/ui/src/LearningTrail.tsx`, `apps/web/src/LearningTrailPanel.tsx`, `apps/web/src/api.ts`, `routes.py` | The JSON shape of `TrailEntry` |
| Connections | `connections.py`, the map and list in `LearningTrail.tsx` | `TrailConnection` |
| What the agent says | `skills/learning-trail/SKILL.md`, `tools.py`, the memory section of `_agent_instructions` in `python/runtime_smolagents/runtime.py` | `Memory.metadata` fields; the `memory.get_mine` result |

Handy starting points:

- To change which entries the agent sees, edit `retrieval.py`. It is pure and needs no server.
- To change how the agent cites and connects them, edit the skill. No code change is needed.
- To move storage to SQLite or PostgreSQL, write another `TrailStore`. Nothing else should change.

## Data ownership

**Whose data.** The student's. Reflections are their own words, and the agent cannot write them.
Feedback a TA or instructor wrote stays theirs in the sense that its author and role are recorded.

**Where it comes from.**

- The student types reflections.
- A TA or instructor writes feedback on an entry the student shared. It is stored as
  `source: "staff"`, with the author and role taken from their session, so it cannot be forged.
- The student can also paste feedback from an email. That is stored as
  `source: "pasted_by_student"` because the platform cannot verify who wrote it, and both the panel
  and the agent describe it that way.

**Who can read it.**

- The student, through the panel.
- TAs and instructors, for the entries that student shared. Sharing is a per-entry choice that is
  visible on the form and can be turned off later, which ends staff access to that entry at once.
  An entry left unshared never appears to staff, and staff cannot tell that it exists.
- The Course Agent, during that student's own runs. Selected text goes to the configured model
  provider as part of the prompt. No agent tool reads another student's trail, including for staff.
- Classmates, for the entries that student marked **Classmates can see this**. This is a separate
  per-entry choice, and it is off by default. A classmate sees the student's name, the build title
  and link, and a short excerpt, and only as a connection from one of their own builds. They never
  see feedback, and the agent never receives a classmate's text.
- Anyone with file access to the server can read the files. They are not encrypted at rest.

**Agent-drafted entries.** A debrief ends with `memory.propose_mine`, which stores one pending
draft per student in a separate file. It is not an entry, is not read by `select_memories`, and
is replaced by the next proposal. Only the student turns it into an entry, after editing it in the
panel, or discards it. The agent cannot save, edit, or delete entries.

**Who can change it.**

- The student can change or delete their own entries, and delete feedback they pasted.
- A TA or instructor can add feedback to a shared entry, and remove staff-written feedback from it.
  They cannot edit a reflection or remove what the student pasted.
- A student cannot delete staff-written feedback on its own. They can stop sharing, or delete the
  whole entry, because the entry is theirs.

Every student method resolves the owner from the trusted `PrincipalContext`, so neither a client nor
the model can name another student. Staff methods take a student ID from the route, but check the
role from the session and return only shared entries. Admin and anonymous principals have no access.

**Deletion.** Deleting removes the entry from the file and from future prompts. An earlier agent
reply that quoted it stays in that conversation's history, like any other message.

## Decision ownership

- **Course Agent:** whether an entry bears on the current question, how to connect entries, when to
  open the panel.
- **Platform code:** identity, ownership, role filtering, validation, bounds, and which entries are
  selected. None of this depends on a prompt.
- **Student:** the words, the relevance mark, which removes an entry from automatic context, and
  whether staff and classmates can see each entry.
- **TA or instructor:** the feedback they write.
- **Bounds:** the constants in `models.py` and `retrieval.py` are safety and context limits, sized so
  a full course of roughly one entry per week fits.

## Running it

Follow the setup in [`class-agent/README.md`](../../../README.md), then:

```bash
uv sync
pnpm install
docker-compose up -d postgres
cp -n .env.example .env                  # add your own OPENAI_API_KEY; never commit .env
uv run python -m course_server.migrations apply
uv run python -m course_server.index_resources
uv run python -m course_server.admin create-user --help   # create a local student account
uv run python -m course_server.api       # terminal 1
pnpm dev                                 # terminal 2, http://localhost:5173
```

No migration is needed for this feature, and entries appear under `var/learning-trail/`. Log in as
the student and click **My builds** in the header, which opens the page at once with no agent run, or
ask the agent to open your learning trail. To see citations, save two or three builds, then press
**Ask the agent about my next build**. Staff see the same button as **Student builds**.

Run the feature's tests:

```bash
uv run pytest python/tests/test_learning_trail.py
pnpm --filter @class-agent/web exec vitest run src/LearningTrailPanel.test.tsx
```

Run `make check` before opening a pull request. The new component changes the registry, so its
contract tests must pass.

## Scope of this version

Included: reflections per build, feedback written by staff or pasted by the student, per-entry
sharing with staff and with classmates, the relevance mark, automatic context and citation, a page
listing the weeks with a map of connections and buttons that ask the agent, plus a staff view of
shared entries.

Not included yet:

- **Connections by meaning.** See the first known limit.
- **Saving from chat.** The constitution also names `memory.save_mine`. It is left out so that the
  agent cannot write in a student's voice; a confirmation step like the email one could add it.
- **Course MCP.** External AI apps connected through the Course MCP do not see the trail.

Known limits:

- Connections compare words with TF-IDF cosine similarity in pure Python, so they need no model or
  embedding provider. Two builds about the same idea in different words rank low, and the order says
  how much the wording overlaps, not how related the ideas are. Chinese is compared by character
  pairs. Embeddings would do better and would add a provider and a cost.
- On a narrow screen the connections panel sits below the list of weeks.
- `FileTrailStore` serializes writes with an in-process lock, which suits the single API process
  in `deploy/`. Several API workers would need a different store.
- Up to 16,000 characters of entries are added to each run for students who have saved many, which
  adds model cost.
- The `students` skill audience also includes instructors, who see the skill but have no trail of
  their own.

This feature does not change a stable contract. `memory.get_mine` comes from Phase 9 of the
constitution, ahead of the repository's current Phase 7. The Week 8 project asks for it directly, so
this is a deliberate deviation that a pull request should state.

## Technical notes for the writeup

A draft of the technical parts only. The reflection and evaluation prose are for the team to write.

**Encode.** A reflection is structured when it is saved: week, build title, optional HTTPS link, the
student's text, feedback with its source, the relevance mark, and whether it is shared.
`retrieval.py` turns each entry into a `Memory` of kind `learning_trail.reflection`.

**Store.** One validated JSON file per student, replaced atomically. See `store.py`.

**Retrieve.** On every run for a logged-in student, `CourseAgentService` calls `select_memories`,
which takes entries still marked relevant, newest week first, up to 16 entries and 16,000 characters.
The runtime prompt presents them as student-written data rather than instructions. The agent calls
`memory.get_mine` when it needs a truncated entry or one the student set aside.

**Observation space added by this feature.** The selected trail memories in `AgentContext`
(each with its topics), the `memory_overview` metadata naming topics practiced and not yet
practiced, the `memory.get_mine` result, the `memory.propose_mine` result, and the
`learning-trail` component in the workspace.

**Tools and actions added by this feature.**

| Tool | Who | Effect |
| --- | --- | --- |
| `memory.get_mine` | Logged-in student's run | Reads their own trail. Read-only. |
| `memory.propose_mine` | Logged-in student's run | Parks one draft for the student to review in the panel. Saves nothing. |
| `workspace.open_component` with `learning-trail` | Agent, existing tool | Opens the panel. Carries at most an entry ID. |

Saving, sharing, and writing feedback happen only through the panel and its API, not through the
agent.

## Demo script

One interaction in which saved information changes a later reply:

1. Log in as a student and ask for help planning a later assignment. Note the generic reply.
2. Open **My builds** and save a build for an earlier week, such as what broke in a build and what
   you would do differently.
3. As a TA, open **Student builds**, select the student, and write feedback on that entry.
4. Back as the student, start a new conversation and ask the same question. The reply should name the
   earlier build and the TA's feedback, and say where each came from.
5. Untick **Agent can use this** on that build and ask again. The reply should stop relying on it.

To try the debrief, press **Debrief this week with the agent**, answer its three questions, and
open **My builds**: the draft is at the top, with the topics it suggested ticked. Change it and
save, or discard it. Press **Check what stuck** on an earlier build for a one-question quiz.

To see connections, save two or more builds and open **My builds**. Select a build, then expand a row
in the list. A second student who ticks **Classmates can see this** on a build appears on the map as
a diamond.
