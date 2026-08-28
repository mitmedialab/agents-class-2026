# Shared course resources

Repository-owned public course resources each have a sibling `resource.json` manifest.
The indexer generates `shared/registry/resources.json` from those manifests. Phase 6
includes:

- the official Markdown syllabus;
- a canonical Markdown schedule, parsed into calendar data at render time and explicitly
  marked provisional in its resource manifest;
- Markdown and JSON repository overviews;
- Markdown and JSON FAQ documents;
- instructor and teaching-assistant profiles;
- the public application guide.

Only the file selected by each public manifest and assets explicitly named in that
manifest are exposed to the Course Agent. Registered asset IDs, rather than repository
paths, are used in workspace compositions. Private application submissions and
temporary uploads are stored under `APPLICANT_DATA_PATH` and `UPLOAD_DATA_PATH`, never
in this directory.
