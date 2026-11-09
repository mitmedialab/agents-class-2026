# Weekly dream — local review copy

Weekly dream feature branch for Brooke’s course-agent fork. Email delivery remains disabled.

## Goal

A private weekly lookahead (inspired by OpenAI's 'Pulse' feature) connects this week's course materials with a student's interests and past projects. It gives each student a personalized lookahead for the week, including specific topics and readings that will interest them plus any connections to other students, or questions they should consider. It works by remembering suggestions and explicit student feedback and engagement.
## Start reading here

- `class-agent/python/course_server/weekly_dreams.py`: schemas, student ownership,
  evidence validation, private storage, feedback, and tools.
- `class-agent/skills/weekly-dream/SKILL.md`: the generation instructions you can edit.
- `class-agent/python/course_server/dream_preview.py`: local Brooke review harness.
- `class-agent/docs/WEEKLY_DREAM.md`: integration and limitations, not your assignment reflection.

## Local preview

From `class-agent/`:

```sh
.venv/bin/python -m course_server.dream_preview
```

Open http://127.0.0.1:8767. The preview has a fixed local test identity representing
Brooke, not a production login. Example outputs are explicitly labeled fixtures;
they are not evidence of a successful live model call.

## Review control

Use VS Code's Source Control view or `git diff` to inspect every change. The feature
extends the existing runtime rather than defining a separate student agent. No automatic
email, scheduler, new public sharing, or new stable `agent_core` contract is introduced.
Do not add credentials or real private roster data to this repository.

## Review checkpoint — November 8

The student-facing preview is a single short, curated email. Feedback and source
explanations are optional; development controls are folded away. The generation
Skill now explicitly uses a Pulse-inspired approach: bring a relevant connection
to the student proactively, rather than assign a checklist of work.

Review these in order:

1. `class-agent/examples/weekly-dream/preview.html` — what the student sees.
2. `class-agent/examples/weekly-dream/brooke.json` — editable, clearly labeled samples.
3. `class-agent/skills/weekly-dream/SKILL.md` — live generation instructions.
4. `class-agent/python/course_server/weekly_dreams.py` — private memory and validation.
5. `class-agent/docs/WEEKLY_DREAM.md` — integration details and remaining limitations.

Working locally: source preparation, private memory, explicit feedback, validation,
short email rendering, and a scripted follow-up demonstrating remembered feedback.
The preview also has an optional real-runtime generation path, but a live provider
call has not been verified. Automatic email delivery is not wired. Brooke confirmed
that the weekly class email comes from the Course Agent; its sending path must be
identified before connecting a successful-send trigger.

The student outcome evaluation is the next work item;
the automated tests check software behavior, not whether students learn more.
