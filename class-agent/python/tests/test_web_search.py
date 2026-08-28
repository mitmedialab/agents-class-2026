from __future__ import annotations

import httpx
import pytest

from course_server import web_search


def _allow_public_test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    def validator(url: str) -> bool:
        return url.startswith("https://images.example.org/")

    monkeypatch.setattr(web_search, "_is_public_https_url", validator)


def test_image_probe_accepts_a_fetchable_image(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_public_test_hosts(monkeypatch)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "image/x-uncommon-format",
                "Content-Length": "999999999",
            },
            content=b"available image bytes",
        )

    url = "https://images.example.org/portrait.jpg"
    result = web_search.probe_public_image_url(
        url,
        transport=httpx.MockTransport(respond),
    )

    assert result == url
    assert len(requests) == 1
    assert "range" not in requests[0].headers


def test_image_probe_accepts_image_bytes_with_a_generic_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_test_hosts(monkeypatch)

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/octet-stream"},
            content=b"\x89PNG\r\n\x1a\navailable",
        )

    url = "https://images.example.org/mislabeled.png"
    assert web_search.probe_public_image_url(url, transport=httpx.MockTransport(respond)) == url


def test_image_probe_rejects_non_images_and_private_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_test_hosts(monkeypatch)

    def html_response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html>not an image</html>",
        )

    assert (
        web_search.probe_public_image_url(
            "https://images.example.org/not-an-image.jpg",
            transport=httpx.MockTransport(html_response),
        )
        is None
    )

    request_count = 0

    def redirect_response(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/private.jpg"})

    assert (
        web_search.probe_public_image_url(
            "https://images.example.org/redirect.jpg",
            transport=httpx.MockTransport(redirect_response),
        )
        is None
    )
    assert request_count == 1
