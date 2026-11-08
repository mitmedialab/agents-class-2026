-- User-owned agent memories, separate from conversation events. Content is sent to
-- the model provider on that user's runs.
CREATE TABLE user_memories (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    kind text NOT NULL CHECK (char_length(kind) BETWEEN 1 AND 80),
    content text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 2000),
    source_event_ids uuid[] NOT NULL DEFAULT '{}',
    privacy text NOT NULL CHECK (privacy IN ('personal', 'course_private')),
    metadata jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX user_memories_user_time_index ON user_memories (user_id, updated_at DESC);
