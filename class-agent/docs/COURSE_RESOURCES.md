# Phase 6 course resources

## Public catalog

The maintained public catalog currently includes:

```text
course://syllabus
course://schedule
course://repositories
course://faq
course://instructors
course://application
course://slides/week-01
```

Each published file has a `resource.json` sidecar under `shared/course/`. The sidecars
are the editable source of truth for URI, title, description, media type, visibility,
publication status, display order, and the file to expose. The generated
`shared/registry/resources.json` is retained as a portable catalog artifact; do not edit
it by hand.

A sidecar may also declare an `assets` object that maps stable asset IDs to files
relative to the sidecar. Asset paths are confined to `shared/`, validated as existing
files, and copied into the generated registry alongside the primary resource path.
Reading a resource returns its asset IDs and media types to the Course Agent without
revealing repository paths. The browser resolves those IDs through the authorized
`/api/v1/course/resources/asset` endpoint; model-controlled input never selects a file
path. For example, the staff resource exposes its portraits as registered image assets,
so a profile composition can use them directly instead of searching the public web.
Staff portrait asset IDs follow `<normalized_display_name>_portrait`. The notification center
applies that convention to an authenticated reply sender and uses the portrait only when the
resulting asset is present in `course://instructors`; otherwise it keeps the semantic type tile.
This preserves a data-owned image catalog without maintaining a second person-to-file mapping in
application code.

To add a resource, create its public content and a sibling `resource.json`. The
manifest's `file` path is relative to its own directory. URI and resolved file paths
must be unique, and files must remain under `shared/`. Private or student-specific
content must never receive a public manifest.

For a public course slide deck, use one directory per deck:

```text
shared/course/slides/week-01/
├── resource.json
└── week-01-slides.pdf
```

```json
{
  "schema_version": 1,
  "resource": {
    "uri": "course://slides/week-01",
    "title": "Week 1 Slides",
    "description": "Slides for the first course meeting.",
    "media_type": "application/pdf",
    "file": "week-01-slides.pdf",
    "visibility": "public",
    "status": "published",
    "order": 100
  }
}
```

The side panel's **Lecture Slides** section derives published PDF decks from authorized
`course://slides/week-NN` resources and labels them Lecture 1, Lecture 2, and so on,
ordered by descending lecture number. Add each new PDF and sidecar using this convention;
restart the backend to index and load the updated catalog. No frontend list needs editing.
Indexing generates a content-addressed `first_slide` PNG asset for every published slide PDF
under `shared/registry/slide-thumbnails/`. The panel loads these small first-page previews through
the existing authorized asset endpoint. New or changed PDFs regenerate their thumbnails automatically.
Slides appear only in **See more**, stay available after opening, and do not create unread
alerts or greeting reminders.

PDF indexing extracts embedded text by page for Course Agent reads and search while retaining the
original bytes for the workspace's `document-viewer`. Image-only or scanned slides still render
and the agent can inspect the focused page visually on demand through the authorized
`document.inspect_page` tool, but they require a separate OCR workflow before their contents are
searchable. The renderer receives only registered course bytes or a principal-owned temporary
upload; rendered PNG bytes are ephemeral and are not stored in conversation history.

`course_server.index_resources` regenerates the catalog from every sidecar manifest,
then synchronizes the searchable PostgreSQL copy. Production API and Course Agent CLI
startup run this command automatically after migrations, so a normal backend restart
picks up added, moved, and removed manifests. It is also safe to run explicitly:

```bash
uv run python -m course_server.index_resources
```

The schedule remains `provisional` until dates and details are confirmed.
`shared/course/schedule/schedule.md` is its only content source. The Calendar's trusted
Markdown parser derives normalized events when the resource is opened, so schedule edits
do not require maintaining or regenerating a second schedule JSON file. The Course Agent
and lexical search read that same Markdown through the authorized `course://schedule`
resource.

## Release notes and generic resource deadlines

Any public or protected resource manifest may add optional notification metadata:

```json
{
  "announcement": {
    "revision": "assignment-1-v1",
    "published_at": "2026-09-05T12:00:00-04:00",
    "summary": "Assignment 1 is now available to enrolled students."
  },
  "deadline": {
    "kind": "course_event",
    "due_at": "2026-09-19T23:59:00-04:00"
  }
}
```

`revision` is a stable release identifier. Change it when a meaningful new release or course edit
should create a fresh unread item; do not use filesystem modification time. The notification center
derives a deterministic item ID from the registered URI and revision, and shows it only to
principals already authorized for that resource. The optional deadline appears during the fourteen
days before `due_at`. The resource remains the content source, while the manifest owns only
release/deadline metadata; React and prompts contain neither maintained course content nor due dates.
Public indexing copies these optional fields into the generated registry. Protected resources
retain them only in their server-owned sidecars.

Structured course assignments do not live in resource manifests. Their canonical records are one
validated JSON file each under `ASSIGNMENT_DATA_PATH`, defaulting to `var/assignments/`. They have
their own agent read/authoring tools and independently drive release and upcoming notifications. See
[ASSIGNMENTS.md](ASSIGNMENTS.md). Manifest deadlines remain useful for non-assignment course events
and for deployments that already maintain generic resource deadline metadata.

## Search refresh

