-- Minimal, pseudonymized Course MCP tool-use telemetry. No prompts, arguments,
-- returned content, access credentials, or direct user identifiers are stored.
CREATE TABLE mcp_tool_usage (
    id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    principal_hash bytea NOT NULL CHECK (octet_length(principal_hash) = 32),
    tool_name text NOT NULL CHECK (char_length(tool_name) BETWEEN 1 AND 80),
    outcome text NOT NULL CHECK (
        outcome IN ('success', 'invalid_tool', 'invalid_input',
                    'permission_denied', 'unavailable', 'execution_error')
    ),
    duration_ms integer NOT NULL CHECK (duration_ms BETWEEN 0 AND 3600000),
    server_version text NOT NULL CHECK (char_length(server_version) BETWEEN 1 AND 64)
);

CREATE INDEX mcp_tool_usage_time_index ON mcp_tool_usage (occurred_at DESC);
CREATE INDEX mcp_tool_usage_principal_time_index
    ON mcp_tool_usage (principal_hash, occurred_at DESC);
