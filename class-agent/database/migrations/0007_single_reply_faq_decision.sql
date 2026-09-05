ALTER TABLE faq_review_candidates
    DROP CONSTRAINT faq_review_candidates_status_check;

ALTER TABLE faq_review_candidates
    ADD CONSTRAINT faq_review_candidates_status_check CHECK (
        status IN (
            'pending_publication',
            'pending_delivery',
            'pending_review',
            'published',
            'declined'
        )
    );

CREATE INDEX faq_review_publication_index
    ON faq_review_candidates (created_at)
    WHERE status = 'pending_publication';

ALTER TABLE mail_inbound_receipts
    DROP CONSTRAINT mail_inbound_receipts_disposition_check;

ALTER TABLE mail_inbound_receipts
    ADD CONSTRAINT mail_inbound_receipts_disposition_check CHECK (
        disposition IN (
            'answered',
            'answer_publish_requested',
            'answer_private',
            'faq_declined',
            'faq_published',
            'invalid_answer_reply',
            'invalid_review_reply',
            'unauthorized_sender',
            'unmatched',
            'empty_reply'
        )
    );
