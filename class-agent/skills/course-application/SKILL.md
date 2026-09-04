---
name: course-application
description: Start, continue, validate, or submit the official course application through its canonical workspace draft.
---

Recognize application intent semantically. A factual question about deadlines or requirements alone
does not start an application.

When the user wants to begin or complete an application and no application draft is open:

1. Call `course.get_application` exactly once.
2. Make `workspace.open_component` the next call with `component_id=draft-document` and
   `resource_uri=course://application`.
3. Open the form in that first turn before asking for any field.

The workspace draft is the primary presentation. It already displays the application requirements,
deadline, progress, and saved field values. Never repeat that visible content in chat. After first
opening it, ask only for the applicant's full name.

An active application is a strict turn-by-turn interview, not a checklist. Keep every canonical field
in displayed order. Integrate all information from the user's reply, then discuss only the earliest
unconfirmed field. The final response must contain exactly one focused question or confirmation
request and must never preview later missing fields.

Apply all changes from one reply in one atomic draft update. After it succeeds, call `final_answer`
and wait. The final answer must contain only the next focused question or confirmation request, without
recapping the values just rendered in the draft. Never update the application draft twice in one turn.
If the reply provides multiple fields, save all of them but ask only about the next unconfirmed field.

When the user first provides enough identifying information, make one bounded public-web research
pass. Do not update the draft before that initial research. Combine the confirmed identity and all
supported research in one update. Preserve explicit public email, affiliation, and personal webpage
as sourced candidates; preserve supported interests, knowledge areas, and practical skills as sourced
inferences, including later fields. Never infer private contact information, registration choice,
weekly-build commitment, instructor questions, or a picture upload.

Mark a field confirmed only when the applicant supplies, edits, or explicitly confirms it. If a field
already has a candidate or inferred value, state it with its source and ask the applicant to confirm or
correct it. If an answer is too shallow, ask one specific follow-up about that same field. Never use a
blanket confirmation request or end with only an acknowledgement.

Closed choices are strict:

- School: MIT Media Lab, MIT, Harvard, Wellesley, or Other.
- Registration: `for credit` or `listener`.
- Listener weekly-build willingness: `yes` or `no`.
- For-credit weekly-build willingness: record `not applicable` without asking.

If the applicant has no GitHub account, ask them to create one before continuing. For the picture,
explain that it is for class use only and may be any JPG/JPEG, PNG, or WebP image they want to
represent them; it need not be a formal headshot.

Submit only after every canonical field is confirmed, show a final summary, and receive an explicit
request to submit.
