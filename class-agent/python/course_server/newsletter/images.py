"""Find the best visual a student published for the week's build, or fall back to a capture.

Discovery is deterministic: the student's site root is opened in headless Chromium, links
that name the week lead to the post, and the visual elements rendered there (images, SVG
figures, canvases, videos and their poster stills) are measured and captured. The model only
chooses among those captures; platform code re-encodes the chosen one for email.

A post is captured the way a visitor sees it. The page settles first (lazy images load, web
fonts arrive), broken images are skipped, and a post that is only an HTML fragment, which the
site's own script loads into its styled shell, is read against the site root as that shell
reads it, so its relative media resolve. A fragment is never screenshotted bare.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, ViewportSize, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .models import CourseWeek
from .screenshots import ScreenshotError, SiteScreenshot, encode_jpeg, still_png

ImageKind = Literal["post_image", "screenshot"]
_MAX_STATIC_HTML_BYTES = 2 * 1024 * 1024
_MAX_STILL_BYTES = 15 * 1024 * 1024
_MIN_WIDTH = 280
_MIN_HEIGHT = 140
_STILL_MAX_WIDTH = 1600
_VISUAL_TAGS = frozenset({"img", "svg", "canvas", "video"})
_ANCHORS_JS = (
    "() => Array.from(document.querySelectorAll('a[href]')).map(a => "
    "({href: a.getAttribute('href') || '', text: (a.innerText || a.textContent || "
    "a.getAttribute('aria-label') || '').trim().slice(0, 120)}))"
)
# Lets the page finish what a visitor's scroll would start: lazy images load, fonts arrive.
_SETTLE_JS = """async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  document.querySelectorAll('img[loading="lazy"]').forEach((img) => { img.loading = 'eager'; });
  const step = Math.max(300, Math.floor(window.innerHeight * 0.9));
  const end = Math.min(document.documentElement.scrollHeight, step * 40);
  for (let y = step; y < end; y += step) { window.scrollTo(0, y); await wait(40); }
  window.scrollTo(0, 0);
  const pending = Array.from(document.images).filter((img) => !img.complete);
  await Promise.race([
    Promise.all(pending.map((img) => new Promise((resolve) => {
      img.addEventListener('load', resolve, {once: true});
      img.addEventListener('error', resolve, {once: true});
    }))),
    wait(5000),
  ]);
  if (document.fonts && document.fonts.ready) {
    await Promise.race([document.fonts.ready, wait(3000)]);
  }
  return true;
}"""
# Tags every visual element with its index so a chosen candidate can be captured later.
_VISUALS_JS = (
    "() => Array.from(document.querySelectorAll('img, svg, canvas, video')).map((el, i) => {"
    "  el.setAttribute('data-nl-idx', String(i));"
    "  if (el.tagName === 'VIDEO') { try { el.muted = true; el.controls = false;"
    "    el.preload = 'auto'; if (el.readyState < 2) { el.load(); } el.currentTime = 1; }"
    "    catch (e) {} }"
    "  const r = el.getBoundingClientRect();"
    "  const style = window.getComputedStyle(el);"
    "  const broken = el.tagName === 'IMG' && (!el.complete || el.naturalWidth === 0);"
    "  return {index: i, tag: el.tagName.toLowerCase(), width: Math.round(r.width),"
    "    height: Math.round(r.height), alt: (el.getAttribute('alt') || "
    "    el.getAttribute('aria-label') || el.getAttribute('title') || '').slice(0, 200),"
    "    src: el.currentSrc || el.src || '',"
    "    poster: el.tagName === 'VIDEO' ? (el.poster || '') : '',"
    "    visible: !broken && style.visibility !== 'hidden' && "
    "    style.display !== 'none' && Number(style.opacity || '1') > 0.05};"
    "})"
)


@dataclass(frozen=True)
class ImageCandidate:
    index: int
    tag: str
    width: int
    height: int
    alt: str
    src: str
    page_url: str
    # A video's poster still, as the browser resolved it; the author's own chosen frame.
    poster: str = ""

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class FoundImage:
    shot: SiteScreenshot
    kind: ImageKind
    page_url: str
    source_url: str | None = None
    # The page is a fragment shown inside the site's shell, not a page to send readers to.
    page_is_fragment: bool = False


class ImageJudge(Protocol):
    """Returns the 1-based index of the best capture, or 0 when none is suitable."""

    def __call__(self, *, prompt: str, images: Sequence[bytes]) -> int: ...


class HighlightImageFinder(Protocol):
    def find(
        self, *, site_url: str, week: CourseWeek, context: str, post_url: str | None = None
    ) -> FoundImage | None: ...


def week_page_pattern(week_number: int) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![a-z0-9])(week|wk|w)[\s_./-]?0*{week_number}(?![0-9])",
        re.IGNORECASE,
    )


def discover_week_pages(
    anchors: Sequence[Mapping[str, object]],
    *,
    site_url: str,
    week: CourseWeek,
    limit: int = 3,
) -> list[str]:
    """Same-site links whose target or text names the week, in page order, root excluded."""

    return [
        page
        for page in discover_week_targets(anchors, site_url=site_url, week=week, limit=limit)
        if urlsplit(page).fragment == ""
    ]


def discover_week_anchor(
    anchors: Sequence[Mapping[str, object]],
    *,
    site_url: str,
    week: CourseWeek,
) -> str | None:
    """A same-page `#section` link naming the week, for single-page sites."""

    return next(
        (
            target
            for target in discover_week_targets(anchors, site_url=site_url, week=week, limit=10)
            if urlsplit(target).fragment
        ),
        None,
    )


def discover_week_targets(
    anchors: Sequence[Mapping[str, object]],
    *,
    site_url: str,
    week: CourseWeek,
    limit: int,
) -> list[str]:
    pattern = week_page_pattern(week.number)
    root_host = urlsplit(site_url).hostname
    root_page = urldefrag(site_url).url.rstrip("/")
    found: list[str] = []
    for anchor in anchors:
        href = anchor.get("href")
        text = anchor.get("text")
        if not isinstance(href, str):
            continue
        absolute = urljoin(site_url, href)
        page, fragment = urldefrag(absolute)
        parsed = urlsplit(page)
        if parsed.scheme != "https" or parsed.hostname != root_host:
            continue
        if not (pattern.search(href) or (isinstance(text, str) and pattern.search(text))):
            continue
        on_root = page.rstrip("/") == root_page
        if on_root and (not fragment or not pattern.search(fragment)):
            continue
        # Fragments matter only on the root page, where they name a week section.
        target = f"{page}#{fragment}" if on_root else page
        if target not in found:
            found.append(target)
            if len(found) >= limit:
                break
    return found


def static_html(url: str, *, timeout_seconds: float = 15.0) -> str | None:
    """The HTML a public page serves before any script runs, or None."""

    try:
        with httpx.Client(
            follow_redirects=True, max_redirects=5, timeout=timeout_seconds
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            media_type = response.headers.get("content-type", "").partition(";")[0].strip()
            if not media_type.casefold().startswith("text/html"):
                return None
            return response.content[:_MAX_STATIC_HTML_BYTES].decode(
                response.encoding or "utf-8", errors="replace"
            )
    except httpx.HTTPError:
        return None


def is_html_fragment(html: str) -> bool:
    """A partial page a site's script inserts into its shell: no document, no styles of its own."""

    soup = BeautifulSoup(html, "html.parser")
    if soup.find(True) is None or soup.find(["html", "head", "body", "style"]) is not None:
        return False
    return not any("stylesheet" in (link.get("rel") or []) for link in soup.find_all("link"))


