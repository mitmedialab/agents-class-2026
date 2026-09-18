"""Derived first-slide assets for indexed course decks."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image

from course_server.agent.document_inspection import render_pdf_page

FIRST_SLIDE_ASSET_ID = "first_slide"
# Enough pixels for a sharp small preview on high-density displays.
THUMBNAIL_EDGE = 320


def generate_slide_thumbnail(pdf_path: Path, shared_root: Path) -> str:
    data = pdf_path.read_bytes()
    digest = sha256(data).hexdigest()
    directory = (shared_root / "registry/slide-thumbnails").resolve()
    if not directory.is_relative_to(shared_root.resolve()):
        raise ValueError("slide thumbnail directory must remain within shared resources")
    target = directory / f"{digest}.png"
    if not target.exists():
        rendered = render_pdf_page(data, 1)
        with Image.open(BytesIO(rendered.png)) as image:
            image.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)
            directory.mkdir(parents=True, exist_ok=True)
            image.save(target, format="PNG")
    return target.relative_to(shared_root).as_posix()
