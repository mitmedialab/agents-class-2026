-- A helper may leave a short note when accepting a classmate's request.
-- Additive only: existing introductions keep a NULL reply.
ALTER TABLE peer_introductions
    ADD COLUMN reply text,
    ADD CONSTRAINT peer_introductions_reply_bounded CHECK (
        reply IS NULL OR (btrim(reply) <> '' AND char_length(reply) <= 1000)
    ),
    ADD CONSTRAINT peer_introductions_reply_only_when_accepted CHECK (
        reply IS NULL OR status = 'accepted'
    );
