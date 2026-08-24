# Shared course resources

Repository-owned public course resources each have a sibling `resource.json` manifest.
The indexer generates `shared/registry/resources.json` from those manifests. Phase 6
includes:

- the official Markdown syllabus;
- Markdown and JSON schedules explicitly marked provisional;
- Markdown and JSON repository overviews;
- Markdown and JSON FAQ documents;
- instructor and teaching-assistant profiles;
- the public application guide.

Only the file selected by each public manifest is exposed to the Course Agent. Private
application submissions and temporary uploads are stored under `APPLICANT_DATA_PATH`
and `UPLOAD_DATA_PATH`, never in this directory.
