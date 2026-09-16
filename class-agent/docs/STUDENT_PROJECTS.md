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

`course.list_student_projects` returns only project IDs and deployed HTTPS URLs.
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
