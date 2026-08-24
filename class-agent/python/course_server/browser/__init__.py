"""Remote browser contracts and adapters."""

from .constants import (
    BROWSER_COMPARE_TOOL_ID,
    BROWSER_COMPONENT_ID,
    BROWSER_HIGHLIGHT_TEXT_TOOL_ID,
    BROWSER_NAVIGATE_TOOL_ID,
    BROWSER_OPEN_TOOL_ID,
    BROWSER_SCROLL_TOOL_ID,
    BROWSER_TOOL_IDS,
    PAGE_CARDS_COMPONENT_ID,
)
from .models import (
    BrowserCapacityReached,
    BrowserError,
    BrowserNavigationError,
    BrowserPage,
    BrowserPreview,
    BrowserPreviewSnapshot,
    BrowserSecurityError,
    BrowserSessionNotFound,
    BrowserSessionService,
    BrowserSnapshot,
    BrowserUnavailable,
)
from .playwright_service import (
    PlaywrightBrowserSessionService,
    ThreadedPlaywrightBrowserSessionService,
    validate_public_https_url,
)

__all__ = [
    "BROWSER_COMPARE_TOOL_ID",
    "BROWSER_COMPONENT_ID",
    "BROWSER_HIGHLIGHT_TEXT_TOOL_ID",
    "BROWSER_NAVIGATE_TOOL_ID",
    "BROWSER_OPEN_TOOL_ID",
    "BROWSER_SCROLL_TOOL_ID",
    "BROWSER_TOOL_IDS",
    "PAGE_CARDS_COMPONENT_ID",
    "BrowserCapacityReached",
    "BrowserError",
    "BrowserNavigationError",
    "BrowserPage",
    "BrowserPreview",
    "BrowserPreviewSnapshot",
    "BrowserSecurityError",
    "BrowserSessionNotFound",
    "BrowserSessionService",
    "BrowserSnapshot",
    "BrowserUnavailable",
    "PlaywrightBrowserSessionService",
    "ThreadedPlaywrightBrowserSessionService",
    "validate_public_https_url",
]
