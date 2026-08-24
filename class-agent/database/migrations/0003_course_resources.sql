CREATE TABLE course_resources (
    uri text PRIMARY KEY,
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    media_type text NOT NULL,
    visibility text NOT NULL CHECK (visibility IN ('public')),
    status text NOT NULL CHECK (status IN ('published', 'provisional')),
    source_path text NOT NULL,
    content_sha256 text NOT NULL,
    normalized_text text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'english',
            coalesce(title, '') || ' ' ||
            coalesce(description, '') || ' ' ||
            coalesce(normalized_text, '')
        )
    ) STORED,
    updated_at timestamptz NOT NULL,
    CONSTRAINT course_resources_uri_scheme CHECK (uri LIKE 'course://%'),
    CONSTRAINT course_resources_title_not_blank CHECK (btrim(title) <> ''),
    CONSTRAINT course_resources_media_type_not_blank CHECK (btrim(media_type) <> ''),
    CONSTRAINT course_resources_source_path_not_blank CHECK (btrim(source_path) <> ''),
    CONSTRAINT course_resources_sha256_format CHECK (
        content_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX course_resources_search_index
    ON course_resources USING gin (search_vector);

CREATE TABLE faq_entries (
    id uuid PRIMARY KEY,
    question text NOT NULL,
    answer text NOT NULL,
    source_question_id uuid,
    published_by_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    active boolean NOT NULL DEFAULT true,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(question, '') || ' ' || coalesce(answer, ''))
    ) STORED,
    CONSTRAINT faq_entries_question_not_blank CHECK (btrim(question) <> ''),
    CONSTRAINT faq_entries_answer_not_blank CHECK (btrim(answer) <> ''),
    CONSTRAINT faq_entries_timestamp_order CHECK (updated_at >= created_at)
);

CREATE INDEX faq_entries_active_search_index
    ON faq_entries USING gin (search_vector)
    WHERE active;
