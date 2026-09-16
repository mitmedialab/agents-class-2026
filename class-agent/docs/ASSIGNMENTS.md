# Course assignments

Course assignments are server-owned, validated JSON records. `ASSIGNMENT_DATA_PATH` defaults to
`var/assignments/`, and each assignment occupies exactly one file named
`<assignment_id>.json`. The directory is ignored by Git so each deployment can maintain its own
course state. Include it in protected production backups.

## Stored schema

Current JSON files are validated as schema version 3 and must contain exactly these keys:

```json
{
  "schema_version": 3,
  "assignment_id": "observe-an-agent-8f3a1c2d",
  "revision": 1,
  "status": "published",
  "title": "Observe an agent",
  "summary": "The complete assignment as authored in Markdown.",
  "content_markdown": "# Observe an agent\n\nThe complete assignment as authored in Markdown.",
  "release_at": "2026-09-06T09:00:00-04:00",
  "due_at": "2026-09-18T23:59:00-04:00",
  "created_at": "2026-09-05T12:00:00-04:00",
  "updated_at": "2026-09-05T12:00:00-04:00",
  "created_by_user_id": "00000000-0000-4000-8000-000000000001"
}
```

`assignment_id` is an internal record identifier and must match the filename. `summary` is a bounded plain-text projection of
the first useful paragraph in `content_markdown` for notification cards, not a second authored
copy. `status` is either `draft` or `published`; `revision` is a positive integer. Every timestamp
must include a timezone, and `due_at` must be later than `release_at`. Unknown fields, malformed
records, symlinks, oversized files, and duplicate IDs fail closed.

Schema version 3 stores the full assignment as Markdown rather than splitting it across summary,
instructions, and submission fields. Exact schema-version-1 and version-2 records remain readable
through narrow compatibility parsers. Their maintained title, summary, instructions, and submission
requirements are projected into one Markdown document; the former version-1 grading field is
discarded. Reading does not rewrite legacy files. Other unknown fields still fail closed.

## Access and rendering

The application intentionally exposes no assignment-creation or assignment-update tool and no
assignment editor. Assignment records are maintained as server-owned course data.

The `course.list_assignments` and `course.get_assignment` tools let the agent inspect
authorized records. Instructors can see drafts and scheduled assignments. Students and TAs see only
published assignments whose release time has passed. Anonymous visitors and admins receive none of
these tools. A successful `course.get_assignment` call opens the exact stored `content_markdown` in
the workspace's safe Markdown renderer so students can read the complete posted assignment without
an agent paraphrase.

Operational changes must preserve the schema, keep the ID and filename aligned, update revision and
timestamps deliberately, and pass the assignment tests before deployment.

## Notification behavior

A published assignment creates an unread release item once `release_at` has passed. It also appears
under Upcoming from fourteen days before `due_at` until the deadline, with its countdown computed
by the server. The release item ID includes the assignment revision, so an intentional revision can
produce a fresh notification. The notification action asks the Course Agent to read the same
authorized assignment record before explaining it or suggesting a plan.

Restart the API after changing Python code or `ASSIGNMENT_DATA_PATH`. Assignment JSON contents are
read from disk for each projection and tool call, so ordinary content edits do not otherwise require
reindexing or a database migration.
