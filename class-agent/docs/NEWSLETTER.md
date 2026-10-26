# The Class Runtime: instructor-run weekly newsletter

The newsletter is a Course Agent capability for instructors, and also a staff command. An
instructor can ask the Course Agent to draft, review, and send the week's issue, or run
`python -m course_server.newsletter` directly; both paths run the same deterministic pipeline. It
never runs for students, and nothing is emailed until the instructor approves it in the platform's
confirmation surface.

## Through the Course Agent

The `instructor-newsletter` skill (audience `instructors`) teaches the agent the workflow, and
platform code exposes three tools only to authenticated instructors:

| Tool | What platform code does |
| --- | --- |
| `instructor.draft_newsletter` | Starts a background draft job (about five minutes) for the last finished week, or a given week. Returns a job id; the agent tells the instructor to ask again shortly. |
| `instructor.newsletter_status` | Reports the latest or a named job, and once it is done returns the draft: headline, editorial, highlights with students and reasons, the closing quote, the scoreboard, and the HTML/PDF/text file paths. The agent presents this faithfully and never rewrites the copy. |
| `instructor.send_newsletter` | Freezes a recipient snapshot (every active student account plus `NEWSLETTER_RECIPIENTS`, or the named test addresses) and emits `instructor.newsletter.confirmation_requested`. The web app shows a Send or Cancel card. |

Send marks the issue `approved` through
`POST /api/v1/conversations/{conversation_id}/newsletter/{issue_id}/confirmation`, which checks the
instructor login, conversation ownership, and the confirmation id; the mail worker then delivers the
approved issue to its snapshot on its next cycle and marks it `sent`. Cancel returns the issue to
`draft`. The agent does not choose the highlights, write the copy, or pick the recipients; those
remain the pipeline's and the instructor's decisions. Job records live under
`var/newsletter/jobs/` and issues carry their approval snapshot, so the status is inspectable from
files as well as from the agent.

## On the course site and through the Course Agent

Every sent issue is a public course resource, and a draft is not: a draft is the instructor's
until it is delivered. `NewsletterResourceCatalog` (`python/course_server/newsletter/resources.py`)
wraps the registered resource catalog the way the published FAQ does and adds, at request time,
`course://newsletter` (every sent issue, newest first, with a link to each) and one
`course://newsletter/<issue_id>` per sent issue, both `text/markdown`. An issue appears as soon as
the mail worker marks it `sent`; no restart or re-indexing is needed. The catalog is installed in
the API and the agent CLI whenever the newsletter settings load, so sent issues are readable even on
a deployment that does not draft (no GitHub token).

An issue's Markdown is `render_markdown` in `render.py`: the same sections as the email, every link
active, and each highlight image referenced by its registered asset id (the project id folded into
the asset-id form, `agents2026-ada` becomes `agents2026_ada`). Model- and repository-supplied text
is escaped so it cannot become Markdown structure; links are only the platform-resolved URLs. The
issue's assets are its highlight images, the masthead wordmark as `logo` (also the list's only
asset), and, when the single-page export exists, `pdf`, all served through the authorized
`/api/v1/course/resources/asset` route by id. Both pages begin with the wordmark; on the list it
stands in for the title.

The web app shows them under **Newsletters** in the header: `/newsletter` is the list of issues
and `/newsletter/<issue_id>` one issue, rendered by the same course-document page as About, with
figures, the closing quote, a **Download issue PDF** control, and in-app links between the list
and its issues. The pages are public, like the About page.

The Course Agent sees the same resources: `course://newsletter` and each issue are listed among the
public course files, readable with `course.read_public_file`, found by `course.search`, and can be
opened in the workspace's document viewer, which resolves the image ids through the same asset
route. The `course-help` skill points the agent at them for questions about the newsletter or what
the class built in a given week. The agent never sees drafts through these resources; the
instructor tools above remain the only way to read a draft.

## From the command line

## What an issue contains

Every issue follows the same skimmable shape:

