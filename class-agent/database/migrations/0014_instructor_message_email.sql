-- The confirmed message and its fixed recipients form the durable email outbox.
-- Existing messages remain in-app only; no historical messages are emailed.
ALTER TABLE instructor_messages
    ADD COLUMN send_email boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT instructor_message_email_confirmation CHECK (
        NOT send_email OR (status = 'sent' AND source_question_id IS NULL)
    );

ALTER TABLE instructor_message_recipients
    ADD COLUMN email_sent_at timestamptz,
    ADD COLUMN email_provider_message_id text,
    ADD COLUMN email_attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN email_last_error text;
