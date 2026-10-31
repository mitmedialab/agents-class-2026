"""Same-origin human confirmation and inbox pages for Course MCP messages."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from agent_core import PrincipalContext
from course_server.auth import (
    AuthenticationService,
    InvalidCredentials,
    InvalidSession,
    LoginRateLimited,
)
from course_server.course_direct_messages import CourseDirectMessageService, CourseMessageError
from course_server.mcp_form_security import same_origin_form_submission

_AUTH_COOKIE = "class_agent_auth"
_NEXT_PATH = re.compile(r"^/messages(?:/[0-9a-f-]+|/confirm/[0-9a-f-]+)?$")


def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><main><h1>{html.escape(title)}</h1>"
        f"{content}</main></html>",
        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"},
    )


def _safe_next(value: str) -> str:
    return value if _NEXT_PATH.fullmatch(value) else "/messages"


def _login_page(next_path: str, error: str = "") -> HTMLResponse:
    alert = f'<p role="alert">{html.escape(error)}</p>' if error else ""
    return _page(
        "Sign in to course messages",
        alert
        + '<form method="post" action="/messages/login">'
        + f'<input type="hidden" name="next" value="{html.escape(next_path, quote=True)}">'
        + '<label>Course username or email <input name="username" '
        + 'autocomplete="username" required></label>'
        + '<label>Course access code <input name="access_code" type="password" '
        + 'autocomplete="current-password" required></label>'
        + '<button type="submit">Sign in</button></form>',
    )


def register_course_message_pages(
    mcp: FastMCP,
    messages: CourseDirectMessageService,
    authentication: AuthenticationService,
    base_url: str,
) -> None:
    async def member(request: Request) -> PrincipalContext | None:
        token = request.cookies.get(_AUTH_COOKIE)
        if not token:
            return None
        try:
            return await authentication.resolve_authenticated(token)
        except InvalidSession:
            return None

    def login_redirect(next_path: str) -> RedirectResponse:
        return RedirectResponse(
            f"/messages/login?next={quote(_safe_next(next_path), safe='')}", status_code=303
        )

    def form_allowed(request: Request) -> bool:
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return False
        return same_origin_form_submission(request, base_url) and 0 <= size <= 24_000

    @mcp.custom_route("/messages/login", methods=["GET", "POST"])  # type: ignore[untyped-decorator]
    async def login(request: Request) -> Response:
        if request.method == "GET":
            return _login_page(_safe_next(request.query_params.get("next", "/messages")))
        if not form_allowed(request):
            return PlainTextResponse("Invalid sign-in request.", status_code=400)
        form = await request.form()
        next_path = _safe_next(str(form.get("next", "/messages")))
        try:
            credential = await authentication.login(
                username=str(form.get("username", "")),
                access_code=str(form.get("access_code", "")),
            )
        except (InvalidCredentials, LoginRateLimited):
            return _login_page(next_path, "The course username or access code was not accepted.")
        response = RedirectResponse(next_path, status_code=303)
        response.headers["Cache-Control"] = "no-store"
        response.set_cookie(
            _AUTH_COOKIE,
            credential.token,
            path="/",
            httponly=True,
            secure=True,
            samesite="lax",
            expires=credential.expires_at,
            max_age=max(0, int((credential.expires_at - datetime.now(UTC)).total_seconds())),
        )
        return response

    @mcp.custom_route("/messages", methods=["GET"])  # type: ignore[untyped-decorator]
    async def inbox(request: Request) -> Response:
        principal = await member(request)
        if principal is None:
            return login_redirect("/messages")
        try:
            offset = int(request.query_params.get("offset", "0"))
            data = await messages.list_mine(principal, offset=offset, limit=50)
        except (CourseMessageError, ValueError):
            return PlainTextResponse("Course messages are unavailable.", status_code=403)
        items = "".join(
            '<li><a href="/messages/'
            + html.escape(item["id"], quote=True)
            + '">'
            + html.escape(item["subject"])
            + "</a> — "
            + html.escape(item["sender"]["display_name"])
            + "</li>"
            for item in data["messages"]
        )
        more = (
            '<p><a href="/messages?offset=' + str(data["next_offset"]) + '">Older messages</a></p>'
            if data["next_offset"] is not None
            else ""
        )
        return _page("Course messages", f"<ol>{items}</ol>{more}")

    @mcp.custom_route("/messages/confirm/{message_id}", methods=["GET", "POST"])  # type: ignore[untyped-decorator]
    async def confirm(request: Request) -> Response:
        principal = await member(request)
        if principal is None:
            return login_redirect(request.url.path)
        try:
            message_id = UUID(request.path_params["message_id"])
            draft = await messages.get_draft(principal, message_id)
        except (ValueError, CourseMessageError):
            return PlainTextResponse("Message draft not found or expired.", status_code=404)
        if request.method == "POST":
            if not form_allowed(request):
                return PlainTextResponse("Invalid confirmation request.", status_code=400)
            form = await request.form()
            action = str(form.get("action", ""))
            if action not in {"send", "cancel"}:
                return PlainTextResponse("Choose Send or Cancel.", status_code=400)
            try:
                result = await messages.confirm(
                    principal,
                    message_id,
                    action=action,  # type: ignore[arg-type]
                    subject=str(form.get("subject", "")) if action == "send" else None,
                    body=str(form.get("body", "")) if action == "send" else None,
                )
            except CourseMessageError as error:
                return _page("Message not sent", f"<p>{html.escape(str(error))}</p>")
            destination = f"/messages/{result.id}" if action == "send" else "/messages"
            return RedirectResponse(destination, status_code=303)
        recipient = html.escape(draft.recipient_label)
        username = html.escape(draft.recipient_username or "@course_staff")
        return _page(
            "Review course message",
            "<p>Nothing has been sent. Review the recipient and exact text. "
            "Press Send to deliver this in the course inbox and queue an email copy.</p>"
            f"<p>To: {recipient} ({username})</p>"
            f'<form method="post" action="/messages/confirm/{message_id}">'
            f'<label>Subject <input name="subject" maxlength="200" required '
            f'value="{html.escape(draft.subject, quote=True)}"></label>'
            f'<label>Message <textarea name="body" maxlength="10000" required>'
            f"{html.escape(draft.body)}</textarea></label>"
            '<button type="submit" name="action" value="send">Send</button>'
            '<button type="submit" name="action" value="cancel">Cancel</button></form>',
        )

    @mcp.custom_route("/messages/{message_id}", methods=["GET"])  # type: ignore[untyped-decorator]
    async def read_message(request: Request) -> Response:
        principal = await member(request)
        if principal is None:
            return login_redirect(request.url.path)
        try:
            message = await messages.read_mine(principal, UUID(request.path_params["message_id"]))
        except (ValueError, CourseMessageError):
            return PlainTextResponse("Message not found.", status_code=404)
        return _page(
            message.subject,
            '<p><a href="/messages">Course inbox</a></p>'
            f"<p>From: {html.escape(message.sender_display_name)} "
            f"({html.escape(message.sender_username)})</p>"
            f"<p>To: {html.escape(message.recipient_label)}</p>"
            f"<pre>{html.escape(message.body)}</pre>"
            f'<form method="post" action="/messages/{message.id}/reply">'
            '<label>Your reply <textarea name="body" maxlength="10000" required></textarea></label>'
            '<button type="submit">Review reply</button></form>',
        )

    @mcp.custom_route("/messages/{message_id}/reply", methods=["POST"])  # type: ignore[untyped-decorator]
    async def reply(request: Request) -> Response:
        principal = await member(request)
        if principal is None:
            return login_redirect(request.url.path)
        if not form_allowed(request):
            return PlainTextResponse("Invalid reply request.", status_code=400)
        try:
            original_id = UUID(request.path_params["message_id"])
            original = await messages.read_mine(principal, original_id)
            form = await request.form()
            subject = (
                original.subject
                if original.subject.startswith("Re: ")
                else f"Re: {original.subject}"
            )
            draft = await messages.prepare(
                principal,
                recipient_username="",
                subject=subject[:200],
                body=str(form.get("body", "")),
                reply_to=original_id,
            )
        except (ValueError, CourseMessageError) as error:
            return _page("Reply not prepared", f"<p>{html.escape(str(error))}</p>")
        return RedirectResponse(f"/messages/confirm/{draft.id}", status_code=303)
