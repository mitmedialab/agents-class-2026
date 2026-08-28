"""Third-party public search adapters used behind application-owned tools."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from ddgs import DDGS

_MAX_IMAGE_REDIRECTS = 3
_IMAGE_PROBE_HEADERS = {
    "Accept": "image/*,*/*;q=0.5",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}


def search_duckduckgo_images(query: str, max_results: int) -> list[dict[str, object]]:
    """Search images with an isolated, DuckDuckGo-first DDGS client per request."""

    results: list[dict[str, Any]] = DDGS(timeout=8).images(
        query,
        backend="duckduckgo,bing",
        max_results=max_results,
        safesearch="moderate",
    )
    return [dict(result) for result in results]


def _is_public_https_url(url: str) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    try:
        address_info = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
    except (OSError, ValueError):
        return False
    addresses = {item[4][0] for item in address_info if isinstance(item[4][0], str)}
    return bool(addresses) and all(
        ipaddress.ip_address(address.split("%", 1)[0]).is_global for address in addresses
    )


def _looks_like_image(content: bytes) -> bool:
    normalized = content.lstrip().lower()
    return (
        content.startswith(b"\xff\xd8\xff")
        or content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith((b"GIF87a", b"GIF89a"))
        or (len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
        or (len(content) >= 12 and content[4:8] == b"ftyp")
        or content.startswith(b"BM")
        or normalized.startswith(b"<svg")
        or (normalized.startswith(b"<?xml") and b"<svg" in normalized)
    )


def probe_public_image_url(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str | None:
    """Return a fetchable final image URL, or ``None`` for an unusable candidate."""

    current_url = url
    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=6.0,
            transport=transport,
        ) as client:
            for _ in range(_MAX_IMAGE_REDIRECTS + 1):
                if not _is_public_https_url(current_url):
                    return None
                with client.stream("GET", current_url, headers=_IMAGE_PROBE_HEADERS) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code not in {200, 206}:
                        return None
                    media_type = response.headers.get("content-type", "").split(";", 1)[0]
                    media_type = media_type.strip().casefold()
                    first_chunk = next(response.iter_bytes(chunk_size=512), b"")
                    if not first_chunk:
                        return None
                    return (
                        current_url
                        if media_type.startswith("image/") or _looks_like_image(first_chunk)
                        else None
                    )
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return None