1. A punny headline about the main topic of the week's assignment, the week's dates, the
   assignment itself, and an editorial of up to 150 words on how the class did against what was
   taught. The headline is written against the assignment as the class received it: the
   published assignment record whose deadline falls in the week's window (see "Data sources").
   It must use at least one term from that record's title (another form of the word counts,
   such as "design" for "designing"); code rejects one that uses none and feeds the title's
   terms back to the model. When no record covers the week, the schedule's assignment line and
   topic stand in, and the draft log says so. The editorial call
   receives that assignment text, the text of that week's slide deck from
   `shared/course/slides/week-NN/`, and the syllabus learning goals alongside the anonymized
   staff notes on every submission that made something that week, and writes two paragraphs.
   The first is a synthesis of how the class answered the assignment: the two or three
   approaches that recurred across the builds (in a week on interfaces, which form factors
   people chose, what the agent notices, when it speaks up), not a tour of builds, since the
   highlights and the full list describe each one. Builds may appear there only as examples of
   an approach, linked to the student's site: code rejects more than three build links or more
   than two sentences that point at a build. The second paragraph names the blind spots
   (lecture ideas the submissions missed or misapplied) and common blockers, framed as what to
   practice next. The editorial never names a student and never counts who submitted; code
   rejects names, participation tallies, overlong copy, and dense prose
   (average sentence over 18 words, any sentence over 26, semicolons, or a Flesch reading ease
   below 50), feeding the exact problem back to the model. The second paragraph is read by students
   who have not seen the other builds yet, so code also rejects an editorial that is not exactly
   two paragraphs, a second paragraph that links to any student's build, and any sentence there
   with more than one comma. It may add up to two external reference links in Markdown form;
   each URL is checked to resolve before it is accepted.
2. Four highlights (configurable). Each one shows an image from the student's own post, names
   the student, and gives a headline plus two sentences: what the build is and what makes it
   interesting, then specifically how it does what the assignment asked. The student's name is
   printed beside the headline, so code rejects a description whose sentence opens with that
   name as if the student were the tool ("Ada helps you..."); the build is the subject. A link
   opens the student's post for the week. Links always go somewhere that renders on its own: a post that is
   only an HTML fragment shown inside the site's shell links to the site instead, at
   `#<the post's file name>` (a shell that loads posts by name opens it from there; any other
   site shows its home page), and when only
   the browser can find the post (a script-built menu), the highlight links to the post page the
   image finder reached. After the last highlight, one line ("How the Course Agent chooses what to
   highlight") links to `https://cognitive-agents.media.mit.edu/?q=newslettercriteria`, which
   opens the course site and sends that query to the Course Agent as the student's first
   message; the agent answers from the course FAQ (see below).
3. Every other student who posted work that week, with one sentence on what they built that
   week and a link to that week's post. Both the list and the sentence are about the week, not
   the site: a student is considered only when something points at this week's work (files in
   the week's folder, commits in the week's window, or site files named for the week), so a
   site that was not touched this week does not put its owner on the list. The scorer then
   marks a submission `blank` when the evidence shows nothing made for this week's assignment:
   an untouched or lightly edited starter site, a welcome or about page, an empty folder, a
   placeholder post, or only earlier weeks' work and final-project ideas. Blank submissions are
   left off the list and are never featured; a plan, a concept page, or a partial or broken
   build still counts. The instructor scoreboard flags blank rows.
4. A closing quote. Preferably a line from a student's own post that week, featured or not: the
   scoring pass asks each project for up to three sentences with personality (surprising, funny,
   candid, vivid; never a definition), code verifies each appears verbatim in that student's
   collected prose, and the editorial call picks the one with the most personality, attributed and
   linked to the student's site. When no verified candidate exists, a curated quote from an AI or computing
   pioneer is used instead, rotated across issues.
5. A colophon, in this order: the credit ("This newsletter was created by The Course Agent"),
   then the course line (`MAS.S60 · AI Agents for Cognitive Augmentation · MIT, Fall 2026`), and
   last the class website, `cognitive-agents.media.mit.edu`.

The email subject is `NEWSLETTER_SUBJECT` followed by the issue number the masthead prints, for
example `The Class Runtime from MAS.S60 · Issue 02`. It is fixed when the draft is made and
stored with the issue. Each message is sent as plain text with an HTML alternative. The HTML keeps the course site's black ground and ivory Helvetica, with
section labels ("The assignment", "How the week went") set small, sentence-case and medium
weight. Secondary text is near-white rather than the site's muted grey, which reads as a
watermark in an inbox; levels are separated by size and weight instead of by dimming. The
assignment label and sentence are set one step greyer (`#d6d6d0`, the same light
grey as the dates) so they read as context under the headline.

