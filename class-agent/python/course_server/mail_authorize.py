"""Mint a new offline Gmail refresh token for the course mailbox.

Google's loopback OAuth flow: this command prints a consent URL, receives the one-time code on
a local port, exchanges it for a refresh token, and prints that token once. Paste it into
`MAIL_REFRESH_TOKEN` in `.env` (or the worker's `.env.mail`). Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TextIO
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from dotenv import load_dotenv

from course_server.config import ConfigurationError
from course_server.mail.gmail import GOOGLE_TOKEN_URL

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)


class MailAuthorizationError(RuntimeError):
    """The consent flow did not produce a refresh token."""


def build_consent_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    return (
        GOOGLE_AUTH_URL
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(GMAIL_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )
    )


def exchange_code(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Trade the one-time authorization code for an offline refresh token."""

    with httpx.Client(timeout=30, transport=transport, trust_env=False) as client:
        response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    try:
        payload = response.json()
    except ValueError as error:
        raise MailAuthorizationError("Google returned a non-JSON token response.") from error
    if response.status_code != 200:
        detail = payload.get("error", "unknown") if isinstance(payload, dict) else "unknown"
        raise MailAuthorizationError(f"Google rejected the code ({detail}).")
    token = payload.get("refresh_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise MailAuthorizationError(
            "Google issued no refresh token. Revoke the app at myaccount.google.com/permissions "
            "and run this command again so consent is granted afresh."
        )
    return token


def _wait_for_code(port: int, *, expected_state: str, out: TextIO) -> str:
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlsplit(self.path).query)
            code = query.get("code", [""])[0]
            state = query.get("state", [""])[0]
            error = query.get("error", [""])[0]
            if error or not code or state != expected_state:
                received["error"] = error or "missing code or state mismatch"
                body = b"Authorization failed. You can close this tab."
            else:
                received["code"] = code
                body = b"Mailbox authorized. You can close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", port), Handler)
    try:
        print(f"Waiting for Google to redirect to http://127.0.0.1:{port}/ ...", file=out)
        while "code" not in received and "error" not in received:
            server.handle_request()
    finally:
        server.server_close()
    if "error" in received:
        raise MailAuthorizationError(f"Consent was not granted ({received['error']}).")
    return received["code"]


def _required(values: Mapping[str, str], name: str) -> str:
    raw = values.get(name, "").strip()
    if not raw or "\n" in raw or "\r" in raw:
        raise ConfigurationError(f"{name} is required (a single line) to authorize the mailbox")
    return raw


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    out: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m course_server.mail_authorize",
        description="Mint a new offline Gmail refresh token for MAIL_REFRESH_TOKEN.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="loopback port Google redirects to; the OAuth client must allow it (default 8766)",
    )
    arguments = parser.parse_args(argv)
    out = out or sys.stdout
    if environment is None:
        load_dotenv(override=False)
        environment = dict(os.environ)
    try:
        client_id = _required(environment, "MAIL_CLIENT_ID")
        client_secret = _required(environment, "MAIL_CLIENT_SECRET")
        mailbox = environment.get("MAILBOX_ADDRESS", "").strip() or "the course mailbox"
        redirect_uri = f"http://127.0.0.1:{arguments.port}/"
        state = secrets.token_urlsafe(24)
        print(
            f"Open this URL in a browser and sign in as {mailbox}:\n\n"
            f"{build_consent_url(client_id=client_id, redirect_uri=redirect_uri, state=state)}\n",
            file=out,
        )
        code = _wait_for_code(arguments.port, expected_state=state, out=out)
        token = exchange_code(
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    except (ConfigurationError, MailAuthorizationError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    print(
        "\nNew refresh token (shown once; put it in .env as MAIL_REFRESH_TOKEN and restart the "
        f"mail worker):\n\nMAIL_REFRESH_TOKEN={token}\n",
        file=out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
