ALTER TABLE instructor_messages
    DROP CONSTRAINT instructor_messages_source_question_id_fkey,
    ADD CONSTRAINT instructor_messages_source_question_id_fkey
        FOREIGN KEY (source_question_id) REFERENCES ta_questions(id) ON DELETE CASCADE;

ALTER TABLE ta_answers
    DROP CONSTRAINT ta_answers_online_instructor_message_id_fkey;
