# Weekly dream evaluation workbench

Status: input preparation only. No model outputs, human ratings, or outcome results yet.
This is an engineering protocol to help the group conduct an evaluation; write the
assignment's evaluation paragraphs and reflection yourselves.

## Question and comparisons

Does a personalized weekly email offer more useful, new connections than a generic
course email? Does retaining suggestions and feedback improve the next email?

| Condition | Course sources | Student focus | Past suggestions and feedback |
| --- | --- | --- | --- |
| Generic | Same | None | None |
| Profile only | Same | Same | None |
| Profile and memory | Same | Same | Included |

Two cases: an initial note and a follow-up after an association-coverage suggestion
was marked Already explored. The follow-up history and feedback are scripted test
fixtures, not feedback Brooke actually gave. Brooke's stated interests and public
projects supply the example profile. These cases test output behavior; a single
profile cannot establish an effect across students or on learning outcomes.

## Prepare and generate

From `class-agent/`:

```sh
.venv/bin/python -m course_server.dream_eval prepare var/dream-evaluation/pilot-01
```

This prepares 18 randomized packets: two cases × three conditions × three repeated
generations. It also creates an empty `ratings.csv` and a separate blinding key.
Existing runs cannot be overwritten. Generated local files are ignored by Git.
Each packet snapshots bounded, real course text and uses the same instruction.

Next step: run each packet as a fresh independent model request using the same
model version, reasoning settings, output limit, and sampling settings. Save the
exact response, packet ID, settings, latency and cost. No tools or additional
retrieval should be enabled for any condition. Do not feed one response into the
next. Do not hand-edit weak outputs or replace failures selectively. A model runner
has not been implemented here; no provider credits are spent by these commands.
This controlled text-generation comparison does not evaluate the deployed scheduler
or the complete tool workflow, which has separate software regression tests.

## Rate and inspect

Give raters the same target profile and, for the follow-up, the same prior suggestion
and feedback. Conceal condition labels and shuffle presentation. Text may still
reveal its condition, so this is label blinding, not guaranteed full blinding.
Keep `blinding-key.json` away from raters until scoring is complete.

Use 1–5 scales (1 poor, 3 adequate, 5 strong):

- Usefulness: offers a concrete starting point worth the student's time.
- Relevance: connects the supplied course evidence with the student's actual work.
- Novelty: offers a meaningful new angle, rather than a reworded familiar point.

Flag 0/1: repeats the dismissed idea; contains an unsupported claim or link.
Use 0 for the repetition flag in the fresh case, where no dismissal exists.
Check the 110-word limit separately and retain failed/empty outputs in the record.
Have Brooke rate personal usefulness; a second rater can audit source accuracy and
repetition. Use anonymous rater IDs in local files. Do not treat generation repeats
as additional independent students or infer learning gains from preference scores.

```sh
.venv/bin/python -m course_server.dream_eval summarize var/dream-evaluation/pilot-01
```

The report contains descriptive means and counts per case/condition. Blank ratings
produce `not_run`, not zero scores. This starter does not compute significance or
confidence intervals. Report missing outputs and ratings alongside any means.

## Stronger study to design together

Recruit multiple consenting students and randomize across conditions over several
weeks, while controlling topic/week and carryover. Use student-rated usefulness as the primary outcome, with questions covering
relevance, novelty and burden. Track useful connections acted on and repeated suggestions
as additional measures. If learning is the goal,
include a preregistered concept-transfer task assessed blind to condition rather
than relying on email opens. Keep private profiles and feedback separate by student;
use participant-level analysis and state uncertainty. The student-written plan
should specify its primary outcome, recruitment, sample size, and analysis before
collecting the main study data.
