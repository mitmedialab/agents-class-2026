# Private weekly build feedback

**Grading** opens the syllabus evaluation policy and links to released graded weekly
builds for active credit students. Opening one shows the student's TA feedback beneath
the assignment instructions, or says no feedback is posted. Comments and checklist
items are displayed separately without assigning numeric scores. The Course Agent can
read the logged-in student's own notes through `grades.get_mine`; the tool accepts no
student identifier.

The API derives identity from the authenticated session. `GET /api/v1/grades/mine`
returns graded assignment titles and feedback availability, and
`GET /api/v1/grades/mine/assignments/{assignment_id}` returns that student's note or
`null`. Both responses use `Cache-Control: private, no-store`. Listeners, inactive
students, and other roles receive `404`. Feedback is never copied into public course
resources or workspace events.

`GRADE_DATA_PATH` defaults to `var/grades/weekly-feedback.json`. Keep the file in
protected server storage and out of Git. The Week 8 fork setup installs a synthetic
example at that path with private file permissions. The format is:

```json
{
  "schema_version": 2,
  "weekly_build_assignment_ids": ["week-2", "week-3"],
  "students": {
    "student_username": [
      {
        "week": 3,
        "date": "2026-10-17",
        "reviewer": "Fictional Course TA",
        "feedback": "Comments and grading checklist from the TA"
      }
    ]
  }
}
```

Each student can have at most one note per listed build. The explicit assignment ID
list defines the grading scope. A missing note means only that no feedback is posted
in this file; it does not establish that a student missed an assignment. The server
reads the file on each request, so an atomic replacement takes effect without an API
restart. Roster changes still require a restart.

For a separate `test-*` student account, set both `GRADE_PREVIEW_USERNAME` and
`GRADE_PREVIEW_DATA_PATH` to use an isolated gradebook. Set `GRADE_PREVIEW_ONLY=true`
on a dedicated preview server if real credit students should be denied there. Leave
these settings unset for ordinary local development with the fictional starter roster.
