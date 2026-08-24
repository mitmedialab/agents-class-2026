CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    user_id uuid REFERENCES users(id) ON DELETE CASCADE,
    anonymous_session_id uuid REFERENCES anonymous_sessions(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    title text,
    archived_at timestamptz,
    CONSTRAINT conversations_exactly_one_owner CHECK (
        num_nonnulls(user_id, anonymous_session_id) = 1
    ),
    CONSTRAINT conversations_title_not_blank CHECK (title IS NULL OR btrim(title) <> ''),
    CONSTRAINT conversations_timestamp_order CHECK (updated_at >= created_at),
    CONSTRAINT conversations_archive_order CHECK (
        archived_at IS NULL OR archived_at >= created_at
    )
);

CREATE INDEX conversations_user_updated_index
    ON conversations (user_id, updated_at DESC)
    WHERE user_id IS NOT NULL;

CREATE INDEX conversations_anonymous_updated_index
    ON conversations (anonymous_session_id, updated_at DESC)
    WHERE anonymous_session_id IS NOT NULL;

CREATE TABLE events (
    id uuid PRIMARY KEY,
    schema_version integer NOT NULL,
    timestamp timestamptz NOT NULL,
    type text NOT NULL,
    actor text NOT NULL,
    principal_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    anonymous_session_id uuid REFERENCES anonymous_sessions(id) ON DELETE SET NULL,
    conversation_id uuid REFERENCES conversations(id) ON DELETE CASCADE,
    node_id uuid,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT events_schema_version_positive CHECK (schema_version > 0),
    CONSTRAINT events_type_not_blank CHECK (btrim(type) <> ''),
    CONSTRAINT events_actor_not_blank CHECK (btrim(actor) <> ''),
    CONSTRAINT events_at_most_one_principal CHECK (
        num_nonnulls(principal_user_id, anonymous_session_id) <= 1
    ),
    CONSTRAINT events_payload_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT events_metadata_object CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX events_conversation_timestamp_index
    ON events (conversation_id, timestamp, id)
    WHERE conversation_id IS NOT NULL;

CREATE INDEX events_principal_user_timestamp_index
    ON events (principal_user_id, timestamp DESC)
    WHERE principal_user_id IS NOT NULL;

CREATE INDEX events_anonymous_timestamp_index
    ON events (anonymous_session_id, timestamp DESC)
    WHERE anonymous_session_id IS NOT NULL;
