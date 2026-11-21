# Course-improvement loop (experimental)

A platform-owned loop in which the one Course Agent researches how students are doing
against the syllabus learning goals, proposes changes to itself or the course site, and
has those proposals replayed, critiqued, and ranked before anything is adopted. It was
added by explicit request outside the constitution's phase order and is **not wired into
the API or web app**: today it runs only from `examples/improvement_loop/demo.py`.

```text
        CHARTER  (learning goals · staff background · directions)
            │
ORIENT → PROPOSE → REPLAY or TRIAL → PANEL CRITIQUE ⇄ REVISE → RANK → GATE → human (critical only)
   └────── notebook: findings, withdrawals, human decisions and reasons ──────┘
```

## Charter and proposal shape

The loop is oriented, not scripted. A staff-maintained charter (the `improvement_charter`
asset of `course://syllabus`) states one overriding purpose (improve the experience of a
student using the Course Agent), a few broad directions, and the sources to read first;
it lists no features. The orientation (research) phase uses the ordinary read-only course
tools to work out where the course is on the brief's date: the week's topic and build,
the goal it serves, and how it leads to the final project. No week-to-goal table is
hand-authored.

To prevent sprawl, a proposal's shape is fixed while its content is open. Each proposal
is one small agentic experience:

- exactly one `goal_id` and one charter `direction`, and optionally a `course_week`;
- one flow in three short fields, `trigger`, `agent_action`, `student_action` (200
  characters each), so a feature needing a second flow must be a second proposal;
- `builds_on`, the existing experience or adopted feature it continues. The brief lists
  adopted features so new ones extend the same experience.

The single goal, single direction, and field bounds are enforced in code. Whether a
proposal is any good is the review panel's judgement.

## Data policy

Staff decision, 19 November 2026. A student's repository builds and commits are public
within the course. Chat logs, grades, feedback, and questions to staff are private.
Private data may inform a general feature; it must never be shown to other students.
The `privacy` rubric states this for critics. In code, the loop still receives no tool
that opens an individual private record (`LOOP_WITHHELD_TOOL_IDS`), and any proposal that
declares private data, names a course member, or changes the interface waits for a human.

## Trials: running a proposed skill

A skill's `SKILL.md` is its whole implementation, so the loop runs it before the panel
grades it. For each persona in the charter's `trial_personas` (staff-edited; with none,
skills are graded from their text as before):

1. The platform opens one trial conversation (`ImprovementService.open_trial`).
2. A second model run plays the student from the persona and the proposal's `trigger`. It
   has no tools and never sees the skill.
3. The Course Agent answers as a student run, with the candidate added to its skill index
   and `skills.read` as its only tool. Whether it loads the skill is its own choice, and the
   platform records it (`Trial.skill_loaded`).
4. After `trial_exchanges` exchanges (three by default, `LoopBudget`), the transcript is
   stored against the revision and shown to every critic in the brief.

Critics are told to grade what the agent did in the transcripts. A revision is a new
implementation, so it is tried again before the panel sees it. Earlier transcripts stay on
the proposal and appear in the report.

The candidate is model-authored and unapproved. `TrialSkillReadTool` serves it only when
the run's trusted conversation ID is the open trial's; every other call goes to the
registered catalog, so no student conversation can load it. Only kinds in
`policy.TRIALLED_KINDS` are tried. An interface mock-up is still judged as a picture.

Limits: the simulated student is the same model family as the agent and the critics; the
trial run has no course tools, so a skill that depends on reading the student's repository
is not exercised; and nothing here measures whether a real student would be helped.

## Interface mock-ups

An interface proposal is a suggestion for a person to build and merge; the loop writes no
site code. To make the suggestion complete enough to judge, its mock-up is a storyboard of
the whole interface, not one panel: exactly three screens, in order, marked
`data-step="trigger"`, `"agent"`, and `"student"`, matching the proposal's flow. Each shows
the conversation beside the workspace.

The platform supplies the stylesheet (`improvement/mockup_shell.css`), whose color tokens
a test keeps equal to `packages/ui/src/styles.css`. The brief gives the author and the
critics the same rules and stylesheet (`artifacts.MOCKUP_RULES`), and `review_file` wraps
the mock-up in it. Critics are told to walk the screens in order and not to ask for
anything the rules forbid, such as real links.

## Review panel

The charter lists the panel's lenses, each with a rubric: `evidence`, `privacy`, `scope`,
`usefulness`, and `learning`. Staff edit the rubrics in the charter file; the report prints
them. Review runs in rounds until it converges:

