# Frontend changes

All paths are under `class-agent/apps/web/src/`.

## New files

| File | What it adds |
|---|---|
| `People.tsx` | The People panel (`PeoplePanel`) with its `MemoryCard` and `IntroductionCard` components. |
| `People.test.tsx` | 3 vitest tests (list below). |

## Changed files

| File | Change |
|---|---|
| `App.tsx` | A **People** header button, shown only to logged-in students. It opens the panel through the existing static-open flow (`openStatic("people")`), the same way Schedule and Grading work. |
| `Workspace.tsx` | Renders `PeoplePanel` when a `draft-document` panel has `document_kind: "people-overview"`. That is the panel the header button opens, and also the one `peers.request_introduction` opens after drafting. |
| `api.ts` | Types `StudentMemory`, `PeerIntroduction`, `PeopleOverview`, `MemoryKind` and `MemoryPrivacy`; functions `getMyPeople`, `updateMyMemory`, `deleteMyMemory` and `actOnIntroduction`; `"people"` added to the `openStaticWorkspace` targets. |
| `styles.css` | `.people-*` styles built on the existing UI tokens. Shared items use the reply color, and items the student needs help with use the message color. |

No new component was added to the workspace registry. The panel reuses the registered
`draft-document` component and is told apart by `document_kind`, as Grading is.

## The People panel

Sections, top to bottom:

1. **Waiting for you** (shown only when there is something to act on):
   - your drafts, with **Send** and **Discard**;
   - requests sent to you, with **Accept** and **Decline**.
2. **What the Course Agent remembers about you**: one card per memory.
   - It shows the kind (Background, Goal, Preference, Project, Can help with, Needs help with),
     the text, and who saved it ("Saved by the agent" or "Edited by you").
   - It shows the date and the source excerpt ("From your message: …").
   - **Visible to**: Only me, or Classmates looking for help. A change saves immediately.
   - **Correct**: edit the text, then Save or Cancel.
   - **Forget**: delete the memory.
   - A note above the list says who can see what, and that course staff have no view of it.
3. **Introductions**: the history of sent, accepted, declined, unavailable and cancelled
   requests. When a request is accepted, the requester is told to reach out in class or on the
   course channel.

Requester and helper see different status labels for the same request:

| Status | Requester sees | Helper sees |
|---|---|---|
| `draft` | Draft, not sent | (hidden) |
| `sent` | Waiting for a reply, with **Withdraw** | Waiting for a reply, with Accept / Decline |
| `accepted` | Accepted, plus the next step | Accepted, "You agreed to help …" |
| `declined` | Not available this time | You declined |

If the API refuses the panel, for example for staff or an inactive account, the panel shows
"People is available to active students."

## Tests

`People.test.tsx`:

1. Memories render with their source excerpt. Changing visibility sends
   `PATCH /people/mine/memories/{id}` with `{privacy}`, and the card then shows "Edited by you".
2. A drafted introduction is sent only after the student clicks **Send**. The request body is
   `{"action": "send"}`, and the status becomes "Waiting for a reply".
3. A `404` from the API shows the unavailable message.

Results on this branch:

- `pnpm test`: 188 web tests passed, including these 3, plus the workspace and protocol
  packages.
- `pnpm typecheck` passes.
