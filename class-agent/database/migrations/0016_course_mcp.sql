CREATE TABLE mcp_oauth_clients (
    client_id text PRIMARY KEY,
    client_info jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mcp_oauth_requests (
    request_hash bytea PRIMARY KEY,
    client_id text NOT NULL REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
    redirect_uri text NOT NULL,
    redirect_uri_explicit boolean NOT NULL,
    client_state text,
    code_challenge text NOT NULL,
    scopes text[] NOT NULL,
    resource text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz
);

CREATE TABLE mcp_oauth_codes (
    code_hash bytea PRIMARY KEY,
    client_id text NOT NULL REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redirect_uri text NOT NULL,
    redirect_uri_explicit boolean NOT NULL,
    code_challenge text NOT NULL,
    scopes text[] NOT NULL,
    resource text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE mcp_oauth_tokens (
    token_hash bytea PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('access', 'refresh')),
    family_id uuid NOT NULL,
    client_id text NOT NULL REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scopes text[] NOT NULL,
    resource text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX mcp_oauth_tokens_user_index ON mcp_oauth_tokens (user_id, created_at DESC);
CREATE INDEX mcp_oauth_tokens_family_index ON mcp_oauth_tokens (family_id);
