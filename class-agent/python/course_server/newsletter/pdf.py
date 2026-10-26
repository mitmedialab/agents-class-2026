"""Render a stored issue's HTML preview to a single-page PDF for sharing and feedback."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .store import FileNewsletterStore, NewsletterStoreError

PAGE_WIDTH_PX = 720
_MAX_HEIGHT_PX = 20_000


def export_pdf(
    store: FileNewsletterStore,
    issue_id: str,
    *,
    executable_path: Path | None = None,
    timeout_ms: int = 30_000,
) -> Path:
    """Write `<issue_id>.pdf` beside the HTML preview, as one tall page with images inline."""

    _, _, html_path = store.paths_for(issue_id)
    if not html_path.is_file():
        raise NewsletterStoreError(f"Issue {issue_id} has no HTML preview to export.")
    pdf_path = store.pdf_path(issue_id)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=str(executable_path) if executable_path is not None else None,
            )
            try:
                page = browser.new_page(viewport={"width": PAGE_WIDTH_PX, "height": 1000})
                page.goto(html_path.resolve().as_uri(), wait_until="load", timeout=timeout_ms)
                page.wait_for_timeout(300)
                height = page.evaluate("() => document.documentElement.scrollHeight")
                total = min(
                    int(height) if isinstance(height, int | float) else 1000, _MAX_HEIGHT_PX
                )
                page.pdf(
                    path=str(pdf_path),
                    width=f"{PAGE_WIDTH_PX}px",
                    height=f"{total + 40}px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            finally:
                browser.close()
    except (PlaywrightError, PlaywrightTimeoutError) as error:
        raise NewsletterStoreError(f"PDF export failed ({type(error).__name__}).") from error
    return pdf_path
