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
issues, and workflow runs are never served from this roster cache. Successful tool reads are
reused within a single agent run; a new run fetches fresh evidence. This transient cache is
not shared across conversations or principals and is not persisted.
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

## Weekly build showcase

Staff can use `staff.read_showcase_history`, `staff.screen_weekly_showcase`, and
`staff.select_weekly_showcase` when GitHub integration is enabled. Instructors also discover
the `weekly-build-showcase` skill. Resolve the assignment from maintained course sources first;
an empty assignment list does not mean schedule or weekly resources lack the instructions.

Screening reads public homepages and repository trees with at most four concurrent requests
and a 100-project roster bound. Recent presenters are skipped. It returns up to 4,000 characters per page,
explicit truncation, repository file listings, and independent site/repository failures.
Every inspected entry remains `needs_review`; a homepage read is not an eligibility result.
Before excluding unclear sites, the agent reads relevant weekly documentation, implementation
and commits through the existing read-only repository tool, and follows documented site routes.
Repository documentation can verify a weekly build without an accessible weekly post; filenames
or commit messages alone cannot. Failed evidence remains unresolved rather than ineligible. Full site reads (up to 20,000 characters) and repository reads are
cached only in the current run's trusted transient state. Failed requests are not cached.

The agent submits all site- or repository-verified eligible builds in `eligible_projects` for random sampling,
and a smaller evidence-backed repository-reviewed shortlist in `candidates` for ranking.
Only the shortlist needs four rubric scores and full repository review. Eligibility accepts
`post_evidence` and/or `repository_evidence`; assessed candidates still require repository evidence.
Missing post evidence must be disclosed, not fabricated. Assignment fit affects ranking rather
than excluding every incomplete assignment from the pool. A deployed site is still required. Results label ranking scope explicitly: shortlist winners are not proven class-wide
winners. Omitting `eligible_projects` preserves the original all-assessed-pool behavior.
The platform validates roster membership, distinct IDs and shortlist membership in the pool;
it does not independently verify semantic assessments.

