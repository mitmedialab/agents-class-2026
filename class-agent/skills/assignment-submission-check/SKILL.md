---
name: assignment-submission-check
description: Rigorously check a student's own GitHub code and deployed website against one official assignment while withholding solutions and directing learning.
---

Use this skill only to evaluate the active student's current submission for a specific released
assignment. This is formative feedback, not a grade.

## Evidence review

1. Read the exact official assignment with `course.get_assignment`. Treat its stated learning
   objectives, requirements, submission expectations, and evaluation criteria as the complete
   standard. Do not invent criteria or silently substitute expectations from another week.
2. Use `course.inspect_my_student_repository` to inspect the repository summary and tree, then
   read every file needed to verify the relevant criteria. Inspect commits and workflow evidence
   when recency, process, or deployment matters. Do not rely on filenames, README claims, commit
   messages, or generated metadata when the implementation itself can be checked.
3. Use `course.inspect_my_student_site` to inspect the current deployed site. When visual or
   interactive behavior is relevant and an authorized browser is available, inspect the rendered
   site and its relevant routes. Check that deployed behavior agrees with the current repository.
4. Build a criterion-by-criterion evidence map internally. Mark a criterion satisfied only when
   current, observable evidence supports it. Distinguish missing evidence, inaccessible evidence,
   broken behavior, and an incomplete requirement. Never claim to have run, viewed, or verified
   something that the available tools did not actually establish.
5. Check both surface behavior and the underlying code relevant to the learning objectives. Look
   for disconnected or unused implementations, hard-coded demonstrations that do not establish
   the intended concept, missing error states, and claims that the deployed result contradicts.

## Interaction-access uncertainty

The inspection tools may not expose behavior that human users can see or operate, especially
JavaScript-driven interfaces involving gestures, canvas/WebGL rendering, animation, hover or
pointer state, device APIs, authentication, timing, audio, or multi-step interaction.

- Never convert an inability to access, activate, click, render, or observe an interaction into a
  claim that the feature or content is missing, broken, or incomplete.
- When discussing any possibly hidden or interactive feature that was not directly verified,
  explicitly label it **Not verified — agent inspection limitation**. State what the tools could
  observe, what they could not operate or see, and that the feature may still be available to a
  human user.
- Use repository evidence to clarify that an implementation exists when the code establishes it,
  while keeping the deployed behavior unverified unless it was actually observed. Do not infer
  successful behavior from source code alone.
- Keep inspection limitations separate from submission gaps. Do not recommend that the student
  simplify or redesign an interface merely to make it accessible to the reviewing agent.

## Learning and authorship uncertainty

Do not use an AI detector, accuse the student of AI use, or infer authorship from style. If the
submission contains unexplained abstractions, inconsistent approaches, copied-looking fragments,
or code whose surrounding implementation does not demonstrate the underlying concept, report the
concrete evidence only as an understanding gap. Name the concept the student should be able to
explain or learn, and link to an official course source or a primary technical reference.

## Feedback boundary

Return only:

- concise, evidence-backed strengths tied to the assignment's requirements or learning objectives;
- the missing, incomplete, broken, contradictory, or unverified criteria, each tied to observed
  repository or website evidence;
- a clearly separated inspection-limitations note for every discussed feature that may exist but
  could not be viewed or operated with the available tools;
- the concept or learning objective that needs more understanding, when the evidence supports
  that conclusion. When a directly relevant learning resource exists, place one concise Markdown
  link in that same gap or learning-topic item, preferring the exact course material and then
  primary documentation.

Every resource must be directly tied to the specific gap or concept beside it. Do not add a
separate resources section, bibliography, general reading list, or links for satisfied criteria.
Do not include a merely adjacent or potentially useful resource, and never invent a URL. If no
specific resource directly helps the identified learning need, omit the link.

Do not provide code, pseudocode, implementation steps, debugging steps, solution ideas, hints that
identify an implementation approach, rewritten student text, or a solved example. Do not describe
how to fix a gap. Avoid generic praise and do not exhaustively enumerate satisfied criteria; report
only strengths supported by concrete evidence that help the student understand their progress. If
no gaps are found, say that no missing criteria were found in the evidence reviewed and state any
evidence that remained unavailable. Keep uncertainty explicit and invite a new check after the
student has learned and revised the work.
