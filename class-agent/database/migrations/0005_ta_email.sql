CREATE SEQUENCE ta_question_number_sequence MAXVALUE 99999 NO CYCLE;

CREATE TABLE ta_questions (
    id uuid PRIMARY KEY,
    public_question_code text NOT NULL UNIQUE,
    student_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    subject text NOT NULL,
    question_text text NOT NULL,
    context_text text,
    status text NOT NULL CHECK (
        status IN ('pending_confirmation', 'queued', 'open', 'answered', 'closed')
    ),
    sent_event_id uuid NOT NULL UNIQUE,
    sent_event_recorded_at timestamptz,
    provider_message_id text,
    outbound_message_id text,
    created_at timestamptz NOT NULL,
    confirmed_at timestamptz,
    sent_at timestamptz,
    resolved_at timestamptz,
    CONSTRAINT ta_questions_code_format CHECK (
        public_question_code ~ '^Q-[0-9]{4}-[0-9]{5}$'
    ),
    CONSTRAINT ta_questions_subject_not_blank CHECK (btrim(subject) <> ''),
    CONSTRAINT ta_questions_question_not_blank CHECK (btrim(question_text) <> ''),
    CONSTRAINT ta_questions_context_not_blank CHECK (
        context_text IS NULL OR btrim(context_text) <> ''
    ),
    CONSTRAINT ta_questions_sent_identifiers_together CHECK (
        (provider_message_id IS NULL) = (outbound_message_id IS NULL)
    )
);

CREATE INDEX ta_questions_delivery_index
    ON ta_questions (created_at)
    WHERE status = 'queued';

CREATE UNIQUE INDEX ta_questions_one_pending_confirmation_per_conversation
    ON ta_questions (conversation_id)
    WHERE status = 'pending_confirmation';

CREATE INDEX ta_questions_outbound_message_index
    ON ta_questions (outbound_message_id)
    WHERE outbound_message_id IS NOT NULL;

CREATE INDEX ta_questions_event_delivery_index
    ON ta_questions (sent_at)
    WHERE sent_at IS NOT NULL AND sent_event_recorded_at IS NULL;

CREATE TABLE ta_answers (
    id uuid PRIMARY KEY,
    question_id uuid NOT NULL UNIQUE REFERENCES ta_questions(id) ON DELETE CASCADE,
    event_id uuid NOT NULL UNIQUE,
    inbound_provider_message_id text NOT NULL UNIQUE,
    inbound_message_id text,
    responder_email text NOT NULL,
    answer_text text NOT NULL,
    received_at timestamptz NOT NULL,
    event_recorded_at timestamptz,
    notification_provider_message_id text,
    notified_at timestamptz,
    CONSTRAINT ta_answers_responder_not_blank CHECK (btrim(responder_email) <> ''),
    CONSTRAINT ta_answers_text_not_blank CHECK (btrim(answer_text) <> ''),
    CONSTRAINT ta_answers_notification_together CHECK (
        (notification_provider_message_id IS NULL) = (notified_at IS NULL)
    )
);

CREATE INDEX ta_answers_event_delivery_index
    ON ta_answers (received_at)
    WHERE event_recorded_at IS NULL;

CREATE INDEX ta_answers_student_notification_index
    ON ta_answers (received_at)
    WHERE notified_at IS NULL;

CREATE TABLE mail_inbound_receipts (
    provider_message_id text PRIMARY KEY,
    disposition text NOT NULL CHECK (
        disposition IN ('answered', 'unauthorized_sender', 'unmatched', 'empty_reply')
    ),
    received_at timestamptz NOT NULL,
    processed_at timestamptz NOT NULL,
    question_id uuid REFERENCES ta_questions(id) ON DELETE SET NULL
);

CREATE TABLE mail_sync_state (
    mailbox_key text PRIMARY KEY,
    last_received_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT mail_sync_mailbox_not_blank CHECK (btrim(mailbox_key) <> '')
);