The Gmail apps recolor dark emails when the phone is in dark mode: plain backgrounds are
lightened and light text is darkened. The renderer counters both. The ground and the section
rules are painted with flat `linear-gradient`s, which Gmail leaves alone. Every run of text sits
inside a pair of inline `mix-blend-mode` wrappers (`screen` around `difference`) that cancel
Gmail's text transform and composite to the original pixels in every other client. Images stay
outside the wrappers, because a difference blend would invert them.

The wrappers must be inline. A diagnostic email read in the Gmail iPhone app in dark mode kept
white text white only with inline blend wrappers, gradient-clipped text, or text inside an
image. The same wrappers applied from a stylesheet through Gmail's `u + .body` selector had no
effect there, and neither did color keywords, `<font>` tags, or `!important`. Every variant
rendered correctly in Gmail on the web. Link underlines use a mid grey, which looks the same
whether or not a client also recolors border colors inside the wrappers.

Mac Mail adapts messages to its own light or dark setting with a WebKit color filter that
flips the lightness of every CSS color but leaves images alone, so the white text turned dark.
The email opts out twice: it declares support for both schemes (`color-scheme: light dark` in the
meta tags and CSS), and it sets `-apple-color-filter: none` on every element. Only dark colors are
defined, so both declarations keep the same dark design. In a Mac Mail test each guard worked on
its own; both stay for robustness, and other clients ignore the filter property.

## How highlights are chosen

Every active project is scored, one model call each, from its bounded evidence against a fixed
rubric of four criteria, each 0 to 10:

| Criterion | Key | Weight | What it asks |
| --- | --- | --- | --- |
| Originality | `originality` | 30% | How far outside the box the idea and approach are: an unexpected problem, domain, or mechanism, ambition, surprising findings. The tutorial's default example re-skinned scores 4 or below. |
| Assignment fit | `goal_fit` | 25% | Whether the student did what the week's assignment asked, not something adjacent. Missing its core scores 3 or below. |
| Cognitive augmentation | `augmentation` | 25% | How directly the build helps a person think, remember, learn, focus, decide, or create while staying in charge. A build that helps no person scores 2 or below. |
| Execution | `execution` | 20% | Whether it works and the post shows it (demo, trace, write-up); honest failure analysis counts in its favor. |

The rubric is defined once, as `RUBRIC` in `score.py`: the scoring prompt, the JSON schema, the
weights, and the instructor scoreboard all read it. Originality absorbed the earlier `interest`
criterion, and issues scored before the change still load (their `interest` becomes
`originality`, with no augmentation score). The same call produces the staff notes reused everywhere else: one sentence on what the student built, what
went well, and what they struggled with. The editorial and headline are written from those notes
across the whole class, so the model reads every submission before it writes a word. Platform
code computes the weighted total, ranks every project with an assignment fit of at least
`MIN_GOAL_FIT` (5) ahead of every project below it, excludes students featured in the last
`NEWSLETTER_HIGHLIGHT_COOLDOWN_ISSUES` sent issues (default 1: only the previous issue's
featured students sit out), breaks ties by assignment fit, then
originality, then cognitive augmentation, then project id, and takes the top
`NEWSLETTER_HIGHLIGHT_COUNT`. The model then writes copy for exactly those projects in that
order; a response that changes the set or order is re-prompted once and then rejected. The full
scoreboard with rationales is stored in the issue and printed by `draft` and `show`, so the choice
is inspectable.

Each issue's selection link asks the Course Agent, which answers from a staff-approved FAQ entry
on how highlights are chosen; keep that entry in step with these rules. The same rules, in plain
language, are also on the course site at `/newsletter/highlights`. That page is the public course
resource `course://newsletter-highlights`
(`shared/course/newsletter/highlights.md`), rendered by the web app with the syllabus page's
component, so the Course Agent can also answer questions about it. A test checks that its
criteria, weights, questions, goal-fit floor, cooldown, and highlight count match the code; change
both together.

## Highlight images

