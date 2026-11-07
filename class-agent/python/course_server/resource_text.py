"""Extract agent- and search-readable text from registered course resources."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

PDF_MEDIA_TYPE = "application/pdf"


class ResourceTextExtractionError(ValueError):
    """Raised when registered resource bytes cannot be decoded for text access."""


def load_slide_accessibility(path: Path) -> tuple[str, ...]:
    """Read numbered, human-maintained slide descriptions from a registered sidecar."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ResourceTextExtractionError("slide accessibility text is unreadable") from error
    descriptions: list[str] = []
    for line in lines:
        match = re.fullmatch(r"([1-9][0-9]*) \| (.+)", line)
        if match is None or int(match.group(1)) != len(descriptions) + 1:
            raise ResourceTextExtractionError("slide accessibility pages must be consecutive")
        description = match.group(2).strip()
        if not description:
            raise ResourceTextExtractionError("slide accessibility description is empty")
        descriptions.append(description)
    if not descriptions:
        raise ResourceTextExtractionError("slide accessibility text is empty")
    return tuple(descriptions)


def load_slide_captions(path: Path) -> dict[int, str]:
    """Read sparse, page-numbered contextual captions for visual slides."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ResourceTextExtractionError("slide captions are unreadable") from error
    captions: dict[int, str] = {}
    last_page = 0
    for line in lines:
        match = re.fullmatch(r"([1-9][0-9]*) \| (.+)", line)
        if match is None:
            raise ResourceTextExtractionError("slide captions must be page-numbered")
        page = int(match.group(1))
        if page <= last_page:
            raise ResourceTextExtractionError("slide caption pages must increase")
        caption = match.group(2).strip()
        if not caption:
            raise ResourceTextExtractionError("slide caption is empty")
        captions[page] = caption
        last_page = page
    if not captions:
        raise ResourceTextExtractionError("slide captions are empty")
    return captions


def extract_resource_text(
    data: bytes,
    media_type: str,
    *,
    slide_descriptions: Sequence[str] | None = None,
    slide_captions: Mapping[int, str] | None = None,
) -> str:
    """Return UTF-8 or embedded PDF text without changing the original resource bytes."""

    normalized_media_type = media_type.partition(";")[0].strip().casefold()
    if normalized_media_type == PDF_MEDIA_TYPE:
        return _extract_pdf_text(
            data, slide_descriptions=slide_descriptions, slide_captions=slide_captions
        )
    if slide_descriptions is not None or slide_captions is not None:
        raise ResourceTextExtractionError("slide descriptions and captions require a PDF")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ResourceTextExtractionError("resource is not valid UTF-8 text") from error


def _extract_pdf_text(
    data: bytes,
    *,
    slide_descriptions: Sequence[str] | None,
    slide_captions: Mapping[int, str] | None,
) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        if slide_descriptions is not None and len(slide_descriptions) != len(reader.pages):
            raise ResourceTextExtractionError("slide description count does not match PDF pages")
        if slide_captions is not None and any(
            not isinstance(page, int)
            or isinstance(page, bool)
            or page < 1
            or page > len(reader.pages)
            for page in slide_captions
        ):
            raise ResourceTextExtractionError("slide caption page is outside PDF")
        pages: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            description = (
                f"Accessibility description: {slide_descriptions[page_number - 1]}"
                if slide_descriptions is not None
                else ""
            )
            caption = (
                f"Slide caption: {slide_captions[page_number]}"
                if slide_captions is not None and page_number in slide_captions
                else ""
            )
            if text or description or caption:
                body = "\n".join(part for part in (description, caption, text) if part)
                pages.append(f"--- Page {page_number} ---\n{body}")
        return "\n\n".join(pages)
    except ResourceTextExtractionError:
        raise
    except (OSError, PdfReadError, ValueError) as error:
        raise ResourceTextExtractionError("resource is not a readable PDF") from error