1. Every lens grades the current revision once, each in a fresh run that sees only its own
   rubric. The platform assigns the lens from recorded state (`policy.next_lens`); a critic
   cannot choose or claim one.
2. Each issue gets a citation, `r<revision>.<lens>.<n>`.
3. If any lens asked for a revision, the author must answer every open issue by citation:
   `resolved` with what changed, or `declined` with a reason and, when two issues pull in
   opposite directions, the `conflicts_with` issue it sided with. `ImprovementService.revise`
   refuses a revision that skips an issue.
4. The whole panel grades the new revision, seeing the earlier issues and the author's
   answers. A critic whose issue was declined is told to insist only if what remains should
   by itself stop adoption.

A proposal is eligible when every lens accepts the same revision. The `conflicts_with`
records are the evidence of competing rubrics; the report lists them under "Where critics
competed".

## Who decides what

| Decision | Owner |
| --- | --- |
| What to investigate, what to propose, critique verdicts, ranking order | Course Agent |
| Which phase runs next, which tools it receives, run budget | `improvement/loop.py` |
| Which lens grades next; when a proposal is eligible, withdrawn, or shelved | `improvement/policy.py` `next_lens`, `review_outcome` |
| Which kinds are tried, with which persona, and in which conversation a candidate may load | `improvement/policy.py` `TRIALLED_KINDS`, `next_trial_persona`; `ImprovementService.open_trial` |
| Which objection wins when two lenses conflict | Course Agent (author), recorded by citation |
| Whether a human must approve | `improvement/policy.py` `assess_proposal` |
| Approve, reject, retire | Instructor, through `ImprovementService.decide` / `retire` |

Every phase is a fresh `AgentRuntime.run` with no prior dialogue, so a critic never sees
the author's reasoning. `PHASE_WRITE_TOOL_IDS` gives each phase one kind of write; no tool
approves, rejects, or retires.

In the research, propose, critique, and revise phases the agent also chooses for itself
among the Course Agent's read tools and skills: every tool in the trusted allowlist
`LOOP_READ_TOOL_IDS` that `CourseCapabilityPolicy` authorizes for the instructor, plus the
instructor's authorized skills. `LOOP_WITHHELD_TOOL_IDS` names what the unattended loop
never receives and why: tools that send, submit, or publish; tools that open individual
private records (grades, roster, applicant files, student questions, a user's own
messages or uploads); and interactive workspace and browser tools that have no viewer in
a background run. A test requires every Course Agent tool to be in exactly one of the two
sets, so a new tool reaches the loop only by an explicit decision.

## Rules enforced in code

- Only instructors can run the loop, call its tools, or decide. Each tool rechecks this.
- A proposal must cite one registered learning goal, one charter direction, and signals
  in the current evidence, and state its flow and what it continues (see above).
- Each kind must attach its finished deliverable (`REQUIRED_ARTIFACT_FORMAT`): a static,
  full-screen HTML mock-up for `ui_feature` (see Interface mock-ups), a standard `SKILL.md` for `agent_skill`, and the exact
  Markdown for `course_content`. `agent_guidance` and `private_data_use` are fully stated
  by their body.
- A mock-up is refused if it contains a script, event handler, form or input, frame, a URL
  other than `#` or an id in the same mock-up, or a style that loads anything, or if it
  lacks one of its three screens (`artifacts.validate_artifact`). A skill
  must parse as a registered skill would. Deliverables are model-authored and untrusted:
  the site never renders a mock-up, and the Course Agent loads a proposed skill only
  inside a trial conversation (see Trials).
  `review_file` exports a mock-up inside a document whose Content Security Policy blocks
  all network and script access, for the reviewing instructor to open locally.
- At most four proposals can be in review at once.
- `agent_guidance` proposals are replayed against every scenario and withdrawn unless
  their mean score beats the baseline.
- A proposal becomes eligible when every lens accepts the same revision. Any `reject`
  withdraws it; so does a panel that still wants changes at the round limit (six revisions
  by default, `max_rounds` on the service, `--max-rounds` in the demo; never unbounded).
  A revision clears its replay scores and every lens's verdict.
- At the gate, only the `top_k` ranked proposals continue. `agent_guidance` is adopted by
  policy; `ui_feature`, `agent_skill`, `course_content`, and `private_data_use` always wait
  for a human, as does anything that declares private data, names a course member, or
  contains a contact detail, including inside its deliverable.
