# Weekly dream implementation notes

This is an opt-in extension of the existing Course Agent, not a separate agent.
Enable `WEEKLY_DREAM_ENABLED=true` to register six student-owned tools in the
existing runtime and capability policy. The default is disabled.

## Content and memory

The weekly-dream Skill guides the model through prepare, history, and save.
Preparation gathers explicitly selected authorized public course resources, the
student's own roster entry and optional own-repository files, their editable
focus, recent suggestions, and explicit feedback. Peer suggestions require the
authorized student roster and a matching active member. Source content is data,
not instructions.

The trusted principal supplies ownership; tool inputs cannot select another
student. Validated JSON lives under `var/weekly-dreams/<user-UUID>.json` (override
with the configured store path). Directories are private and files use mode 0600;
this is file permission protection, not encryption. Each record keeps an editable
profile, eight recent dreams, and up to 32 explicit feedback entries. Only sources
cited by a saved dream are retained with it. Retention is bounded by count, not age.
Students can inspect, correct, or clear their own feature memory. Server operators
can access the backing files; clearing does not erase backups or existing chats.
No engagement tracking is implemented.

Save validates source identifiers, course and personal grounding, known reading
links (including URLs embedded in prose/headlines), verified peer identities, profile
revision, and recently repeated item keys.
These checks do not prove factual entailment or detect every semantic repetition.
Output aims for 75–100 words, with a hard 110-word limit including headings.

## Email and review

`dream_email.py` renders a short plain-text subject and body. The intended delivery
is just after the existing weekly class email. Brooke confirmed that the Course Agent sends the weekly class email. Scheduling
and sending are not yet wired: its specific sender path must be located so a trusted
successful-send event can trigger the dream. The existing Graph/Gmail mail worker provides transport, but its confirmed
message delivery is not a weekly announcement trigger. Do not infer consent or
recipients from generated text. Any production integration must use trusted roster
recipients, explicit delivery configuration, and an idempotent per-student/week
outbox to avoid duplicates on retry.

The loopback preview is deliberately separate from the production API. Run from
`class-agent/` with `.venv/bin/python -m course_server.dream_preview`, then open
http://127.0.0.1:8767. Its test identity represents Brooke and contains no private
roster. Reviewed examples are fixed fixtures, explicitly labeled; the follow-up
requires marking the first connection Already explored. The explicitly confirmed
Reset Brooke sample action restores the original sample profile for replay; ordinary
Clear local dream memory stays cleared across restarts. Optional live generation
uses the existing runtime and a server-side `OPENAI_API_KEY` in the uncommitted
`.env`. No live model generation has been verified without that key. The preview
does not send email, and its JSON under `var/dream-preview` is ignored by Git.

These are engineering notes, not the group's assignment writeup or reflection.
