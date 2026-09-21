ALTER TABLE ta_answers
    DROP CONSTRAINT ta_answers_publication_decision_check,
    ADD CONSTRAINT ta_answers_publication_decision_check
        CHECK (publication_decision IN ('publish', 'silent_publish', 'private'));
