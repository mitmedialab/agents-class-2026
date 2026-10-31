from __future__ import annotations

import pytest
from starlette.requests import Request

from course_server.mcp_form_security import same_origin_form_submission

PUBLIC_ORIGIN = "https://course.example"


@pytest.mark.parametrize(
    ("origin", "fetch_site", "allowed"),
    [
        (PUBLIC_ORIGIN, None, True),
        (PUBLIC_ORIGIN, "same-origin", True),
        ("null", "same-origin", True),
        (None, "same-origin", True),
        ("null", None, False),
        ("null", "cross-site", False),
        ("null", "same-site", False),
        ("https://other.example", "same-origin", False),
        (PUBLIC_ORIGIN, "cross-site", False),
    ],
)
def test_same_origin_form_submission(
    origin: str | None, fetch_site: str | None, allowed: bool
) -> None:
    headers = []
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if fetch_site is not None:
        headers.append((b"sec-fetch-site", fetch_site.encode()))
    request = Request({"type": "http", "method": "POST", "path": "/connect", "headers": headers})
    assert same_origin_form_submission(request, PUBLIC_ORIGIN) is allowed
