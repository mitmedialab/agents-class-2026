# Canonical course roster

`COURSE_ROSTER_PATH` is the one private operational source for accepted membership, current
active/inactive status, enrollment type, account and GitHub identities, participation, project
links, and project interests. It defaults to `var/roster/course-members.json`; production should
place it in protected server storage, keep it mode `0600`, and include it in encrypted backups.
It is ignored by Git and must never be registered directly as a course resource.

The version-1 JSON object contains `schema_version`, `as_of`, and `members`. Every member has a
stable `student_id`, course `username`, distinct `github_username`, name/aliases, email,
institution, department, enrollment and participation types, current `course_status`, optional
project/site and application linkage, keywords, and up to three project ideas. Inactive members
also require a reason and explicit departure-notice state. IDs, emails, usernames, GitHub
usernames, and project IDs are unique.

## Runtime projections and access

Before restart, the operator command atomically publishes two generated protected resources beneath
`COURSE_DATA_PATH`. The API validates the complete source and verifies both projections match it
exactly before accepting requests:

- `course://students/roster` contains the complete active-member profile and project-interest
  projection. Authenticated students and instructors may read it through the existing private
  resource tools. Inactive members and operational application IDs are absent.
- `course://instructors/roster` contains active and inactive members plus operational status.
  Only authenticated instructors may read it.

The source file is never sent to a browser, model, conversation event, or resource index. Private
resource reads use summary-only durable tool events and `no-store` HTTP responses.

The same validated roster controls related boundaries:

- an explicitly inactive student username cannot create or continue an authenticated session;
- the instructor student directory and all-student messaging resolve only active roster members
  whose PostgreSQL student accounts are also active;
- GitHub listing, inspection, and showcase tools accept only active weekly-build project IDs;
- course-account to repository aliases are derived from the distinct course/GitHub identities;
- initial application sharing projects accepted identities from this roster, while
  `student-access.json` remains the explicit immutable UUID authority.

PostgreSQL still owns credentials, roles, the account `active` kill switch, and sessions. Raw
application records remain immutable. A roster edit does not rewrite either store.

## Migration and updates

For the one-time migration from the former accepted, status, and project-interest files:

```bash
uv run python -m course_server.course_roster migrate-legacy \
  --accepted var/applicants/accepted-applicants.json \
  --status var/active-roster.json \
  --interests data/students/final-project-interests/final-project-interests.md \
  --applicants var/applicants \
  --output var/roster/course-members.json \
  --course-data data
```

The importer fails on missing status, ambiguous applications, invalid identities, and duplicates.
After verifying the result, archive or remove `accepted-applicants.json`, `active-roster.json`,
`original-table.md`, and temporary roster CSVs. `student-access.json`, its resolution report, and
the raw applications remain.

For later edits, atomically replace the canonical JSON and validate/publish it before restarting:

```bash
uv run python -m course_server.course_roster publish \
  --roster var/roster/course-members.json \
  --course-data data
```

Startup never writes these files or widens its protected filesystem permissions; it fails closed
when a projection is absent or stale. Reconcile course usernames with active PostgreSQL student
accounts before deployment; a membership status change takes effect after publishing and the next
API restart. Never hand-edit the generated Markdown or manifests.
