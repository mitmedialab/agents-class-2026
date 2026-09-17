# Student project access

The Course Agent connects directly to the GitHub API for the repositories in the configured
course collection. This is a server-side, read-only integration; GitHub credentials never reach
the browser, model prompt, tool arguments, events, or logs.

## Authorization

Platform code filters tools before the model sees them and each tool checks the trusted
`PrincipalContext` again during execution:

| Principal | Project list and deployed sites | Repository source and metadata |
| --- | --- | --- |
| Anonymous | No | No |
| Student | All course project sites | No |
| Instructor | All course project sites | All course repositories |
| TA | All course project sites | All course repositories |
| Admin | All course project sites | All course repositories |

The repository boundary is the configured organization and prefix, minus explicit exclusions.
For this deployment that is `mitmedialab/agents2026-*` except `agents2026-test`. A model-supplied
organization, arbitrary repository URL, user ID, or role cannot widen that scope.

`course.list_student_projects` returns only project IDs and deployed HTTPS URLs. Student
listings contain other accepted students; see self-exclusion below.
`course.inspect_student_site` reads the current public site and intentionally returns no source,
commits, issues, or workflow information. The agent can pass the returned URL to the existing
isolated `browser.open` tool for a rendered visual inspection.

`staff.inspect_student_repository` is available to TAs, instructors, and admins. It supports
focused, bounded reads of repository summary,
tree, UTF-8 files, commits, branches, pull requests, issues, and Actions workflow runs. It cannot
read secrets, repository settings, collaborators, or perform writes. Full fetched results are
ephemeral to the current model turn; durable history stores only a generic completion summary.
Obvious committed credential and private-key paths are refused before GitHub file content is read.

## Configuration

Enable the integration only after installing a credential with read access to the private course
repositories:

```dotenv
GITHUB_STUDENT_PROJECTS_ENABLED=true
GITHUB_TOKEN=replace-with-protected-read-only-token
GITHUB_ORGANIZATION=mitmedialab
GITHUB_REPOSITORY_PREFIX=agents2026-
GITHUB_EXCLUDED_REPOSITORIES=agents2026-test
GITHUB_ROSTER_CACHE_TTL_SECONDS=300
```

Prefer a GitHub App installation token or a fine-grained token restricted to the 26 repositories.
Grant only Metadata, Contents, Pull requests, Issues, Actions, and Pages read access. Do not grant
write or administration permissions. Keep the value in the protected server environment; never
commit it. The API must be restarted after configuration changes.

The adapter enumerates the real repositories rather than maintaining a second mock roster. To
avoid repeating the same GitHub organization and Pages calls during a conversation, it keeps the
resolved roster in process for the configured bounded TTL (five minutes by default). Set the TTL
to `0` to disable caching. Repository summaries, trees, files, commits, branches, pull requests,
issues, and workflow runs are never served from this roster cache and remain live GitHub reads.
The adapter uses repository `homepage` metadata first and GitHub Pages metadata when present.
Projects without either value remain listed with no deployed site until their metadata is fixed.
Normal automated tests use an injected HTTP transport, while an explicit deployment check uses
the real credential and GitHub API.

## Failure behavior

Provider authentication, invalid requests, missing repositories, and temporary GitHub failures
produce distinct safe categories without returning provider response bodies. Site reads reuse the
existing public-network validation, redirect limits, response-size bounds, and private-address
rejection. GitHub file reads are limited to UTF-8 text and 50,000 bytes per call; lists and trees
are bounded.

## Peer recommendations and self-exclusion

Student listings apply self-exclusion automatically. There is no opt-in matching argument and
no `student-identities.json`, extra roster, provisioning command, or new environment setting.
The API/CLI passes the existing auth store to the tools. Platform code loads the active account
by the trusted session's user UUID and compares its stored email with accepted application emails
using case-insensitive, whitespace-trimmed equality. Tool arguments cannot choose the requester.

`instructor.list_applications` always excludes every application with the student's account
email, including duplicate submissions, regardless of `accepted_only`. Access remains bounded
by the existing `student-access.json` UUID allowlist; submitted email claims cannot grant access
to an unaccepted application. Staff application listings are unchanged.

A student can call `instructor.read_application` without `application_id` to read their own
accepted profile as comparison context. The email must match exactly one accepted record;
missing or duplicate matches return a clear error requiring correction of the existing data.
Explicit authorized reads by application ID continue to work, including one's own application.

Student `course.list_student_projects` results contain only other accepted students' projects.
This deployment's established repository convention is `GITHUB_REPOSITORY_PREFIX` plus the first
word of the accepted applicant's name, compared case-insensitively (for example, Ada Example
maps to `agents2026-ada`). The logged-in student's first name is excluded, including all same-name
collisions. Names shared by different accepted emails are omitted rather than attributing a
website to the wrong person. The student's own email must resolve to an accepted application
with a name before website candidates can be returned. Other unresolved names simply do not
match a repository. GitHub usernames/write collaborators are not read by this implementation;
it uses the confirmed first-name naming convention, not a repository-ownership assertion.

The resulting IDs are intersected with the existing live GitHub course roster. The server-side
roster cache is shared, but filtering occurs after retrieval for each authenticated user so one
student's candidate list never becomes another student's cached list. TA/instructor/admin
project listings are unchanged. Direct authorized site inspection still permits every course
site, including one's own.

The student skill reads the personal profile separately and uses the latest peer lists for
recommendations. Code enforces exclusion in these lists on every call; arbitrary model prose
is not a separately validated matching-result contract. Correct email records and the documented
repository naming convention remain the identity assumptions.

Deploy the code and restart the API. Existing account records, accepted applications,
`student-access.json`, and GitHub configuration are sufficient. No identity file or database
migration is required. The own-profile read is an additive optional-ID tool operation; stable
core/wire schemas and persisted records are unchanged. The superseded `for_matching` argument
is rejected; callers should omit it. It cannot be used to bypass filtering.
