"""Construct the configured mailbox adapter from validated settings."""

from __future__ import annotations

from course_server.config import ConfigurationError, MailSettings

from .gmail import GoogleGmailMailAdapter
from .graph import MicrosoftGraphMailAdapter


def create_mail_adapter(
    settings: MailSettings,
) -> GoogleGmailMailAdapter | MicrosoftGraphMailAdapter:
    if settings.provider == "microsoft_graph":
        if settings.tenant_id is None:
            raise ConfigurationError("MAIL_TENANT_ID is required for Microsoft Graph")
        return MicrosoftGraphMailAdapter(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret.get_secret_value(),
            mailbox_address=str(settings.mailbox_address),
        )
    if settings.refresh_token is None:
        raise ConfigurationError("MAIL_REFRESH_TOKEN is required for Google Gmail")
    return GoogleGmailMailAdapter(
        client_id=settings.client_id,
        client_secret=settings.client_secret.get_secret_value(),
        refresh_token=settings.refresh_token.get_secret_value(),
        mailbox_address=str(settings.mailbox_address),
    )
