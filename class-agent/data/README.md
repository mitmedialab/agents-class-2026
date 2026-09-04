# Protected course data

This directory is the local-development default for role-scoped course resources. Real
deployment data should normally live outside the Git checkout and be selected with
`COURSE_DATA_PATH`.

- `students/` is readable after login by student and instructor accounts.
- `instructors/` is readable only by instructor accounts.
- TA and admin roles do not inherit either audience automatically.

Contents below both audience directories are ignored by Git. Do not commit student records,
grades, credentials, applicant records, or other private data.

Each readable resource must have a sibling `resource.json`; files are never exposed merely
because they exist in a protected directory. Example student resource:

```json
{
  "schema_version": 1,
  "resource": {
    "uri": "course://students/week-one",
    "title": "Week One Notes",
    "description": "Notes available to enrolled students and instructors.",
    "media_type": "text/markdown",
    "file": "week-one.md",
    "visibility": "students",
    "status": "published"
  }
}
```

Instructor resources use a `course://instructors/...` URI and
`"visibility": "instructors"`. Paths are confined to their audience directory, and the
runtime exposes only authorized opaque URIs—not filesystem paths.