The runtime lexical search reads registered files directly, so content edits are
visible to a running process. PostgreSQL keeps a normalized full-text copy for
server-side inspection and later gateway-backed search. Run the index command after
editing resources when an immediate database refresh is needed without a restart.

Indexing upserts current resources and seeded FAQ entries, removes stale resource rows, and
marks removed seeded FAQ entries inactive. Staff-approved database FAQ entries have a
`source_question_id` and remain available for workflow and notification bookkeeping. The
agent-facing `course://faq` overlay and lexical search read staff-approved updates from the separate
local `PUBLISHED_FAQ_PATH` JSON file. Resource indexing never edits or imports that file. It does
not use embeddings.

The public FAQ capability distinguishes browsing from search. The Course Agent can list recent
staff-approved Q&A additions and read one by its opaque public entry ID without supplying a topic;
`course.search_faq` remains available for topic-specific retrieval. Only active entries from the
public knowledge file appear in either path.

## Role-scoped resources

`COURSE_DATA_PATH` defaults to `data/` and contains `students/` and `instructors/`.
Protected contents are not part of `shared/course`, the generated public registry, or the
PostgreSQL public search index. Production should point this setting at a protected
server-owned directory outside the Git checkout.

Every readable file requires a sibling `resource.json`. Student manifests use a
`course://students/...` URI and `visibility: students`; instructor manifests use a
`course://instructors/...` URI and `visibility: instructors`. The loader verifies that the
manifest audience matches its directory, confines files and assets to that audience root,
and rejects duplicate URIs. Directory placement alone never publishes a file.

Students can list, search, read, and display student resources after login. Instructors can
do the same for both audiences. Anonymous, TA, and admin principals receive neither set.
The API and agent capability catalog use the same trusted-principal policy. Private tool
results use summary-only durable storage, and protected HTTP responses use `no-store`.

## Applications

`course://application` is the public guide. The private submission tool accepts a
structured application only after the user explicitly approves it. Required fields are
Name, Email, GitHub ID, School, Department, Research group, Degree, Year of degree
start, Personal Webpage, Interests, motivation, Knowledgeable about, Skill-set,
Registration, conditional listener commitment to weekly builds, questions or comments,
and a temporary JPG/JPEG, PNG, or WebP representative-picture upload for class use only.
The picture can be any image the applicant wants to represent them and need not be a
formal headshot. Missing, blank, placeholder, malformed, expired, and inaccessible
values produce a model-visible validation error naming the fields that still need answers.

The public guide opens with the 20-student capacity, application and notification
deadlines, and the expectation that students build every week, document each build in a
GitHub repository, and show and present the technical implementation in class. The
motivation response covers why the course interests the applicant, what they have built,
what they want to build and why, and their roles in past projects.

School is one of `MIT Media Lab`, `MIT`, `Harvard`, `Wellesley`, or `Other`.
Registration is independently one of `for credit` or `listener`. Listeners must answer
`yes` or `no` about completing weekly builds; for-credit applicants record
`not applicable`. The year field is the four-digit year the applicant started the
degree, not their current year of study. Applicants without a GitHub account must create
one before continuing.

Temporary uploads are principal-scoped, expire after 24 hours, and default to
`var/uploads/`. A successful submission copies the selected photo into a durable,
private application directory beside `application.json`. Configure production paths
with:

```dotenv
UPLOAD_DATA_PATH=/srv/class-agent/uploads
APPLICANT_DATA_PATH=/srv/class-agent/applicants
```

Neither directory may be web-served or registered as a public resource. Restrict staff
access, include the applicant directory in encrypted backups, and define application
and upload retention policies before accepting real applications. The service validates
image type and file signature; it intentionally does not perform face recognition.
Authenticated instructors may explicitly ask the Course Agent to inspect selected application
images. That bounded operation sends the selected private bytes to the configured multimodal
provider with provider storage disabled; ordinary application reads expose metadata only.
For an instructor-visible gallery, the tool returns opaque applicant image URIs that the trusted
web client resolves through an authenticated no-store endpoint. The private directory itself is
never mounted or exposed as static content.

Application sharing update: authenticated students may use the existing application-review
tools and photo route only for accepted application UUIDs explicitly shared in the private
`student-access.json` registry. Instructor access remains unrestricted. See
[STORAGE.md](STORAGE.md) for authorization, provisioning, and revocation details.

## Syllabus PDF download

`syllabus.md` remains the maintained syllabus source. Its sidecar registers `syllabus.pdf`
as the `pdf` asset. Both the About page and a Markdown DocumentViewer offer the same
registered download through the existing authorized asset endpoint.

After editing the syllabus, regenerate the PDF from the running frontend's syllabus renderer
and print styles, review its pages, then refresh the resource catalog:

```bash
uv run python -m course_server.export_syllabus --web-url https://localhost:5173
uv run python -m course_server.index_resources
```

The export uses installed Playwright Chromium by default. For local development with system
Chrome and Vite's self-signed certificate, add `--browser-channel chrome --ignore-https-errors`.
The exporter intercepts only the syllabus-content read with current repository Markdown, so
it does not accidentally export stale API content. A regression test compares the PDF's text
with the maintained Markdown and rejects empty pages. No PDF generation occurs on user downloads.
