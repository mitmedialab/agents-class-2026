"""Browser-origin checks for course-site MCP forms."""

from __future__ import annotations

from starlette.requests import Request


def same_origin_form_submission(request: Request, public_origin: str) -> bool:
    """Accept same-origin forms even when no-referrer makes Origin null.

    Browsers still send Sec-Fetch-Site for these navigations. Require its
    same-origin value when Origin is unavailable; never trust same-site or
    cross-site submissions for account access or message delivery.
    """
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site not in {None, "same-origin"}:
        return False
    if origin == public_origin:
        return True
    return origin in {None, "null"} and fetch_site == "same-origin"