- Adopted guidance is added to student runs only, as a bounded instruction section, and
  an instructor can retire it. An approved `ui_feature`, `agent_skill`, or other critical
  proposal is a record for a reviewed code or content change; it changes nothing at
  runtime. A mock-up is a design reference, not code to ship: the real feature is built
  from registered components and tokens.
- Evidence signals must describe at least three students.
- A human decision may carry a short reason. The decision and reason are written to the
  notebook so later cycles, which start with no memory, learn from the gate.

## Data

- Charter: the `improvement_charter` asset of `course://syllabus`
  (`shared/course/syllabus/improvement-charter.json`). It is a public asset like the
  learning goals; if it should be staff-only it belongs in the protected resource
  manifest instead.
- Learning goals: the `learning_goals` asset of `course://syllabus`
  (`shared/course/syllabus/learning-goals.json`). A test keeps each statement identical
  to the syllabus text.
- Evidence and replay scenarios: validated `EvidenceDigest` and `ReplayScenarios`
  documents. Only synthetic fixtures exist. Nothing yet derives evidence from real
  conversations, feedback, or staff questions; that needs a privacy decision first.
- Loop state (`ImprovementState`) is in memory. Each phase run is stored as a conversation
  owned by the triggering instructor, beginning with `improvement.phase.requested`.

## Known gaps

- No API route, scheduler, durable store, or approval UI.
- The loop has had one exploratory live-model run; prompts and limits are untuned.
- Critics judge usefulness from the use case, the deliverable, and for skills simulated
  trials; no real student has tried one.
- The scripted demo proposes no skill, so trials run only with `--live`.
- Replay answers and scores come from the same model family as the proposals.
- Ranking is a single ordering run, not a pairwise tournament.
- Phase conversations would appear in the instructor's conversation list if wired in.

## Demo

```bash
uv run python examples/improvement_loop/demo.py --decision approve
```

All inputs are synthetic. The terminal shows a short summary; the full review is written
to `report.html` in `examples/improvement_loop/out/` (git-ignored) or the `--out`
directory, beside each deliverable. The report escapes all model text and shows a mock-up
only inside a script-less sandboxed frame, and it includes withdrawn and shelved proposals
with their review history. Every dossier is shown before any decision is
asked for, and an interactive run opens the report in the browser.

- No flag: a scripted model plays the LLM, so the run is offline and identical each time.
- `--live`: the configured OpenAI model makes every choice. Needs `OPENAI_API_KEY`
  (and optionally `MODEL_ID`) in the environment or `.env`.
- `--trace` prints each run's tool calls and answers; `--trace-file PATH` appends every
  run event as JSON lines.
- `--langfuse` exports full model traces over OpenTelemetry. Needs the `tracing`
  dependency group (`uv run --group tracing …`) and `LANGFUSE_PUBLIC_KEY`,
  `LANGFUSE_SECRET_KEY`, and optionally `LANGFUSE_BASE_URL` (or `LANGFUSE_HOST`). Each
  agent run is its own trace, named by phase and lens (for example `critique · privacy`)
  and sent when that run ends; a cycle's traces share the session ID the demo prints. A
  critique trace carries its rubric as input and metadata, and the recorded grade as a
  Langfuse score `critic.<lens>` (accept, revise or reject, with the issues as its
  comment). A replay trace carries its scenario rubric and a numeric `replay.<scenario>`
  score. The export includes prompts and tool results, so it exists only in
  this synthetic demo.
- `--real-projects` reads the course GitHub repositories through the Course Agent's own
  read-only reader (`GITHUB_TOKEN`) instead of the synthetic ones. It requires `--live` and
  `--evidence PATH`, a digest that describes the real cohort.
  `examples/improvement_loop/local/evidence.json` is one: aggregate counts only, with no
  student or repository names. Repository names are added to the
  privacy screen, so a proposal that names a student waits for a human.
- `--trial-exchanges N` sets how many student messages each simulated trial of a proposed
  skill contains. With `--langfuse`, trial runs are traces named `trial · <persona>` (the
  simulated student) and `trial · <persona> · agent` (the Course Agent's reply).
- Without `--decision`, the demo asks at the gate, and for an optional reason;
  `--reason` supplies one non-interactively.
- The demo registers the real course schedule, syllabus, public-file, and search tools,
  and runs on the real date. Its synthetic repositories and evidence
  (`projects.synthetic.json`, `evidence.synthetic.json`) describe a cohort in week 10 of
  the Fall 2026 schedule, with weekly builds and week 8 final-project proposals.
