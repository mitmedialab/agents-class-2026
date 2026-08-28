"""Third-party public search adapters used behind application-owned tools."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from markdownify import markdownify
from openai import OpenAI

_MAX_IMAGE_REDIRECTS = 3
_MAX_WEBPAGE_REDIRECTS = 5
_MAX_WEBPAGE_BYTES = 2 * 1024 * 1024
_MAX_PAGE_IMAGES = 20
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


def _is_public_web_url(url: str) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    try:
        address_info = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except (OSError, ValueError):
        return False
    addresses = {item[4][0] for item in address_info if isinstance(item[4][0], str)}
    return bool(addresses) and all(
        ipaddress.ip_address(address.split("%", 1)[0]).is_global for address in addresses
    )


def fetch_public_webpage(
    url: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> str | dict[str, object]:
    """Fetch readable text and resolved image DOM metadata with safe redirects."""

    current_url = url
    with httpx.Client(
        follow_redirects=False,
        timeout=20.0,
        transport=transport,
        trust_env=False,
    ) as client:
        for _ in range(_MAX_WEBPAGE_REDIRECTS + 1):
            if not _is_public_web_url(current_url):
                raise ValueError("webpage URL must resolve only to public internet addresses")
            with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("webpage redirect did not include a destination")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                media_type = response.headers.get("content-type", "").partition(";")[0]
                normalized_media_type = media_type.strip().casefold()
                if normalized_media_type not in {
                    "text/html",
                    "application/xhtml+xml",
                    "text/plain",
                    "text/markdown",
                }:
                    raise ValueError("webpage did not return a supported text format")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_WEBPAGE_BYTES:
                        raise ValueError("webpage response exceeded the size limit")
                encoding = response.encoding or "utf-8"
                text = bytes(content).decode(encoding, errors="replace")
                if normalized_media_type in {"text/html", "application/xhtml+xml"}:
                    soup = BeautifulSoup(text, "html.parser")
                    images: list[dict[str, object]] = []
                    seen: set[str] = set()
                    for element in soup.select(
                        "img[src], img[data-src], img[data-lazy-src], source[srcset], "
                        "meta[property='og:image'][content], meta[name='twitter:image'][content]"
                    ):
                        raw_url = (
                            element.get("content")
                            or element.get("data-src")
                            or element.get("data-lazy-src")
                            or element.get("src")
                        )
                        srcset = element.get("srcset")
                        if not raw_url and isinstance(srcset, str):
                            entries = [item.strip().split()[0] for item in srcset.split(",")]
                            raw_url = entries[-1] if entries else None
                        if not isinstance(raw_url, str):
                            continue
                        image_url = urljoin(current_url, raw_url.strip())
                        if image_url in seen or urlsplit(image_url).scheme not in {"http", "https"}:
                            continue
                        seen.add(image_url)
                        image: dict[str, object] = {"image_url": image_url}
                        for source_name, output_name in (
                            ("alt", "alt"),
                            ("title", "title"),
                            ("width", "width"),
                            ("height", "height"),
                        ):
                            value = element.get(source_name)
                            if isinstance(value, str) and value.strip():
                                image[output_name] = value.strip()[:500]
                        images.append(image)
                        if len(images) >= _MAX_PAGE_IMAGES:
                            break
                    return {
                        "url": current_url,
                        "text": markdownify(text).strip(),
                        "images": images,
                    }
                return text.strip()
    raise ValueError("webpage exceeded the redirect limit")


def inspect_images_with_openai(
    urls: list[str],
    prompt: str,
    *,
    model_id: str,
    api_key: str,
) -> str:
    """Inspect a bounded batch of verified images using multimodal model input."""

    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": (
                "Inspect the numbered public images. Describe visible content, compare their "
                "usefulness for the requested purpose, and flag uncertainty. Do not identify a "
                "person solely from appearance.\n\nRequest: " + prompt
            ),
        }
    ]
    for index, url in enumerate(urls, start=1):
        content.extend(
            [
                {"type": "input_text", "text": f"Image {index}: {url}"},
                {"type": "input_image", "image_url": url, "detail": "high"},
            ]
        )
    response = OpenAI(api_key=api_key).responses.create(
        model=model_id,
        input=cast(Any, [{"role": "user", "content": content}]),
        store=False,
    )
    return response.output_text.strip()


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
