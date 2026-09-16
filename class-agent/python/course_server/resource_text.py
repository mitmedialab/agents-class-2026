"""Extract agent- and search-readable text from registered course resources."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

PDF_MEDIA_TYPE = "application/pdf"


class ResourceTextExtractionError(ValueError):
    """Raised when registered resource bytes cannot be decoded for text access."""


def extract_resource_text(data: bytes, media_type: str) -> str:
    """Return UTF-8 or embedded PDF text without changing the original resource bytes."""

    normalized_media_type = media_type.partition(";")[0].strip().casefold()
    if normalized_media_type == PDF_MEDIA_TYPE:
        return _extract_pdf_text(data)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ResourceTextExtractionError("resource is not valid UTF-8 text") from error


def _extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        pages: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"--- Page {page_number} ---\n{text}")
        return "\n\n".join(pages)
    except (OSError, PdfReadError, ValueError) as error:
        raise ResourceTextExtractionError("resource is not a readable PDF") from error
