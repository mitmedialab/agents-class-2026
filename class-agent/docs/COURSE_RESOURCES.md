# Phase 6 course resources

## Public catalog

Phase 6 publishes six canonical resources:

```text
course://syllabus
course://schedule
course://repositories
course://faq
course://instructors
course://application
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

To add a resource, create its public content and a sibling `resource.json`. The
manifest's `file` path is relative to its own directory. URI and resolved file paths
must be unique, and files must remain under `shared/`. Private or student-specific
content must never receive a public manifest.

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

## Search refresh

The runtime lexical search reads registered files directly, so content edits are
visible to a running process. PostgreSQL keeps a normalized full-text copy for
server-side inspection and later gateway-backed search. Run the index command after
editing resources when an immediate database refresh is needed without a restart.

Indexing upserts current resources and FAQ entries, removes stale resource rows, and
marks removed seeded FAQ entries inactive. It does not use embeddings.

## Applications

`course://application` is the public guide. The private submission tool accepts a
structured application only after the user explicitly approves it. Required fields are
Name, Email, Department / Research Group / Year of Study MIT, Personal
Webpage, Interests, motivation, Knowledgeable about, Skill-set,
Registration Status, listener commitment to weekly builds, questions or comments, and a
temporary JPEG, PNG, or WebP representative-picture upload for class use only. The
picture can be any image the applicant wants to represent them and need not be a formal
headshot. Missing, blank, placeholder, malformed, expired, and inaccessible values
produce a model-visible validation error naming the fields that still need answers.

The public guide opens with the 20-student capacity, application and notification
deadlines, and the expectation that students build every week, document each build in a
GitHub repository, and show and present the technical implementation in class. The
motivation response covers why the course interests the applicant, what they have built,
what they want to build and why, and their roles in past projects.

Registration Status is a closed six-option combination of affiliation (`MAS student`,
`MIT student`, or `Other student`) and participation mode (`for credit` or `listener`).
The guide and tool contract require the agent to ask for this choice rather than infer
participation mode from a researched affiliation.

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
