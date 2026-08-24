CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id uuid PRIMARY KEY,
    username text NOT NULL,
    display_name text NOT NULL,
    email text NOT NULL,
    role text NOT NULL CHECK (role IN ('student', 'ta', 'instructor', 'admin')),
    access_code_hash text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT users_username_not_blank CHECK (btrim(username) <> ''),
    CONSTRAINT users_display_name_not_blank CHECK (btrim(display_name) <> ''),
    CONSTRAINT users_email_not_blank CHECK (btrim(email) <> ''),
    CONSTRAINT users_timestamp_order CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX users_username_normalized_unique ON users (lower(username));
CREATE UNIQUE INDEX users_email_normalized_unique ON users (lower(email));

CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CONSTRAINT auth_sessions_expiry_after_creation CHECK (expires_at > created_at),
    CONSTRAINT auth_sessions_last_seen_after_creation CHECK (last_seen_at >= created_at),
    CONSTRAINT auth_sessions_revoked_after_creation CHECK (
        revoked_at IS NULL OR revoked_at >= created_at
    )
);

CREATE INDEX auth_sessions_user_id_index ON auth_sessions (user_id);
CREATE INDEX auth_sessions_expires_at_index ON auth_sessions (expires_at);

CREATE TABLE anonymous_sessions (
    id uuid PRIMARY KEY,
    token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CONSTRAINT anonymous_sessions_expiry_after_creation CHECK (expires_at > created_at),
    CONSTRAINT anonymous_sessions_last_seen_after_creation CHECK (last_seen_at >= created_at),
    CONSTRAINT anonymous_sessions_revoked_after_creation CHECK (
        revoked_at IS NULL OR revoked_at >= created_at
    )
);

CREATE INDEX anonymous_sessions_expires_at_index ON anonymous_sessions (expires_at);

CREATE TABLE auth_login_failures (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rate_limit_key_hash bytea NOT NULL,
    attempted_at timestamptz NOT NULL
);

CREATE INDEX auth_login_failures_lookup_index
    ON auth_login_failures (rate_limit_key_hash, attempted_at DESC);
