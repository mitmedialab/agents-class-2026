DROP INDEX faq_entries_import_origin_unique;

ALTER TABLE faq_entries
    DROP CONSTRAINT faq_entries_import_origin_exclusive,
    DROP CONSTRAINT faq_entries_import_code_requires_origin,
    DROP CONSTRAINT faq_entries_import_code_format,
    DROP COLUMN imported_from_faq_id,
    DROP COLUMN imported_source_question_code;
