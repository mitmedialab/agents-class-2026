"""Third-party public search adapters used behind application-owned tools."""

from __future__ import annotations

from typing import Any

from ddgs import DDGS


def search_duckduckgo_images(query: str, max_results: int) -> list[dict[str, object]]:
    """Search images with an isolated, DuckDuckGo-first DDGS client per request."""

    results: list[dict[str, Any]] = DDGS(timeout=8).images(
        query,
        backend="duckduckgo,bing",
        max_results=max_results,
        safesearch="moderate",
    )
    return [dict(result) for result in results]