For each featured build the finder opens the student's site in headless Chromium (the same
Playwright dependency the agent's browser uses; `BROWSER_EXECUTABLE_PATH` is honored when it
exists), goes to the student's post (the one evidence collection found, then same-site links that
name the week), and measures the visual
elements rendered there: images, SVG figures, canvases, and videos. Before measuring, the page
settles the way it would for a visitor: lazy images are loaded by scrolling, web fonts are awaited,
and images that failed to load are skipped. Visible elements at least 280 by 140 CSS pixels with a
sane aspect ratio are candidates, largest first, and each is captured at 2x as its own element
screenshot, so vector figures and live canvases work as well as photos. A video with a poster
contributes the poster itself, fetched at full size, because it is the frame the student chose;
otherwise a decoded frame is captured. Some sites publish each week as an HTML fragment that
their script loads into a styled shell (with relative media paths that only resolve against the
site root). Such a fragment is read inside a minimal document whose base is the site root, as the
site reads it, and is never screenshotted bare; if it offers no usable visual, the fallback is
the styled site root. The model picks the capture that best represents the build (rendered results, demos, diagrams over
logos, icons, and portraits). The chosen capture is flattened onto black, downscaled to 1200 pixels
wide, encoded as JPEG, stored beside the issue with its source and page URL, and embedded in the
email as an inline `cid:` image. Root-page visuals are considered only when the site has no week post. When a post
has no usable visual, the week page (or, on single-page sites, the week section) is captured
instead and recorded as a screenshot. A site that cannot
be inspected is skipped and noted in the draft log; the highlight is still written.

## Where each decision lives

| Decision | Owner |
| --- | --- |
| Which week is "last week", and its assignment goal | Platform code, parsed from `shared/course/schedule/schedule.md` |
| Which repositories exist and what can be read | The existing read-only GitHub catalog (`mitmedialab/agents2026-*`) |
| Which projects are eligible to be featured | Platform code: the project changed something during the week and was not featured in the last `NEWSLETTER_HIGHLIGHT_COOLDOWN_ISSUES` sent issues |
| Rubric scores and notes per project, the editorial, the prose, the image choice among measured candidates | The configured model, from bounded evidence |
| Weights, goal-fit floor, ranking, cooldown, final selection and order | Platform code (`score.py`) |
| Highlight set/order, editorial length, brevity limits, link-free prose, no staff vocabulary ("brief", "rubric", "score") | Validated in code; a violating response is re-prompted once with the concrete problems, then rejected |
| Links, project list, quote, footer, HTML escaping, image fetching and re-encoding | Platform code; the model cannot add links, addresses, or image URLs |
| Whether anything is emailed, and to whom | The instructor, at `send` time |

The model receives only the week's assignment text, repository names, derived labels, deployed
site URLs, commit subjects,
bounded Markdown/text documents and notebook prose from `weekly_builds/weekNN/` and from site
files named for the week, and bounded deployed site text.
It does not receive credentials, student email addresses, or account data.

## Data sources and bounds

For each course repository the collector reads, through the existing catalog:

- the week's assignment record: the published record under `ASSIGNMENT_DATA_PATH` (default
  `var/assignments/`, one file per assignment, directly or one folder down) whose deadline falls
  inside the week's window, capped at 14,000 characters. This is the deployment's own store
  (`docs/ASSIGNMENTS.md`), so a draft made on the server reads the live record. A draft made
  anywhere else must copy the server's `var/assignments/` first; the draft log names the
  record and revision it used, or says that none was found;
- the recursive tree, to count files under `weekly_builds/weekNN/` and `website/`, and to
  note the `website/` files whose path names the week (`rooms/week03.html`,
  `docs/week03/part-1.md`);
- up to six `.md`, `.txt`, or `.rst` documents and `.ipynb` notebooks, the week's folder first
  (shallowest and README first) and then the site files named for the week, each capped at
  4,000 characters and 9,000 characters per project. Only a notebook's Markdown cells are
  read, by scanning, so a notebook the catalog cut off at its size cap still yields its prose;
- the 30 most recent commits, filtered to the week's window (class day through the day before the
  next class, in `NEWSLETTER_TIMEZONE`);
- the deployed site's readable text, capped at 2,500 characters, using the same public-network
  fetch rules as the agent's web tools;
- the student's post for the week, capped at 5,000 characters: the first same-site link in the
  served HTML that names the week. When the served HTML names none, the published page named
  for the week among the site's files is used (a week folder's own index first, then the
  shallowest path), because a page can exist without the home page linking it. Failing that,
  because the site's script builds its menu or fills in its posts, the site root is opened in
  headless Chromium and the rendered link is followed; on a single-page site that link is a
  `#week-NN` section the script opens. The post's visible text is read there. That post is
  also the student's link in the issue, and the page the image finder starts from.

