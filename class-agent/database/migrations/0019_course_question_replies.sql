CREATE TABLE course_question_replies (
    id uuid PRIMARY KEY,
    question_id uuid NOT NULL REFERENCES ta_questions(id) ON DELETE CASCADE,
    sender_user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    sender_role text NOT NULL CHECK (sender_role IN ('student', 'staff')),
    body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 10000),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX course_question_replies_thread_index
    ON course_question_replies (question_id, created_at, id);
CREATE INDEX course_question_replies_sender_index
    ON course_question_replies (sender_user_id, created_at DESC);
