CREATE TABLE instructor_messages (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    audience text NOT NULL CHECK (audience IN ('all_students', 'specific_students')),
    subject text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 200),
    body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 10000),
    status text NOT NULL CHECK (status IN ('pending_confirmation', 'sent', 'cancelled')),
    created_at timestamptz NOT NULL,
    sent_at timestamptz,
    cancelled_at timestamptz,
    CONSTRAINT instructor_messages_status_timestamps CHECK (
        (status = 'pending_confirmation' AND sent_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'sent' AND sent_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND sent_at IS NULL AND cancelled_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX instructor_messages_one_pending_per_conversation
    ON instructor_messages (conversation_id)
    WHERE status = 'pending_confirmation';

CREATE INDEX instructor_messages_sender_index
    ON instructor_messages (sender_user_id, created_at DESC);

CREATE TABLE instructor_message_recipients (
    message_id uuid NOT NULL REFERENCES instructor_messages(id) ON DELETE CASCADE,
    student_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (message_id, student_user_id)
);

CREATE INDEX instructor_message_recipients_student_index
    ON instructor_message_recipients (student_user_id, message_id);
