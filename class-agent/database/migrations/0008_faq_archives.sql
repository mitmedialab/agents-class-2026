ALTER TABLE faq_entries
    ADD COLUMN imported_from_faq_id uuid,
    ADD COLUMN imported_source_question_code text;

ALTER TABLE faq_entries
    ADD CONSTRAINT faq_entries_import_origin_exclusive CHECK (
        source_question_id IS NULL OR imported_from_faq_id IS NULL
    ),
    ADD CONSTRAINT faq_entries_import_code_requires_origin CHECK (
        imported_source_question_code IS NULL OR imported_from_faq_id IS NOT NULL
    ),
    ADD CONSTRAINT faq_entries_import_code_format CHECK (
        imported_source_question_code IS NULL
        OR imported_source_question_code ~ '^Q-[0-9]{4}-[0-9]{5}$'
    );

CREATE UNIQUE INDEX faq_entries_import_origin_unique
    ON faq_entries (imported_from_faq_id)
    WHERE imported_from_faq_id IS NOT NULL;