Credential-like paths are refused by the catalog before any content is requested. One unreadable
repository or site is noted in the evidence and does not stop the draft.

## Commands

```bash
# Draft the most recently finished week (run from class-agent/ with .env configured).
uv run python -m course_server.newsletter draft

# Draft a specific week, or pretend today is a given date when choosing the week.
uv run python -m course_server.newsletter draft --week 1
uv run python -m course_server.newsletter draft --as-of 2026-09-22

# Review a stored issue again, as text or HTML, or export a single-page PDF to share.
uv run python -m course_server.newsletter show 2026-week01
uv run python -m course_server.newsletter show 2026-week01 --html
uv run python -m course_server.newsletter pdf 2026-week01
uv run python -m course_server.newsletter list

# Send yourself a test copy; the issue stays a draft.
uv run python -m course_server.newsletter send 2026-week01 --test-to you@mit.edu

# Approve and send. Recipients are NEWSLETTER_RECIPIENTS plus --to plus, optionally, every
# active student account. The command prints the full text and recipient list, then waits
# for you to type SEND. Pass --yes only in a scripted context.
uv run python -m course_server.newsletter send 2026-week01 --to-active-students
uv run python -m course_server.newsletter send 2026-week01 --to list@example.edu --yes
```

If the draft is not right, edit nothing by hand. `rewrite <issue>` regenerates the headline,
editorial, highlight copy, and quote while keeping the selection, scores, and images (two model
calls); `draft --week N` starts over, re-scoring the class. A week that was already sent is refused
unless `--force` is passed, which produces a fresh draft.

Drafting requires `GITHUB_STUDENT_PROJECTS_ENABLED=true`, a read-only `GITHUB_TOKEN`, and the
model settings used by the agent. Sending requires the same `MAIL_*` settings as the mail worker;
`--to-active-students` also requires `DATABASE_URL`. `show` and `list` need neither.

Like the other CLIs, the command loads `.env` without overriding variables already exported in
the shell. If a stale `OPENAI_API_KEY` is exported, the model request fails with
`AuthenticationError`; run `unset OPENAI_API_KEY` first so the `.env` value is used.

## Masthead

The wordmark at the top of every issue is `shared/course/newsletter/newsletter-logo.png`
(`NEWSLETTER_LOGO_PATH` overrides it). The store writes an email-sized copy beside each issue, the
HTML preview references it relatively, and the email embeds it as an inline `cid:` image like the
highlight images.

## Storage

`NEWSLETTER_DATA_PATH` (default `var/newsletter/`, ignored by Git) holds `issues/<year>-weekNN.json`
plus `.txt`, `.html`, and `.pdf` renderings for review (the PDF is one tall page rendered by headless
Chromium, produced after each draft and on demand with `pdf`), and
`issues/<year>-weekNN/<project>.jpg` images that the `.html` preview references relatively, so it
opens correctly in a browser. The JSON record stores the week, the validated
model copy, the project roster with links, the quote, status (`draft` or `sent`), and one delivery
row per recipient with the provider message ID or the sanitized error class. Sent issues are the
source of the fairness rule and of quote rotation, and of the public `course://newsletter`
resources, so keep this directory in staff backups. The API reads only sent issues from it, by
validated issue id; the `.pdf` is served as the issue's `pdf` asset when it exists.

Each recipient receives a separate message; other recipients' addresses are never included.
Provider acceptance is recorded per recipient. A failed recipient is recorded and the issue stays a
draft only if nobody received it; re-running `send` on a sent issue is refused.

## Cost and failure behavior

Each draft makes one scoring request per active project, one editorial request, one image-choice
request per featured build with candidates, and one highlight-copy request (each text request is
retried once if the response breaks a rule), plus a few
hundred GitHub reads across the class and one headless browser session per featured build. The `draft` command prints the total requests and input/output tokens it used; a week-1 run with 27 active projects used about 32 requests, 78,000 input tokens, and 11,000 output tokens, roughly $0.30 at GPT-5.6 Terra prices. Provider failures
surface as sanitized errors without response bodies. No newsletter code runs inside the API
process or the Course Agent runtime.
