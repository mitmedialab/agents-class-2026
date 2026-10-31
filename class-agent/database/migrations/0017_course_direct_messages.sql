-- Human-confirmed course messages. MCP creates drafts; only the website can send.
-- One recipient per message keeps reply ownership and email delivery unambiguous.
CREATE TABLE course_direct_messages (
    id uuid PRIMARY KEY,
    sender_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    recipient_user_id uuid REFERENCES users(id) ON DELETE RESTRICT,
    recipient_kind text NOT NULL CHECK (recipient_kind IN ('user', 'course_staff')),
    reply_to_message_id uuid REFERENCES course_direct_messages(id) ON DELETE SET NULL,
    reply_to_instructor_message_id uuid REFERENCES instructor_messages(id) ON DELETE SET NULL,
    reply_to_question_id uuid REFERENCES ta_questions(id) ON DELETE SET NULL,
    subject text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 200),
    body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 10000),
    status text NOT NULL CHECK (status IN ('pending_confirmation', 'sent', 'cancelled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    sent_at timestamptz,
    cancelled_at timestamptz,
    email_sent_at timestamptz,
    email_abandoned_at timestamptz,
    email_provider_message_id text,
    email_attempts integer NOT NULL DEFAULT 0,
    email_last_error text,
    CONSTRAINT course_direct_message_recipient CHECK (
        (recipient_kind = 'user' AND recipient_user_id IS NOT NULL)
        OR (recipient_kind = 'course_staff' AND recipient_user_id IS NULL)
    ),
    CONSTRAINT course_direct_message_reply_source CHECK (
        num_nonnulls(reply_to_message_id, reply_to_instructor_message_id,
                     reply_to_question_id) <= 1
    ),
    CONSTRAINT course_direct_message_status_timestamps CHECK (
        (status = 'pending_confirmation' AND sent_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'sent' AND sent_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND sent_at IS NULL AND cancelled_at IS NOT NULL)
    ),
    CONSTRAINT course_direct_message_email_sent CHECK (
        email_sent_at IS NULL OR status = 'sent'
    ),
    CONSTRAINT course_direct_message_email_outcome CHECK (
        email_sent_at IS NULL OR email_abandoned_at IS NULL
    )
);

CREATE INDEX course_direct_messages_sender_index
    ON course_direct_messages (sender_user_id, created_at DESC);
CREATE INDEX course_direct_messages_recipient_index
    ON course_direct_messages (recipient_user_id, sent_at DESC)
    WHERE status = 'sent';
CREATE INDEX course_direct_messages_staff_index
    ON course_direct_messages (sent_at DESC)
    WHERE status = 'sent' AND recipient_kind = 'course_staff';
CREATE INDEX course_direct_messages_email_outbox_index
    ON course_direct_messages (sent_at, id)
    WHERE status = 'sent' AND email_sent_at IS NULL AND email_abandoned_at IS NULL;
