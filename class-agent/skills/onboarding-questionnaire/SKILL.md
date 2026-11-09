---
name: onboarding-questionnaire
description: Turn a user's submitted onboarding questionnaire responses into separate memories with memory.save_mine.
---

Use this skill when a message contains the user's submitted onboarding questionnaire responses.
The questions and answers come in that message.

## Saving

Call `memory.save_mine` once for each fact worth remembering. Make all of these calls together in
a single response, because a run has a limited number of steps.

1. Save one fact per memory. Split an answer that holds several separate facts.
2. Use the user's own terms. Do not add, infer, generalize, or embellish. Write memories without
   gendered pronouns, and do not infer gender from a name.
3. Skip blank answers and answers that say nothing about the user, such as "n/a".
4. Do not save secrets, such as passwords or access codes. Do not save sensitive details, such as
   health, financial, or legal information, unless the user clearly offered them as a preference
   for how the agent should help them.
5. Set `kind` to a short category, such as `preference`, `goal`, or `background`.

## Replying

Briefly tell the user what was saved and what was left out, if anything. Report only saves that
succeeded. If `memory.save_mine` is unavailable or fails, say that those answers were not saved.
