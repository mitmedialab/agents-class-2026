ALTER TABLE ta_questions
    ADD COLUMN reporter_visibility text NOT NULL DEFAULT 'named' CHECK (
        reporter_visibility IN ('named', 'anonymous')
    );

ALTER TABLE faq_entries
    ADD CONSTRAINT faq_entries_source_question_fk
    FOREIGN KEY (source_question_id) REFERENCES ta_questions(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX faq_entries_source_question_unique
    ON faq_entries (source_question_id)
    WHERE source_question_id IS NOT NULL;

CREATE TABLE faq_review_candidates (
    id uuid PRIMARY KEY,
    question_id uuid NOT NULL UNIQUE REFERENCES ta_questions(id) ON DELETE CASCADE,
    answer_id uuid NOT NULL UNIQUE REFERENCES ta_answers(id) ON DELETE CASCADE,
    suggested_question text NOT NULL,
    suggested_answer text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('pending_delivery', 'pending_review', 'published', 'declined')
    ),
    review_provider_message_id text,
    review_outbound_message_id text,
    review_sent_at timestamptz,
    decision_inbound_provider_message_id text UNIQUE,
    reviewed_by_email text,
    reviewed_at timestamptz,
    published_faq_entry_id uuid UNIQUE REFERENCES faq_entries(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT faq_review_question_not_blank CHECK (btrim(suggested_question) <> ''),
    CONSTRAINT faq_review_answer_not_blank CHECK (btrim(suggested_answer) <> ''),
    CONSTRAINT faq_review_delivery_fields_together CHECK (
        (review_provider_message_id IS NULL) = (review_outbound_message_id IS NULL)
        AND (review_provider_message_id IS NULL) = (review_sent_at IS NULL)
    ),
    CONSTRAINT faq_review_decision_fields_together CHECK (
        (decision_inbound_provider_message_id IS NULL) = (reviewed_at IS NULL)
        AND (decision_inbound_provider_message_id IS NULL) = (reviewed_by_email IS NULL)
    )
);

CREATE INDEX faq_review_delivery_index
    ON faq_review_candidates (created_at)
    WHERE status = 'pending_delivery';

CREATE INDEX faq_review_reply_index
    ON faq_review_candidates (review_outbound_message_id)
    WHERE status = 'pending_review';

CREATE TABLE course_notifications (
    id uuid PRIMARY KEY,
    faq_entry_id uuid NOT NULL UNIQUE REFERENCES faq_entries(id) ON DELETE CASCADE,
    published_at timestamptz NOT NULL
);

CREATE TABLE course_notification_reads (
    notification_id uuid NOT NULL REFERENCES course_notifications(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at timestamptz NOT NULL,
    PRIMARY KEY (notification_id, user_id)
);

ALTER TABLE mail_inbound_receipts
    DROP CONSTRAINT mail_inbound_receipts_disposition_check;

ALTER TABLE mail_inbound_receipts
    ADD CONSTRAINT mail_inbound_receipts_disposition_check CHECK (
        disposition IN (
            'answered',
            'faq_declined',
            'faq_published',
            'invalid_review_reply',
            'unauthorized_sender',
            'unmatched',
            'empty_reply'
        )
    );
