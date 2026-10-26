"""Image encoding shared by the newsletter's post-image finder and page captures."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

from PIL import Image

ScreenshotMediaType = Literal["image/jpeg", "image/png"]
# Matches the email's black ground so transparent artwork does not flash white.
_GROUND_RGBA = (0, 0, 0, 255)


class ScreenshotError(RuntimeError):
    """An image could not be captured or decoded; the highlight continues without it."""


@dataclass(frozen=True)
class SiteScreenshot:
    data: bytes
    media_type: ScreenshotMediaType
    width: int
    height: int


def encode_jpeg(source: bytes, *, max_width: int, quality: int) -> SiteScreenshot:
    """Decode any Pillow-readable image, flatten transparency, downscale, and emit a JPEG."""

    try:
        with Image.open(io.BytesIO(source)) as image:
            image.load()
            if image.mode in {"RGBA", "LA", "P"}:
                rgba = image.convert("RGBA")
                ground = Image.new("RGBA", rgba.size, _GROUND_RGBA)
                rgb = Image.alpha_composite(ground, rgba).convert("RGB")
            else:
                rgb = image.convert("RGB")
    except (OSError, ValueError) as error:
        raise ScreenshotError("The image could not be decoded.") from error
    if rgb.width > max_width:
        height = max(1, round(rgb.height * max_width / rgb.width))
        rgb = rgb.resize((max_width, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return SiteScreenshot(
        data=buffer.getvalue(),
        media_type="image/jpeg",
        width=rgb.width,
        height=rgb.height,
    )


def still_png(
    source: bytes, *, min_width: int, min_height: int, max_width: int
) -> tuple[bytes, int, int]:
    """Decode a published still (a video poster), flatten it, and return PNG bytes and size."""

    try:
        with Image.open(io.BytesIO(source)) as image:
            image.load()
            rgba = image.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ScreenshotError("The still could not be decoded.") from error
    if rgba.width < min_width or rgba.height < min_height:
        raise ScreenshotError("The still is too small to feature.")
    rgb = Image.alpha_composite(Image.new("RGBA", rgba.size, _GROUND_RGBA), rgba).convert("RGB")
    if rgb.width > max_width:
        height = max(1, round(rgb.height * max_width / rgb.width))
        rgb = rgb.resize((max_width, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), rgb.width, rgb.height