def fragment_shell(fragment: str, *, base_url: str) -> str:
    """A document that reads a fragment against the page that loads it, as the site does."""

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<base href="{escape(base_url, quote=True)}"></head><body>{fragment}</body></html>'
    )


def static_anchors(site_url: str, *, timeout_seconds: float = 15.0) -> list[dict[str, object]]:
    """Links present in the served HTML, for sites whose scripts replace the DOM on load."""

    html = static_html(site_url, timeout_seconds=timeout_seconds)
    if html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    anchors: list[dict[str, object]] = []
    for element in soup.select("a[href]"):
        href = element.get("href")
        if isinstance(href, str):
            anchors.append({"href": href, "text": element.get_text(" ", strip=True)[:120]})
    return anchors


@dataclass(frozen=True)
class RenderedPost:
    url: str
    text: str


# The week's own section when the page keeps it under that id, otherwise the whole page.
_POST_TEXT_JS = """(id) => {
  const section = id ? document.getElementById(id) : null;
  const node = section && section.innerText.trim() ? section : document.body;
  return node ? node.innerText : '';
}"""


def read_rendered_week_post(
    site_url: str,
    week: CourseWeek,
    *,
    executable_path: Path | None = None,
    timeout_ms: int = 20_000,
    settle_ms: int = 800,
) -> RenderedPost | None:
    """The week's post as a visitor's browser shows it, for sites whose scripts build links.

    Static discovery reads served HTML, which misses a menu a script renders and a post whose
    script fills in its text. This opens the site root in headless Chromium, follows the first
    same-site link that names the week, and returns that page's visible text. Errors propagate
    so the collector can note them.
    """

    parsed = urlsplit(site_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(executable_path) if executable_path is not None else None,
        )
        try:
            page = browser.new_page()

            def visit(url: str) -> None:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                with contextlib.suppress(PlaywrightTimeoutError):
                    page.wait_for_load_state("networkidle", timeout=5_000)
                page.wait_for_timeout(settle_ms)

            visit(site_url)
            anchors = page.evaluate(_ANCHORS_JS)
            rendered = anchors if isinstance(anchors, list) else []
            posts = discover_week_pages(rendered, site_url=site_url, week=week)
            # A single-page site shows the week as a section its script opens from `#week-NN`.
            target = (
                posts[0] if posts else discover_week_anchor(rendered, site_url=site_url, week=week)
            )
            if target is None:
                return None
            visit(target)
            text = page.evaluate(_POST_TEXT_JS, urlsplit(target).fragment)
        finally:
            browser.close()
    if not isinstance(text, str) or not text.strip():
        return None
    return RenderedPost(url=target, text=text)


