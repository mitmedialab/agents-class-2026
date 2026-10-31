"""Public, client-neutral setup instructions for the remote Course MCP."""

from __future__ import annotations

from html import escape
from pathlib import Path

from starlette.responses import HTMLResponse

_SETUP_TEMPLATE = Path(__file__).resolve().parents[2] / "mcp/ai-connect.html"


def course_mcp_setup_page(public_base_url: str) -> HTMLResponse:
    endpoint = escape(f"{public_base_url.rstrip('/')}/mcp", quote=True)
    page = _SETUP_TEMPLATE.read_text(encoding="utf-8").replace("{{MCP_ENDPOINT}}", endpoint)
    return HTMLResponse(
        page,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
