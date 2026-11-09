# Weekly dream implementation notes

This opt-in feature extends the existing Course Agent. `WEEKLY_DREAM_ENABLED=true`
enables the private tools and automatic student-profile projection. Default: disabled.

## Profile learning

The editable profile contains interests, current weekly build, prior builds, questions
engaged with the Course Agent, open questions, and the original free-text project field.
The authenticated course conversation service records owned student-message observations.
On first use it also imports the student's own nonarchived conversation messages once.
It never imports another student's messages, assistant answers as student beliefs, or
synthetic greetings. Clearing feature memory prevents automatic historical re-import;
new student interactions can create new observations afterwards.

When the dream tool reads authorized own-build files, it records those observations too.
The student’s own roster metadata can supply interests, but cannot establish a completed
build or a question the student asked.
The same Course Agent/provider performs an isolated structured learning pass over new
observations in chronological batches. It can add/remove interests, prior builds and
engaged questions, or set the current build. Replacing a current build moves the old one
into prior builds. Every inferred change retains an observation ID and an exact source
quote. Identity comes from trusted execution context; output cannot select a student.
Exact quotation proves provenance, not semantic correctness. These inferences still need
live-model evaluation. Students can inspect observations and update provenance in private
history, and edit all profile fields. Student corrections supersede older pending
observations; optimistic revision checks reject in-flight stale learning writes.

Automatic learning uses additional configured-provider calls. No calls are made for
anonymous users or when the feature is disabled. Failed inference leaves observations
pending for retry, without claiming the profile was updated or breaking the course reply.
The local sample preview does not pretend to learn from its synthetic Generate command.

## Storage and retrieval

JSON is stored at `var/weekly-dreams/<trusted-user-UUID>.json` (configurable root), with
private directory/file permissions. This is not encryption. All dreams, all feedback
revisions, profile observations and change evidence are retained until explicitly cleared;
there is no fixed count or age cutoff. Server operators can access these records. Other
students cannot retrieve them through the feature. Clearing does not erase backups or the
original course conversations.

The application record is now schema version 2. Version 1 files are accepted and upgraded
on their next successful read/write; old profiles, dreams, feedback, IDs and timestamps
are preserved, with new fields defaulted. Data already discarded by the former eight-dream
cutoff cannot be recovered. No stable core/wire schema or SQL migration changes.

Preparation reads the entire saved profile and dream/feedback history. Below the configured
`WEEKLY_DREAM_COMPACTION_CHARS` threshold (default 24000 characters), it returns the full
profile, all drafts and feedback. Above it, the same agent summarizes that context in
bounded batches, recursively if needed. The returned context pack identifies its
representation as `full` or `summarized`; in the latter case `history_summary` represents
the profile and history, and the raw profile/draft/feedback fields are omitted or empty.
Current authorized course sources and evidence references are still supplied separately.
Original records are never rewritten or deleted by summarization. Each summary must
account for every input entry ID; semantic fidelity still requires evaluation. Missing
coverage, lack of size reduction or model failure stops preparation with a clear error.
This is an explicitly implemented feature compactor, not a claim that the upstream
runtime already had automatic summarization. Its ordinary recent-chat window is separate.

## Generation and delivery

The Skill guides generation through prepare, history and validated save. Each suggestion
needs course and student grounding; links (including those in prose) must appear in cited
sources, and peer suggestions need an authorized roster match. Output uses the DreamDraft
schema and a hard 110-word limit. These checks do not prove entailment or semantic novelty.

`dream_email.py` renders the short email. Intended delivery follows the Course Agent's
weekly class email, but its exact sender path/trigger has not been integrated. Sending
and scheduling remain disabled. Production delivery still needs trusted roster recipients
and a per-student/week outbox to avoid duplicate sends.

Run `.venv/bin/python -m course_server.dream_preview` from `class-agent/`, then open
http://127.0.0.1:8767. The fixed Brooke examples are labeled scripted fixtures. Optional live
generation uses a server-side key in the uncommitted `.env`; no paid provider run has been
verified. The simulated-provider tests exercise learning, isolation, retention, compaction
and the existing runtime without API spend. These are engineering notes, not outcome
results or the group's reflection.
