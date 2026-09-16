CREATE TABLE notification_item_reads (
    item_id uuid NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at timestamptz NOT NULL,
    PRIMARY KEY (item_id, user_id)
);

CREATE INDEX notification_item_reads_user_index
    ON notification_item_reads (user_id, read_at DESC);
