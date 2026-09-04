---
name: workspace-presentation
description: Present substantive answers, artifacts, schedules, drafts, comparisons, or visual explanations in the registered conversation workspace.
---

Treat the trusted conversation workspace as the preferred presentation surface when a registered
component clearly represents the result.

When the workspace carries the detailed result, treat it as the primary response. Do not duplicate
its headings, facts, summaries, schedule entries, draft text, or field values in chat. After a
successful open or update, chat may contain only a brief handoff or one next question that the user
must answer. If no handoff or question is useful, keep the acknowledgement minimal.

- Show schedules in `calendar`.
- Open a particular paper, PDF, text file, or uploaded artifact in `document-viewer` when the user
  wants to read, navigate, search, or discuss passages.
- Open a particular website in `webpage-viewer`, or use the remote browser when the user wants to
  see or interact with the live public site.
- For knowledge questions, summaries, comparisons, and overviews, synthesize the useful information
  in `visual-composition`. Do not choose `document-viewer` merely because a source is a document.
- For an evolving proposal, report, note, letter, outline, plan, form, or application, open one
  `draft-document` and update that same panel. Preserve prior material unless the user asks to replace
  it. Mark fields confirmed only when the user supplies or confirms them.

The workspace has one current surface. Open a new surface when the user's focus changes; update the
current panel only when refining the same artifact or presentation. Never invent a component, HTML,
CSS, JavaScript, class name, style string, or unregistered renderer.

Workspace focus is silent housekeeping. Do not announce a focus operation or focus a panel that is
already focused. A draft is a progress view, not approval for an external effect; require explicit
user approval before submission.

When the task calls for a composed knowledge interface, read
[the visual-composition reference](references/visual-composition.md) before opening or updating it.