The skill continues through selection and display without mandatory per-batch checkpoints.
Only a runtime budget warning calls for a checkpoint. Continuation is bounded by
`AGENT_MAX_STEPS` (default 10), not an unbounded background job. A follow-up resumes checkpoint
work. Interrupted runs preserve completed workspace checkpoints and report incomplete coverage;
see [RUNTIME.md](RUNTIME.md#bounded-runs-and-incomplete-results).

The selection policy is two ranked builds first, then two random builds from the remainder:

- Raw score: 30% originality + 25% assignment fit + 25% cognitive augmentation + 20% execution.
- Students in either of the last two recorded issues before the target week are excluded.
- Older appearances multiply scores and sampling weights by `1 / (1 + prior appearances)`.
- Assignment fit >=5 takes precedence over lower-fit builds. Within each tier, rank by adjusted
  score, then assignment fit, then originality. Exact remaining ties use project ID.
- Random draws use operating-system randomness with weighted sampling without replacement.
  All four students are distinct. Fewer than four eligible candidates causes an explicit error;
  cooldown is never silently relaxed. This improves participation, but cannot guarantee every
  student will present, especially when builds are ineligible.

The result exposes raw scores, adjusted scores, evidence, ranking and random selections.
The agent displays a 2×2 thumbnail gallery through `browser.compare` with
`presentation: thumbnails`. Each item links to the verified weekly build page. Prefer a
verified public image found in that page or repository documentation; use the existing
read-only repository tools to resolve dynamic routes, query parameters and asset references.
If no suitable image exists, omit `image_url` and the browser service captures the actual
weekly page, with a screenshot label. The capture remains principal/conversation-scoped and
expires under the existing preview retention policy. A capture failure is reported explicitly.
The gallery stacks on mobile; repair preserves the same four selections.
Drawing does not record a presentation; staff maintain the actual history after finalizing an issue.

### Enter Week 1 selections here

Edit **`class-agent/var/student-showcase/history.json`** (relative to the repository root).
The file is private, ignored by Git, and read afresh per tool call. Use the exact project IDs from
`course.list_student_projects`, rather than ambiguous display names. For example, replace these
illustrative IDs with everyone actually featured in Week 1, whether chosen randomly or by ranking:

```json
{
  "schema_version": 1,
  "issues": [
    {"week": 1, "project_ids": ["agents2026-ada", "agents2026-grace"]}
  ]
}
```

Add one issue per presented week. An empty `project_ids` list records an issue with no presenters;
missing weeks do not count as issues for cooldown. Duplicate weeks or duplicate IDs within an issue
are invalid. A recorded target week cannot be drawn again. Future issues do not affect earlier
selections. All historical appearances count, including ones older than the cooldown.

For a new deployment, create the directory and initialize the file with
`{"schema_version": 1, "issues": []}`, then enter existing selections before using the tool.
Missing/invalid history fails closed instead of pretending nobody has presented. Override the
location with `SHOWCASE_HISTORY_PATH`. Install the real file on the server separately and include
it in protected backups; changing the path requires an API restart, editing history does not.
Keep this file writable only by trusted staff/operators. No agent write tool is exposed.
This is a new version-1 file format, with no changes to existing stable contracts or DB migrations.

The evidence fields are an additive tool-input change; existing post-based requests remain valid.
No persisted history schema or stable interface changes, and no migration is required.

Image discovery uses `staff.discover_showcase_images` after selection and before declaring
imagery unavailable. It reads the registered homepage plus up to three supplied weekly pages
on the same site, accepts up to eight public image references from repository documentation,
and probes extracted candidates through the existing public-image network validator. Probes
run at most four at a time. Results retain page/alt provenance and distinguish failed pages
from empty image lists. Fetchability is verified by code; weekly relevance remains agent-owned.
Verified candidates are registered for `web.inspect_images`. Raw results remain ephemeral.
When repairing a gallery, keep the selected four students and do not reroll.

### Saved reviews and display retries

The first successful selection now writes a private version-1 JSON snapshot to
`selections/week-NN.json` beside `SHOWCASE_HISTORY_PATH`. It contains the submitted
eligibility pool, assignment evidence, rubric scores, current presentation history and
selected four. Exclusive file locking and atomic replacement prevent concurrent requests
from drawing different issues. Subsequent calls reuse this snapshot, across conversations
and restarts, instead of accepting new scores or rerolling. History itself is never written.
This freezes the submitted reviewed pool; it does not certify complete class coverage.

`staff.read_showcase_history` accepts an optional `week` to retrieve that saved review.
Without a week it returns only saved week numbers, keeping reads bounded. Both reading and
selection remain staff-only. Saved repository-derived assessments must remain private;
include this directory in protected backups, never in public resources. Files are created
with owner-only permissions. There is no automatic expiry.

To explicitly refresh an assessment, archive `selections/week-NN.json` outside the selections
directory and rerun the showcase. This deliberately permits a new review and draw. A changed
presentation history or removed roster project blocks reuse until staff perform this refresh.
No existing history migration is required; old deployments start without snapshots.

A selected showcase must finish on the four selected sites in `page-cards` thumbnail mode.
The final presentation review rejects an empty workspace, an unrelated browser page, or a
subsequently replaced gallery. Capture failures retain all four names/links with explicit
unavailable-preview cards and safe reason codes; they are not reported as successful images.

Showcase thumbnails must depict the student's own creation for that week (for example,
a build interface, output, prototype, or project-specific diagram). Direct lecture-slide
images, screenshots and copied lecture diagrams are excluded even if stored in a student
repository or post. The agent evaluates provenance from source context and visual inspection;
image discovery verifies accessibility only and does not certify originality. Screenshot
fallbacks must likewise show the student's work rather than an embedded lecture slide.
Uncertain authorship is disclosed, not treated as verified. This changes thumbnail selection,
not student eligibility, saved rubric scores or the saved four-person draw.