def filter_candidates(
    raw_visuals: Sequence[Mapping[str, object]],
    *,
    page_url: str,
    min_width: int = _MIN_WIDTH,
    min_height: int = _MIN_HEIGHT,
    limit: int = 4,
) -> list[ImageCandidate]:
    """Keep visible, reasonably sized visual elements, biggest first, one per source."""

    candidates: list[ImageCandidate] = []
    seen_sources: set[str] = set()
    for raw in raw_visuals:
        index = raw.get("index")
        tag = raw.get("tag")
        width = raw.get("width")
        height = raw.get("height")
        if (
            not isinstance(index, int)
            or not isinstance(tag, str)
            or tag not in _VISUAL_TAGS
            or not isinstance(width, int)
            or not isinstance(height, int)
            or raw.get("visible") is False
        ):
            continue
        if width < min_width or height < min_height:
            continue
        ratio = width / height
        if ratio < 0.4 or ratio > 4.0:
            continue
        src = raw.get("src")
        source = src if isinstance(src, str) else ""
        if source.startswith("data:"):
            source = ""
        if source and source in seen_sources:
            continue
        if source:
            seen_sources.add(source)
        alt = raw.get("alt")
        poster = raw.get("poster")
        candidates.append(
            ImageCandidate(
                index=index,
                tag=tag,
                width=width,
                height=height,
                alt=alt if isinstance(alt, str) else "",
                src=source,
                page_url=page_url,
                poster=poster if isinstance(poster, str) and poster.startswith("https://") else "",
            )
        )
    return sorted(candidates, key=lambda item: -item.area)[:limit]


def build_judge_prompt(
    *, context: str, week: CourseWeek, candidates: Sequence[ImageCandidate]
) -> str:
    listing = "\n".join(
        f"{index}. {candidate.tag} {candidate.width}x{candidate.height}"
        + (f' alt="{candidate.alt}"' if candidate.alt else "")
        for index, candidate in enumerate(candidates, start=1)
    )
    return (
        "Choose the one image that best represents this student's build for a class "
        "newsletter highlight. Prefer a rendered result, demo, visualization, diagram, or "
        "artifact the student made for the assignment. Avoid logos, icons, portraits, stock "
        "decoration, blank or mostly empty frames, and images that are mostly small text. "
        "If none is suitable, answer 0.\n\n"
        f"Week {week.number} assignment: {week.tutorial}\n"
        f"Build: {context}\n\nCandidates:\n{listing}\n\n"
        'Respond with JSON only: {"choice": <number>, "reason": "<one sentence>"}'
    )


