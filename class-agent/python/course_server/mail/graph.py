"""Microsoft Graph implementation of the portable mailbox boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from .content import html_to_text
from .models import InboundMail, OutboundMail, SentMail

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
LOGIN_BASE_URL = "https://login.microsoftonline.com"
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
MAX_MESSAGE_PAGES = 10


def _plain_body(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    content = body.get("content")
    if not isinstance(content, str):
        return ""
    content_type = body.get("contentType")
    if not isinstance(content_type, str) or content_type.casefold() != "html":
        return content
    return html_to_text(content)


class MicrosoftGraphMailError(RuntimeError):
    """A sanitized Microsoft Graph failure safe for operational logs."""


class MicrosoftGraphMailAdapter:
    """Application-permission mailbox adapter for Microsoft 365 Outlook."""

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        mailbox_address: str,
        client: httpx.AsyncClient | None = None,
        graph_base_url: str = GRAPH_BASE_URL,
        login_base_url: str = LOGIN_BASE_URL,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._mailbox_address = mailbox_address
        self._client = client or httpx.AsyncClient(timeout=30)
        self._owns_client = client is None
        self._graph_base_url = graph_base_url.rstrip("/")
        self._login_base_url = login_base_url.rstrip("/")
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
        url = f"{self._login_base_url}/{quote(self._tenant_id, safe='')}/oauth2/v2.0/token"
        try:
            response = await self._client.post(
                url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("access_token")
            expires_in = payload.get("expires_in", 3600)
            if not isinstance(token, str) or not token:
                raise MicrosoftGraphMailError("Microsoft identity returned no access token")
            if not isinstance(expires_in, int):
                expires_in = 3600
        except MicrosoftGraphMailError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise MicrosoftGraphMailError("Microsoft identity authentication failed") from error
        self._access_token = token
        self._token_expires_at = now + timedelta(seconds=max(expires_in, 300))
        return token

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        prefer_text: bool = False,
        retry_auth: bool = True,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {await self._token()}",
            "Prefer": 'IdType="ImmutableId"',
        }
        if prefer_text:
            headers["Prefer"] += ', outlook.body-content-type="text"'
        try:
            response = await self._client.request(
                method,
                url,
                headers=headers,
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
                    url,
                    json=json,
                    params=params,
                    prefer_text=prefer_text,
                    retry_auth=False,
                )
            category = "permission denied" if status in {401, 403} else "request failed"
            raise MicrosoftGraphMailError(f"Microsoft Graph mail {category}") from error
        except httpx.HTTPError as error:
            raise MicrosoftGraphMailError("Microsoft Graph mail request failed") from error

    def _mailbox_url(self, suffix: str) -> str:
        mailbox = quote(self._mailbox_address, safe="")
        return f"{self._graph_base_url}/users/{mailbox}{suffix}"

    def _messages_url(self, suffix: str = "") -> str:
        return self._mailbox_url(f"/messages{suffix}")

    async def send_message(self, message: OutboundMail) -> SentMail:
        headers = [
            {"name": name, "value": value}
            for name, value in message.headers.items()
            if name.lower().startswith("x-") and name.isascii() and value.isascii()
        ]
        draft = await self._request(
            "POST",
            self._messages_url(),
            json={
                "subject": message.subject,
                "body": {"contentType": "Text", "content": message.text},
                "toRecipients": [
                    {"emailAddress": {"address": str(recipient)}} for recipient in message.to
                ],
                "internetMessageHeaders": headers,
            },
        )
        try:
            draft_payload = draft.json()
            provider_id = draft_payload["id"]
        except (KeyError, TypeError, ValueError) as error:
            raise MicrosoftGraphMailError("Microsoft Graph returned an invalid draft") from error
        if not isinstance(provider_id, str) or not provider_id:
            raise MicrosoftGraphMailError("Microsoft Graph returned an invalid draft")

        return await self._send_draft(provider_id)

    async def reply_to_message(
        self,
        original: InboundMail,
        *,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> SentMail:
        original_id = quote(original.provider_message_id, safe="")
        draft = await self._request(
            "POST",
            self._messages_url(f"/{original_id}/createReply"),
        )
        try:
            draft_payload = draft.json()
            provider_id = draft_payload["id"]
        except (KeyError, TypeError, ValueError) as error:
            raise MicrosoftGraphMailError(
                "Microsoft Graph returned an invalid reply draft"
            ) from error
        if not isinstance(provider_id, str) or not provider_id:
            raise MicrosoftGraphMailError("Microsoft Graph returned an invalid reply draft")
        custom_headers = [
            {"name": name, "value": value}
            for name, value in (headers or {}).items()
            if name.lower().startswith("x-") and name.isascii() and value.isascii()
        ]
        update: dict[str, Any] = {"body": {"contentType": "Text", "content": text}}
        if custom_headers:
            update["internetMessageHeaders"] = custom_headers
        encoded_id = quote(provider_id, safe="")
        await self._request("PATCH", self._messages_url(f"/{encoded_id}"), json=update)
        return await self._send_draft(provider_id)

    async def _send_draft(self, provider_id: str) -> SentMail:
        encoded_id = quote(provider_id, safe="")
        await self._request("POST", self._messages_url(f"/{encoded_id}/send"))
        sent: httpx.Response | None = None
        for attempt in range(4):
            try:
                sent = await self._request(
                    "GET",
                    self._messages_url(f"/{encoded_id}"),
                    params={"$select": "id,internetMessageId"},
                )
                break
            except MicrosoftGraphMailError:
                if attempt == 3:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
        assert sent is not None
        try:
            sent_payload = sent.json()
            internet_message_id = sent_payload["internetMessageId"]
        except (KeyError, TypeError, ValueError) as error:
            raise MicrosoftGraphMailError(
                "Microsoft Graph returned no sent message identifier"
            ) from error
        if not isinstance(internet_message_id, str) or not internet_message_id:
            raise MicrosoftGraphMailError("Microsoft Graph returned no sent message identifier")
        return SentMail(
            provider_message_id=provider_id,
            internet_message_id=internet_message_id,
        )

    async def fetch_new_messages(self, *, since: datetime) -> list[InboundMail]:
        if since.tzinfo is None or since.utcoffset() is None:
            raise ValueError("since must be timezone-aware")
        next_url: str | None = self._mailbox_url("/mailFolders/inbox/messages")
        since_value = since.astimezone(UTC).isoformat().replace("+00:00", "Z")
        params: dict[str, str] | None = {
            "$filter": f"receivedDateTime ge {since_value}",
            "$orderby": "receivedDateTime asc",
            "$select": "id",
            "$top": "50",
        }
        message_ids: list[str] = []
        for _ in range(MAX_MESSAGE_PAGES):
            if next_url is None:
                break
            response = await self._request("GET", next_url, params=params)
            params = None
            try:
                payload = response.json()
            except ValueError as error:
                raise MicrosoftGraphMailError(
                    "Microsoft Graph returned invalid mail data"
                ) from error
            raw_values = payload.get("value") if isinstance(payload, dict) else None
            if not isinstance(raw_values, list):
                raise MicrosoftGraphMailError("Microsoft Graph returned invalid mail data")
            for value in raw_values:
                if isinstance(value, dict) and isinstance(value.get("id"), str):
                    message_ids.append(value["id"])
            raw_next = payload.get("@odata.nextLink") if isinstance(payload, dict) else None
            next_url = raw_next if isinstance(raw_next, str) and raw_next else None
        if next_url is not None:
            raise MicrosoftGraphMailError("Microsoft Graph mailbox page limit exceeded")

        messages: list[InboundMail] = []
        for provider_id in message_ids:
            encoded_id = quote(provider_id, safe="")
            response = await self._request(
                "GET",
                self._messages_url(f"/{encoded_id}"),
                params={
                    "$select": (
                        "id,internetMessageId,subject,from,receivedDateTime,"
                        "uniqueBody,internetMessageHeaders"
                    )
                },
                prefer_text=True,
            )
            message = self._parse_message(response.json())
            if message is not None:
                messages.append(message)
        return sorted(messages, key=lambda message: message.received_at)

    @staticmethod
    def _parse_message(payload: Any) -> InboundMail | None:
        if not isinstance(payload, dict):
            return None
        sender = payload.get("from")
        address = (
            sender.get("emailAddress", {}).get("address") if isinstance(sender, dict) else None
        )
        unique_body = payload.get("uniqueBody")
        text = _plain_body(unique_body)
        received_at = payload.get("receivedDateTime")
        provider_id = payload.get("id")
        if not isinstance(address, str) or not address:
            return None
        if not isinstance(received_at, str) or not received_at:
            return None
        if not isinstance(provider_id, str) or not provider_id:
            return None
        raw_headers = payload.get("internetMessageHeaders")
        headers: dict[str, str] = {}
        if isinstance(raw_headers, list):
            for item in raw_headers:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                value = item.get("value")
                if isinstance(name, str) and isinstance(value, str):
                    headers[name.casefold()] = value
        return InboundMail(
            provider_message_id=provider_id,
            internet_message_id=(
                payload.get("internetMessageId")
                if isinstance(payload.get("internetMessageId"), str)
                else None
            ),
            sender=address,
            subject=payload.get("subject") if isinstance(payload.get("subject"), str) else "",
            text=text,
            received_at=datetime.fromisoformat(received_at.replace("Z", "+00:00")),
            headers=headers,
        )
