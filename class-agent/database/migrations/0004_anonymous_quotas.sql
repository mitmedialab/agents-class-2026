CREATE TABLE anonymous_quota_usage (
    session_id uuid NOT NULL REFERENCES anonymous_sessions(id) ON DELETE CASCADE,
    metric text NOT NULL CHECK (
        metric IN ('conversations', 'agent_runs', 'uploads', 'upload_bytes')
    ),
    used bigint NOT NULL CHECK (used >= 0),
    PRIMARY KEY (session_id, metric)
);
