"""Gmail API implementation of the portable mailbox boundary."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import make_msgid, parseaddr
from typing import Any

import httpx

from .content import html_to_text, strip_quoted_reply
from .models import InboundMail, OutboundMail, SentMail

GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
MAX_MESSAGE_PAGES = 10


class GoogleGmailMailError(RuntimeError):
    """A sanitized Gmail API failure safe for operational logs."""


def _decode_base64url(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}").decode(
            "utf-8",
            errors="replace",
        )
    except (ValueError, TypeError):
        return ""


def _payload_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    plain: list[str] = []
    html: list[str] = []

    def visit(part: Any) -> None:
        if not isinstance(part, dict):
            return
        mime_type = part.get("mimeType")
        body = part.get("body")
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, str) and data:
            decoded = _decode_base64url(data)
            if isinstance(mime_type, str) and mime_type.casefold() == "text/html":
                html.append(decoded)
            elif not isinstance(mime_type, str) or mime_type.casefold() == "text/plain":
                plain.append(decoded)
        parts = part.get("parts")
        if isinstance(parts, list):
            for child in parts:
                visit(child)

    visit(payload)
    if plain:
        return "\n".join(plain)
    return html_to_text("\n".join(html))


class GoogleGmailMailAdapter:
    """User-consent OAuth adapter for one dedicated Gmail mailbox."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        mailbox_address: str,
        client: httpx.AsyncClient | None = None,
        gmail_base_url: str = GMAIL_BASE_URL,
        token_url: str = GOOGLE_TOKEN_URL,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._mailbox_address = mailbox_address
        self._client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None
        self._gmail_base_url = gmail_base_url.rstrip("/")
        self._token_url = token_url
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _token(self) -> str:
        now = datetime.now(UTC)
        if (
            self._access_token is not None
            and self._token_expires_at is not None
            and now + TOKEN_REFRESH_MARGIN < self._token_expires_at
        ):
            return self._access_token
        try:
            response = await self._client.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            expires_in = payload.get("expires_in", 3600)
            if not isinstance(token, str) or not token:
                raise GoogleGmailMailError("Google identity returned no access token")
            if not isinstance(expires_in, int):
                expires_in = 3600
        except GoogleGmailMailError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise GoogleGmailMailError("Google identity authentication failed") from error
        self._access_token = token
        self._token_expires_at = now + timedelta(seconds=max(expires_in, 300))
        return token

    async def _request(
        self,
        method: str,
        suffix: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                f"{self._gmail_base_url}{suffix}",
                headers={"Authorization": f"Bearer {await self._token()}"},
                json=json,
                params=params,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 401 and retry_auth:
                self._access_token = None
                self._token_expires_at = None
                return await self._request(
                    method,
                    suffix,
                    json=json,
                    params=params,
                    retry_auth=False,
                )
            category = "permission denied" if status in {401, 403} else "request failed"
            raise GoogleGmailMailError(f"Gmail API mail {category}") from error
        except httpx.HTTPError as error:
            raise GoogleGmailMailError("Gmail API mail request failed") from error

    async def send_message(self, message: OutboundMail) -> SentMail:
        mime = EmailMessage(policy=SMTP)
        mime["From"] = self._mailbox_address
        mime["To"] = ", ".join(str(recipient) for recipient in message.to)
        mime["Subject"] = message.subject
        domain = self._mailbox_address.rsplit("@", 1)[-1]
        internet_message_id = make_msgid(domain=domain)
        mime["Message-ID"] = internet_message_id
        for name, value in message.headers.items():
            if name.lower().startswith("x-") and name.isascii() and value.isascii():
                mime[name] = value
        mime.set_content(message.text)
        return await self._send_mime(mime)

    async def reply_to_message(
        self,
        original: InboundMail,
        *,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> SentMail:
        response = await self._request(
            "GET",
            f"/users/me/messages/{original.provider_message_id}",
            params={"format": "metadata"},
        )
        try:
            payload = response.json()
            thread_id = payload["threadId"]
        except (KeyError, TypeError, ValueError) as error:
            raise GoogleGmailMailError("Gmail API returned no reply thread") from error
        if not isinstance(thread_id, str) or not thread_id:
            raise GoogleGmailMailError("Gmail API returned no reply thread")

        mime = EmailMessage(policy=SMTP)
        mime["From"] = self._mailbox_address
        mime["To"] = str(original.sender)
        subject = original.subject.strip()
        mime["Subject"] = subject if subject.casefold().startswith("re:") else f"Re: {subject}"
        domain = self._mailbox_address.rsplit("@", 1)[-1]
        internet_message_id = make_msgid(domain=domain)
        mime["Message-ID"] = internet_message_id
        if original.internet_message_id:
            mime["In-Reply-To"] = original.internet_message_id
            references = original.headers.get("references", "").strip()
            mime["References"] = f"{references} {original.internet_message_id}".strip()
        for name, value in (headers or {}).items():
            if name.lower().startswith("x-") and name.isascii() and value.isascii():
                mime[name] = value
        mime.set_content(text)
        return await self._send_mime(mime, thread_id=thread_id)

    async def _send_mime(
        self,
        mime: EmailMessage,
        *,
        thread_id: str | None = None,
    ) -> SentMail:
        internet_message_id = str(mime["Message-ID"])
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        payload = {"raw": raw}
        if thread_id is not None:
            payload["threadId"] = thread_id
        response = await self._request(
            "POST",
            "/users/me/messages/send",
            json=payload,
        )
        try:
            payload = response.json()
            provider_id = payload["id"]
        except (KeyError, TypeError, ValueError) as error:
            raise GoogleGmailMailError("Gmail API returned an invalid sent message") from error
        if not isinstance(provider_id, str) or not provider_id:
            raise GoogleGmailMailError("Gmail API returned an invalid sent message")
        return SentMail(
            provider_message_id=provider_id,
            internet_message_id=internet_message_id,
        )

    async def fetch_new_messages(self, *, since: datetime) -> list[InboundMail]:
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("since must be timezone-aware")
        params: dict[str, str] | None = {
            "q": f"in:inbox after:{int(since.astimezone(UTC).timestamp())}",
            "maxResults": "100",
        }
        message_ids: list[str] = []
        next_page_token: str | None = None
        for _ in range(MAX_MESSAGE_PAGES):
            if params is not None and next_page_token is not None:
                params["pageToken"] = next_page_token
            response = await self._request("GET", "/users/me/messages", params=params)
            try:
                payload = response.json()
            except ValueError as error:
                raise GoogleGmailMailError("Gmail API returned invalid mail data") from error
            if not isinstance(payload, dict):
                raise GoogleGmailMailError("Gmail API returned invalid mail data")
            raw_messages = payload.get("messages", [])
            if not isinstance(raw_messages, list):
                raise GoogleGmailMailError("Gmail API returned invalid mail data")
            for raw_message in raw_messages:
                if isinstance(raw_message, dict) and isinstance(raw_message.get("id"), str):
                    message_ids.append(raw_message["id"])
            raw_next = payload.get("nextPageToken")
            next_page_token = raw_next if isinstance(raw_next, str) and raw_next else None
            if next_page_token is None:
                break
        if next_page_token is not None:
            raise GoogleGmailMailError("Gmail API mailbox page limit exceeded")

        messages: list[InboundMail] = []
        for provider_id in message_ids:
            response = await self._request(
                "GET",
                f"/users/me/messages/{provider_id}",
                params={"format": "full"},
            )
            message = self._parse_message(response.json())
            if message is not None:
                messages.append(message)
        return sorted(messages, key=lambda message: message.received_at)

    @staticmethod
    def _parse_message(payload: Any) -> InboundMail | None:
        if not isinstance(payload, dict):
            return None
        provider_id = payload.get("id")
        internal_date = payload.get("internalDate")
        body = payload.get("payload")
        if not isinstance(provider_id, str) or not provider_id:
            return None
        if not isinstance(internal_date, str) or not internal_date.isdigit():
            return None
        if not isinstance(body, dict):
            return None
        raw_headers = body.get("headers")
        headers: dict[str, str] = {}
        if isinstance(raw_headers, list):
            for item in raw_headers:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                value = item.get("value")
                if isinstance(name, str) and isinstance(value, str):
                    headers[name.casefold()] = value
        sender = parseaddr(headers.get("from", ""))[1]
        if not sender:
            return None
        text = strip_quoted_reply(_payload_text(body))
        return InboundMail(
            provider_message_id=provider_id,
            internet_message_id=headers.get("message-id"),
            sender=sender,
            subject=headers.get("subject", ""),
            text=text,
            received_at=datetime.fromtimestamp(int(internal_date) / 1_000, tz=UTC),
            headers=headers,
        )
