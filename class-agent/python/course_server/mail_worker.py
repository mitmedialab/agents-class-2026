"""Dedicated mailbox process for private course-staff replies."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from collections.abc import Sequence

from dotenv import load_dotenv

from course_server.config import ConfigurationError, MailSettings
from course_server.faq import CoordinatedFaqPublisher, LocalFaqKnowledgeStore, PostgresFaqStore
from course_server.mail import (
    GoogleGmailMailAdapter,
    MailWorker,
    MicrosoftGraphMailAdapter,
    PostgresTAQuestionStore,
)
from course_server.migrations import apply_migrations
from course_server.postgres.auth_store import PostgresAuthStore, create_auth_pool
from course_server.postgres.conversation_store import PostgresConversationStore

logger = logging.getLogger(__name__)


async def run_worker(*, database_url: str, settings: MailSettings, once: bool = False) -> None:
    apply_migrations(database_url)
    pool = create_auth_pool(database_url)
    await pool.open()
    await pool.wait()
    adapter: MicrosoftGraphMailAdapter | GoogleGmailMailAdapter
    if settings.provider == "microsoft_graph":
        if settings.tenant_id is None:
            raise ConfigurationError("MAIL_TENANT_ID is required for Microsoft Graph")
        adapter = MicrosoftGraphMailAdapter(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret.get_secret_value(),
            mailbox_address=str(settings.mailbox_address),
        )
    else:
        if settings.refresh_token is None:
            raise ConfigurationError("MAIL_REFRESH_TOKEN is required for Google Gmail")
        adapter = GoogleGmailMailAdapter(
            client_id=settings.client_id,
            client_secret=settings.client_secret.get_secret_value(),
            refresh_token=settings.refresh_token.get_secret_value(),
            mailbox_address=str(settings.mailbox_address),
        )
    worker = MailWorker(
        mail=adapter,
        questions=PostgresTAQuestionStore(pool),
        auth=PostgresAuthStore(pool),
        conversations=PostgresConversationStore(pool),
        faqs=CoordinatedFaqPublisher(
            PostgresFaqStore(pool),
            LocalFaqKnowledgeStore(settings.published_faq_path),
        ),
        mailbox_key=str(settings.mailbox_address),
        staff_recipient=str(settings.staff_recipient_address),
        authorized_reply_senders=(str(value) for value in settings.authorized_reply_senders),
    )
    try:
        while True:
            try:
                await worker.run_once()
            except Exception as error:
                logger.error("Mail worker cycle failed (%s)", type(error).__name__)
                if once:
                    raise
            if once:
                return
            await asyncio.sleep(settings.poll_interval_seconds)
    finally:
        await adapter.close()
        await pool.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Class Agent mailbox worker")
    parser.add_argument("--once", action="store_true", help="process one polling cycle and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    load_dotenv(override=False)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise ConfigurationError("DATABASE_URL is required")
    settings = MailSettings.optional_from_environment(os.environ)
    if settings is None:
        raise ConfigurationError("MAIL_ENABLED=true is required for the mail worker")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(database_url=database_url, settings=settings, once=arguments.once))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
