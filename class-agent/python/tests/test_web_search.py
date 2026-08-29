from __future__ import annotations

import httpx
import pytest

from course_server import web_search


def _allow_public_test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    def validator(url: str) -> bool:
        return url.startswith("https://images.example.org/")

    monkeypatch.setattr(web_search, "_is_public_https_url", validator)


def _allow_public_web_test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        web_search,
        "_is_public_web_url",
        lambda url: url.startswith("https://public.example.org/"),
    )


def test_brave_web_search_uses_authenticated_api_and_formats_results() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "  Example   profile ",
                            "url": "https://public.example.org/profile",
                            "description": " Public <strong>research</strong>   profile. ",
                        }
                    ]
                }
            },
        )

    client = web_search.BraveWebSearchClient(
        "test-brave-secret",
        max_results=5,
        requests_per_second=None,
        transport=httpx.MockTransport(respond),
    )

    assert client("Ada Lovelace") == (
        "## Search Results\n\n"
        "[Example profile](https://public.example.org/profile)\n"
        "Public research profile."
    )
    assert len(requests) == 1
    assert requests[0].url.params["q"] == "Ada Lovelace"
    assert requests[0].url.params["count"] == "5"
    assert requests[0].headers["x-subscription-token"] == "test-brave-secret"


def test_brave_web_search_retries_rate_limit_using_reset_header() -> None:
    request_count = 0
    sleeps: list[float] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(429, headers={"X-RateLimit-Reset": "0.5"})
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Result",
                            "url": "https://public.example.org/result",
                            "description": "Found after retry.",
                        }
                    ]
                }
            },
        )

    client = web_search.BraveWebSearchClient(
        "test-brave-secret",
        requests_per_second=None,
        transport=httpx.MockTransport(respond),
        sleep=sleeps.append,
    )

    assert "Found after retry." in client("retry me")
    assert request_count == 2
    assert sleeps == [0.5]


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


def test_webpage_fetch_revalidates_and_rejects_private_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_web_test_hosts(monkeypatch)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    with pytest.raises(ValueError, match="public internet"):
        web_search.fetch_public_webpage(
            "https://public.example.org/start",
            transport=httpx.MockTransport(respond),
        )
    assert len(requests) == 1


def test_webpage_fetch_follows_only_revalidated_public_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_web_test_hosts(monkeypatch)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=(
                b'<h1>Safe page</h1><img src="/hero.jpg" alt="Hero" width="1200" '
                b'height="800"><img data-src="https://public.example.org/second.png">'
            ),
        )

    result = web_search.fetch_public_webpage(
        "https://public.example.org/start",
        transport=httpx.MockTransport(respond),
    )
    assert isinstance(result, dict)
    assert "Safe page" in str(result["text"])
    assert result["url"] == "https://public.example.org/final"
    assert result["images"] == [
        {
            "image_url": "https://public.example.org/hero.jpg",
            "alt": "Hero",
            "width": "1200",
            "height": "800",
        },
        {"image_url": "https://public.example.org/second.png"},
    ]