class PlaywrightImageFinder:
    """One headless Chromium session per build: discover the post, capture visuals, choose."""

    def __init__(
        self,
        *,
        judge: ImageJudge | None = None,
        executable_path: Path | None = None,
        viewport_width: int = 1200,
        viewport_height: int = 750,
        device_scale_factor: int = 2,
        output_width: int = 1200,
        timeout_ms: int = 20_000,
        settle_ms: int = 800,
        jpeg_quality: int = 84,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._judge = judge
        self._executable_path = executable_path
        self._viewport: ViewportSize = {"width": viewport_width, "height": viewport_height}
        self._device_scale_factor = device_scale_factor
        self._output_width = output_width
        self._timeout_ms = timeout_ms
        self._settle_ms = settle_ms
        self._jpeg_quality = jpeg_quality
        self._log = log or (lambda message: None)

    def find(
        self, *, site_url: str, week: CourseWeek, context: str, post_url: str | None = None
    ) -> FoundImage | None:
        """`post_url` is the week's post when evidence collection already found it."""

        parsed = urlsplit(site_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ScreenshotError("Only public https sites are inspected.")
        known = (
            [post_url]
            if post_url is not None and urlsplit(post_url).hostname == parsed.hostname
            else []
        )
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=(
                        str(self._executable_path) if self._executable_path is not None else None
                    ),
                )
                try:
                    browser_context = browser.new_context(
                        viewport=self._viewport,
                        device_scale_factor=self._device_scale_factor,
                    )
                    page = self._open(browser_context, site_url)
                    rendered = page.evaluate(_ANCHORS_JS)
                    # Rendered links first, then the served HTML: single-page apps often
                    # replace the DOM and drop the plain links the template shipped with.
                    anchors = [
                        *(rendered if isinstance(rendered, list) else []),
                        *static_anchors(site_url),
                    ]
                    week_pages = discover_week_pages(anchors, site_url=site_url, week=week)
                    week_anchor = discover_week_anchor(anchors, site_url=site_url, week=week)
                    # Root visuals are considered only when the site has no week post; a
                    # landing-page graphic must not outrank a capture of the actual post. The
                    # post evidence collection found comes first: it may be one no link names.
                    scan = list(dict.fromkeys([*known, *week_pages])) or [week_anchor or site_url]
                    fragments: set[str] = set()
                    for page_url in scan:
                        if page_url != site_url:
                            shell = self._fragment_shell(page_url, site_url=site_url)
                            if shell is not None:
                                fragments.add(page_url)
                            opened = self._try_open(browser_context, page_url, shell=shell)
                            if opened is None:
                                continue
                            page = opened
                        found = self._capture_best(page, page_url, week=week, context=context)
                        if found is not None:
                            return replace(found, page_is_fragment=page_url in fragments)
                    # A fragment on its own is unstyled; the site root is what visitors see.
                    fallback_url = site_url if scan[0] in fragments else scan[0]
                    fallback = self._try_open(browser_context, fallback_url)
                    if fallback is None:
                        fallback_url, fallback = page.url, page
                    self._settle(fallback)
                    png = fallback.screenshot(
                        type="png",
                        full_page=False,
                        animations="disabled",
                        timeout=self._timeout_ms,
                    )
                finally:
                    browser.close()
        except (PlaywrightError, PlaywrightTimeoutError) as error:
            detail = str(error).splitlines()[0][:120] if str(error) else ""
            raise ScreenshotError(
                f"Site inspection failed ({type(error).__name__}: {detail})."
            ) from error
        return FoundImage(
            shot=encode_jpeg(png, max_width=self._output_width, quality=self._jpeg_quality),
            kind="screenshot",
            page_url=fallback_url,
        )

    def _fragment_shell(self, page_url: str, *, site_url: str) -> str | None:
        served = static_html(page_url)
        if served is None or not is_html_fragment(served):
            return None
        self._log(f"    {page_url}: a fragment the site loads into its shell; reading it there")
        return fragment_shell(served, base_url=site_url)

    def _try_open(
        self, browser_context: BrowserContext, url: str, *, shell: str | None = None
    ) -> Page | None:
        """Open a URL in a fresh tab; a stalled load still counts once the document arrived."""

        try:
            return self._open(browser_context, url, shell=shell)
        except PlaywrightTimeoutError:
            page = browser_context.pages[-1] if browser_context.pages else None
            arrived = page is not None and (
                page.url.split("#", 1)[0].rstrip("/") == url.split("#", 1)[0].rstrip("/")
            )
            self._log(
                f"    {url}: load timed out; {'using partial page' if arrived else 'skipped'}"
            )
            return page if arrived else None

    def _open(self, browser_context: BrowserContext, url: str, *, shell: str | None = None) -> Page:
        """Each page gets its own tab so a student's root app cannot block later navigation."""

        self._log(f"    opening {url}")
        page = browser_context.new_page()
        if shell is not None:
            document = urldefrag(url).url
            page.route(
                lambda requested: urldefrag(requested).url == document,
                lambda route: route.fulfill(
                    status=200, content_type="text/html; charset=utf-8", body=shell
                ),
            )
        # domcontentloaded: a hanging third-party resource must not block the whole capture.
        page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
        with contextlib.suppress(PlaywrightTimeoutError):
            page.wait_for_load_state("networkidle", timeout=5_000)
        page.wait_for_timeout(self._settle_ms)
        return page

    def _settle(self, page: Page) -> None:
        """Load what a visitor's scroll would load, and wait for web fonts, before capturing."""

        try:
            page.evaluate(_SETTLE_JS)
        except (PlaywrightError, PlaywrightTimeoutError) as error:
            self._log(f"    page did not settle ({type(error).__name__}); capturing as is")

    def _still(self, page: Page, candidate: ImageCandidate) -> tuple[ImageCandidate, bytes] | None:
        """A video's poster, fetched as published; the author picked this frame to represent it."""

        try:
            response = page.request.get(candidate.poster, timeout=self._timeout_ms)
            if not response.ok:
                return None
            data = response.body()
        except (PlaywrightError, PlaywrightTimeoutError):
            return None
        if len(data) > _MAX_STILL_BYTES:
            return None
        try:
            png, width, height = still_png(
                data, min_width=_MIN_WIDTH, min_height=_MIN_HEIGHT, max_width=_STILL_MAX_WIDTH
            )
        except ScreenshotError as error:
            self._log(f"    poster for video #{candidate.index}: {error}")
            return None
        still = replace(
            candidate, tag="video poster", width=width, height=height, src=candidate.poster
        )
        return still, png

    def _capture_best(
        self, page: Page, page_url: str, *, week: CourseWeek, context: str
    ) -> FoundImage | None:
        self._settle(page)
        raw_visuals = page.evaluate(_VISUALS_JS)
        if isinstance(raw_visuals, list) and any(
            isinstance(item, dict) and item.get("tag") == "video" for item in raw_visuals
        ):
            page.wait_for_timeout(self._settle_ms)  # let a nudged video paint a frame
        candidates = filter_candidates(
            raw_visuals if isinstance(raw_visuals, list) else [], page_url=page_url
        )
        captures: list[tuple[ImageCandidate, bytes]] = []
        for candidate in candidates:
            if candidate.tag == "video" and candidate.poster:
                still = self._still(page, candidate)
                if still is not None:
                    captures.append(still)
                    continue
            locator = page.locator(f'[data-nl-idx="{candidate.index}"]').first
            if candidate.tag == "video" and not self._video_has_frame(page, candidate.index):
                self._log(f"    video #{candidate.index}: no frame loaded; skipped")
                continue
            try:
                png = locator.screenshot(
                    type="png", animations="disabled", timeout=self._timeout_ms
                )
            except (PlaywrightError, PlaywrightTimeoutError) as error:
                self._log(
                    f"    {candidate.tag} #{candidate.index}: capture failed "
                    f"({type(error).__name__})"
                )
                continue
            captures.append((candidate, png))
        if not captures:
            return None
        chosen = self._choose(captures, week=week, context=context)
        if chosen is None:
            return None
        candidate, png = chosen
        try:
            shot = encode_jpeg(png, max_width=self._output_width, quality=self._jpeg_quality)
        except ScreenshotError as error:
            self._log(f"    {candidate.tag} #{candidate.index}: {error}")
            return None
        return FoundImage(
            shot=shot,
            kind="post_image",
            page_url=page_url,
            source_url=candidate.src or None,
        )

    def _video_has_frame(self, page: Page, index: int) -> bool:
        """Give a nudged video a few seconds to decode a frame; a spinner is not a picture."""

        selector = f'[data-nl-idx="{index}"]'
        with contextlib.suppress(PlaywrightError, PlaywrightTimeoutError):
            page.wait_for_function(
                "selector => { const v = document.querySelector(selector);"
                " return !!v && v.readyState >= 2; }",
                arg=selector,
                timeout=6_000,
            )
        ready = page.evaluate(
            "selector => { const v = document.querySelector(selector);"
            " return v ? v.readyState : 0; }",
            selector,
        )
        return isinstance(ready, int) and ready >= 2

    def _choose(
        self,
        captures: Sequence[tuple[ImageCandidate, bytes]],
        *,
        week: CourseWeek,
        context: str,
    ) -> tuple[ImageCandidate, bytes] | None:
        # Even a single capture is judged, so a blank frame or logo can be rejected.
        if self._judge is None:
            return captures[0]
        try:
            choice = self._judge(
                prompt=build_judge_prompt(
                    context=context,
                    week=week,
                    candidates=[candidate for candidate, _ in captures],
                ),
                images=[png for _, png in captures],
            )
        except Exception as error:  # the judge is advisory; fall back to the largest visual
            self._log(f"    image judge unavailable ({type(error).__name__}); using largest")
            return captures[0]
        if choice <= 0:
            return None
        return captures[min(choice, len(captures)) - 1]
