ALTER TABLE instructor_messages
    ADD COLUMN source_question_id uuid REFERENCES ta_questions(id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX instructor_messages_one_active_reply_per_question
    ON instructor_messages (source_question_id)
    WHERE source_question_id IS NOT NULL
      AND status IN ('pending_confirmation', 'sent');

ALTER TABLE ta_answers
    ADD COLUMN source text NOT NULL DEFAULT 'email' CHECK (source IN ('email', 'online')),
    ADD COLUMN publication_decision text NOT NULL DEFAULT 'private'
        CHECK (publication_decision IN ('publish', 'private')),
    ADD COLUMN online_instructor_message_id uuid UNIQUE
        REFERENCES instructor_messages(id) ON DELETE RESTRICT,
    ALTER COLUMN inbound_provider_message_id DROP NOT NULL;

ALTER TABLE ta_answers
    ADD CONSTRAINT ta_answers_source_fields CHECK (
        (
            source = 'email'
            AND inbound_provider_message_id IS NOT NULL
            AND online_instructor_message_id IS NULL
        )
        OR (
            source = 'online'
            AND inbound_provider_message_id IS NULL
            AND inbound_message_id IS NULL
            AND online_instructor_message_id IS NOT NULL
        )
    );

CREATE INDEX ta_answers_online_notification_index
    ON ta_answers (received_at)
    WHERE source = 'online' AND notified_at IS NULL;
