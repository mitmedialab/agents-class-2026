-- Student-owned memories (constitution section 22) and human-confirmed peer introductions.
-- A memory's privacy decides who may read it: 'personal' is visible only to its owner;
-- 'course_private' may also be offered to classmates by the peer-matching tool.

CREATE TABLE memories (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (
        kind IN ('background', 'goal', 'preference', 'project', 'can_help', 'needs_help')
    ),
    content text NOT NULL,
    source_event_ids uuid[] NOT NULL DEFAULT '{}',
    privacy text NOT NULL CHECK (privacy IN ('personal', 'course_private')),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT memories_content_not_blank CHECK (btrim(content) <> ''),
    CONSTRAINT memories_content_bounded CHECK (char_length(content) <= 500),
    CONSTRAINT memories_timestamp_order CHECK (updated_at >= created_at)
);

CREATE INDEX memories_user_updated ON memories (user_id, updated_at DESC);
CREATE INDEX memories_shared_kind ON memories (kind) WHERE privacy = 'course_private';

-- An introduction is drafted by the agent for the requester, sent only by the requester's
-- own click, and answered only by the helper. Declines carry no reason.
CREATE TABLE peer_introductions (
    id uuid PRIMARY KEY,
    requester_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    helper_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic text NOT NULL,
    message text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('draft', 'sent', 'accepted', 'declined', 'cancelled')
    ),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    sent_at timestamptz,
    responded_at timestamptz,
    CONSTRAINT peer_introductions_distinct_people CHECK (requester_user_id <> helper_user_id),
    CONSTRAINT peer_introductions_topic_bounded CHECK (
        btrim(topic) <> '' AND char_length(topic) <= 200
    ),
    CONSTRAINT peer_introductions_message_bounded CHECK (
        btrim(message) <> '' AND char_length(message) <= 2000
    ),
    CONSTRAINT peer_introductions_timestamp_order CHECK (updated_at >= created_at)
);

CREATE INDEX peer_introductions_requester ON peer_introductions (requester_user_id, created_at DESC);
CREATE INDEX peer_introductions_helper ON peer_introductions (helper_user_id, created_at DESC);
