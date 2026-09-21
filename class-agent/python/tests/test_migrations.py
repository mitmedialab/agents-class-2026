from __future__ import annotations

from pathlib import Path

import pytest

from course_server.migrations import MigrationError, discover_migrations

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_PATH = PROJECT_ROOT / "database/migrations"


def test_migrations_are_discoverable_and_checksummed() -> None:
    migrations = discover_migrations(MIGRATIONS_PATH)

    assert [migration.version for migration in migrations] == [
        "0001_authentication",
        "0002_conversations_events",
        "0003_course_resources",
        "0004_anonymous_quotas",
        "0005_ta_email",
        "0006_email_faq_review",
        "0007_single_reply_faq_decision",
        "0008_faq_archives",
        "0009_local_faq_knowledge",
        "0010_notification_center",
        "0011_instructor_messages",
        "0012_online_question_answers",
        "0013_online_answer_retention",
        "0014_instructor_message_email",
        "0015_silent_faq_publication",
    ]
    assert all(len(migration.checksum) == 64 for migration in migrations)


def test_phase_two_migration_contains_required_authentication_tables() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[0].sql.lower()

    for table in (
        "schema_migrations",
        "users",
        "auth_sessions",
        "anonymous_sessions",
        "auth_login_failures",
    ):
        assert "create table" in sql
        assert table in sql

    assert "access_code_hash" in sql
    assert "token_hash" in sql
    assert "access_code text" not in sql
    assert "session_token" not in sql


def test_phase_three_migration_contains_portable_history_tables() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[1].sql.lower()

    assert "create table conversations" in sql
    assert "create table events" in sql
    assert "payload jsonb" in sql
    assert "metadata jsonb" in sql
    assert "pickle" not in sql


def test_phase_six_migration_contains_searchable_course_resources() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[2].sql.lower()

    assert "create table course_resources" in sql
    assert "create table faq_entries" in sql
    assert "tsvector" in sql
    assert "using gin" in sql


def test_anonymous_quota_migration_is_session_scoped() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[3].sql.lower()

    assert "create table anonymous_quota_usage" in sql
    assert "references anonymous_sessions" in sql
    assert "on delete cascade" in sql


def test_ta_email_migration_keeps_questions_private_and_idempotent() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[4].sql.lower()

    assert "create table ta_questions" in sql
    assert "create table ta_answers" in sql
    assert "create table mail_inbound_receipts" in sql
    assert "student_user_id" in sql
    assert "conversation_id" in sql
    assert "inbound_provider_message_id text not null unique" in sql


def test_email_faq_review_migration_requires_staff_decision_and_tracks_reads() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[5].sql.lower()

    assert "create table faq_review_candidates" in sql
    assert "create table course_notifications" in sql
    assert "create table course_notification_reads" in sql
    assert "reporter_visibility" in sql
    assert "faq_entries_source_question_unique" in sql


def test_single_reply_migration_adds_durable_publication_outbox() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[6].sql.lower()

    assert "pending_publication" in sql
    assert "faq_review_publication_index" in sql
    assert "answer_publish_requested" in sql
    assert "answer_private" in sql
    assert "invalid_answer_reply" in sql


def test_interim_faq_archive_migration_is_preserved_as_applied_history() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[7].sql.lower()

    assert "imported_from_faq_id" in sql
    assert "imported_source_question_code" in sql
    assert "faq_entries_import_origin_exclusive" in sql
    assert "faq_entries_import_origin_unique" in sql


def test_local_faq_migration_removes_superseded_archive_columns() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[8].sql.lower()

    assert "drop index faq_entries_import_origin_unique" in sql
    assert "drop column imported_from_faq_id" in sql
    assert "drop column imported_source_question_code" in sql


def test_notification_center_migration_adds_generic_per_user_read_state() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[9].sql.lower()

    assert "create table notification_item_reads" in sql
    assert "references users" in sql
    assert "primary key (item_id, user_id)" in sql


def test_instructor_message_migration_snapshots_recipients_and_confirmation_state() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[10].sql.lower()

    assert "create table instructor_messages" in sql
    assert "create table instructor_message_recipients" in sql
    assert "pending_confirmation" in sql
    assert "one_pending_per_conversation" in sql
    assert "primary key (message_id, student_user_id)" in sql


def test_online_answer_migration_links_confirmed_replies_to_questions() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[11].sql.lower()

    assert "source_question_id" in sql
    assert "one_active_reply_per_question" in sql
    assert "online_instructor_message_id" in sql
    assert "publication_decision" in sql
    assert "ta_answers_source_fields" in sql


def test_online_answer_retention_does_not_depend_on_instructor_conversation() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[12].sql.lower()

    assert "instructor_messages_source_question_id_fkey" in sql
    assert "on delete cascade" in sql
    assert "drop constraint ta_answers_online_instructor_message_id_fkey" in sql


def test_silent_faq_publication_extends_the_durable_decision() -> None:
    sql = discover_migrations(MIGRATIONS_PATH)[14].sql.lower()

    assert "ta_answers_publication_decision_check" in sql
    assert "silent_publish" in sql


def test_invalid_migration_filename_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad-name.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match="invalid migration filename"):
        discover_migrations(tmp_path)
