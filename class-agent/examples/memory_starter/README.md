# Week 8 student fork setup

The fork includes the published Week 1–8 assignments, including the open-ended
[Week 8 memory and user-modeling build](assignments/week-8/week-8.md). It also
includes a fictional copy of the historical final-project team-formation assignment. The Week 8
group list is omitted here; consult the live Course Agent assignment for your
assigned group. The fork does not include the operational course roster. This
setup creates four active fictional students, one inactive fictional student, an
instructor, and a TA. It publishes protected roster resources and creates matching
local login accounts. Every fictional student has a synthetic project snapshot;
the inactive member's project remains inaccessible through course tools. It uses
no real student records or GitHub repos. Choose your own personalization objective
and approach. The [Week 8 slides](https://cognitive-agents.media.mit.edu/?q=openweek8slides)
offer ideas for possible features. A short, reviewed text summary is also available
to the local agent as `course://week-8-ideas`.

From `class-agent/` in a fresh fork, after installing the tools listed in the
[main README](../../README.md):

```bash
uv sync
pnpm install
docker compose up -d postgres
uv run python examples/memory_starter/setup.py
```

The last command installs the published assignments, fictional user data, and a
fictional weekly feedback file into
ignored local paths, creates `.env`, applies database migrations, indexes public
course resources, enables offline project fixtures in `.env`, and prints a one-time
access code for each fictional account. Save those codes locally; do not commit
them. The setup is safe to rerun with the
same fixtures and refuses to replace an existing roster, gradebook, or different assignments.
Use `--data-only --output-root /path/to/empty/directory` to try the file setup without
connecting to PostgreSQL. A non-default local database may be passed with
`--database-url`; remote database URLs are refused. If `.env` already exists, setup
preserves it; set `STUDENT_PROJECT_FIXTURES_ENABLED=true` there to use the offline
projects.

Add your own `OPENAI_API_KEY` and `BRAVE_API_KEY` to `.env` for the current live
agent runtime. Then use two terminals:

```bash
uv run python -m course_server.api
pnpm dev
```

Open **https://localhost:5173** and accept the local development certificate warning.
Vite already supplies HTTPS and proxies `/api` to the local server. Log in as
`ada-demo`, `bo-demo`, `cy-demo`, or `dee-demo` to develop and compare user behavior.
`eli-demo` is inactive and should be refused by the roster login policy. Use
`teacher-demo` and `ta-demo` to test staff visibility. Access codes print once.
The default Python tests use scripted models and do not require an API key.

The project fixtures under [`projects/`](projects/) provide GitHub-shaped summaries,
trees, files, commits, issues, pull requests, and workflows through the same Course
Agent tools and identity checks as the deployment. `course.inspect_student_site`
reads the matching local site text. The returned `student-fixtures.invalid` URLs
are deliberately non-routable; the generic browser tool cannot open them. Fixture
mode makes no GitHub API request and needs no GitHub token. To test against a real
public repository instead, put it in an organization and repository naming scope
that matches the fictional roster IDs, then configure the separate GitHub integration
with a read-only token. Do not commit tokens or collected profiles.

The [fictional gradebook](grades/weekly-feedback.json) follows the deployment's
private schema: Ada and Bo have different amounts of feedback, Cy has none, Dee is
an active listener, and Eli is an inactive former credit student with historical
feedback. Setup copies it to ignored `var/grades/weekly-feedback.json` with private
file permissions and never replaces different local feedback. Active credit students
can open **Grading** to see graded weekly builds and their own feedback beneath an
assignment; the Course Agent can also read their own notes. Compare Ada, Bo, and Cy
to test different feedback histories. Dee and Eli cannot access grades. See
[gradebook documentation](../../docs/GRADES.md). No actual student's feedback is included.

The historical assignments are reference material; the Week 8 build is the current
task, due Monday, November 9 at 11:59 PM Eastern Time.
