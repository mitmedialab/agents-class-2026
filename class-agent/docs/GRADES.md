# Private weekly build feedback

Grading opens the syllabus evaluation policy followed by weekly-build feedback cards
for active credit students. Each card links to its assignment. The student's TA
feedback also appears beneath the assignment instructions, or the card says no feedback is posted.
Comments and checklist results are shown as separate sections; checklist marks are
displayed as individual items without assigning numeric scores.
The renderer also handles TA emails that put the checklist before the comment and
use bullet-prefixed checkmarks; reviewer follow-ups remain with the comments.
Listeners and inactive students do not see grading data, even if an inactive credit
student's historical feedback is retained in the private file. The Course Agent can read
the logged-in credit student's own notes through `grades.get_mine`; it accepts no
student identifier. There is no numeric score in the imported feedback.

Feedback is fetched through `GET /grades/mine/assignments/{assignment_id}` and is
never copied into workspace events or public course resources. `GET /grades/mine`
returns assignment titles and availability for the Grading links. Both endpoints
derive identity from the authenticated session and send `Cache-Control: private,
no-store`. They return `404` for anyone outside the active credit roster.

`GRADE_DATA_PATH` defaults to `var/grades/weekly-feedback.json`. Keep it in protected
server storage with mode `0600`, include it in encrypted backups, and do not commit
it. The format is:

```json
{
  "schema_version": 2,
  "weekly_build_assignment_ids": ["week-2", "week-3", "week-4"],
  "students": {
    "student_username": [
      {
        "week": 3,
        "date": "2026-10-17",
        "reviewer": "Course TA",
        "feedback": "Comments and grading checklist from the TA"
      }
    ]
  }
}
```

Use course account usernames. Each student can have at most one note per build.
`weekly_build_assignment_ids` is the explicit grading scope. Week 1 and the Week 7
final project proposal are excluded. Add later weekly builds to this list when
released. The server reads the file on each request, so an atomic replacement takes
effect without restarting the API. Roster changes still require a service restart.

The source collection is incomplete. The private `var/grades/import-audit.md` records
which messages were imported and week-by-week coverage. Absence of a note does not
establish that a student missed an assignment or grade.

## Testing with a separate student account

For a live website preview, configure both `GRADE_PREVIEW_USERNAME=test-student2` and
`GRADE_PREVIEW_DATA_PATH=var/grades/test-student2-preview.json` on the API host, then
restart the API after deploying the frontend and backend changes. The preview account
must already be an active student login. Its gradebook is separate from real student
feedback and must contain only the configured `test-*` username. The repository's
ignored `var/grades/test-student2-preview.json` is sample feedback for Week 3, with
comments and marked checklist items. It has no real grade or student data. Keep it
mode `0600` and do not publish or commit it. Leave both settings unset to disable
preview access. The preview account is not added to the canonical credit roster or
included in credit-student coverage counts.
Set `GRADE_PREVIEW_ONLY=true` on a public preview service to deny real credit accounts
until the grading feature is released on the main site. The normal API defaults this
setting to false.

After login, open **Grading** and select **Week 3 Build**. The assignment should show
the sample comments and grading checklist beneath its instructions. Other graded
weekly builds should say no feedback is posted. Week 1 and the Week 7 final project
proposal should not appear in the Grading list.

For the current host, the isolated live preview is built at
`/home/wazeer/grade-preview-site/dist` with Vite base `/grade-preview/` and API base
`/grade-preview/api/v1`. An administrator can install the separate port-8002 service
and nginx location with `sudo bash deploy/enable-grade-preview.sh`. This exposes
`https://cognitive-agents.media.mit.edu/grade-preview/` while the main site's
frontend, API process, and port-8000 proxy remain in place. The script checks nginx
syntax and the preview API health before reloading nginx; it backs up the existing
site config and rolls back on failure. Remove the preview with
`sudo bash deploy/disable-grade-preview.sh` after testing. The preview runs from the
current checkout and should be stopped before changing its Python source.
