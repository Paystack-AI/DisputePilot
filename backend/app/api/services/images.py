"""Validation and cleaning of uploaded images. CPU bound: run it in the threadpool."""

import warnings
from dataclasses import dataclass
from io import BytesIO

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings

SETTINGS = get_settings()

# iPhone photos (HEIC/HEIF) open through this plugin
pillow_heif.register_heif_opener()

# images bigger than this raise instead of being decoded (decompression bombs)
Image.MAX_IMAGE_PIXELS = SETTINGS.UPLOAD_MAX_IMAGE_PIXELS

# detected format -> (format it is stored as, content type, extension)
OUTPUT_FORMATS: dict[str, tuple[str, str, str]] = {
    "JPEG": ("JPEG", "image/jpeg", ".jpg"),
    "PNG": ("PNG", "image/png", ".png"),
    "WEBP": ("WEBP", "image/webp", ".webp"),
    # HEIC is stored as JPEG so every browser can show it
    "HEIF": ("JPEG", "image/jpeg", ".jpg"),
}


class NotAnImageError(Exception):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    extension: str
    width: int
    height: int


def process_image(data: bytes) -> ProcessedImage:
    """Checks the bytes are a supported image by decoding them (the client's content type
    and file name are never trusted), then re-saves it upright and without metadata: the
    location, device and time a photo carries are dropped (data minimisation), and
    re-encoding also discards anything hidden in the original file"""
    try:
        with warnings.catch_warnings():
            # past MAX_IMAGE_PIXELS pillow only warns until twice the limit; treat it as fatal
            warnings.simplefilter("error", Image.DecompressionBombWarning)

            with Image.open(BytesIO(data)) as probe:
                detected: str | None = probe.format
                probe.verify()  # structural check without decoding all pixels

            if detected not in OUTPUT_FORMATS:
                raise NotAnImageError(detected)

            with Image.open(BytesIO(data)) as image:
                image.load()
                # apply the camera's rotation tag before the metadata holding it is dropped
                upright: Image.Image = ImageOps.exif_transpose(image)
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise NotAnImageError(str(exc)) from exc

    output_format, content_type, extension = OUTPUT_FORMATS[detected]

    if output_format == "JPEG" and upright.mode not in ("RGB", "L"):
        upright = upright.convert("RGB")

    # only the colour profile is kept: it is not personal and keeps colours accurate
    icc_profile: bytes | None = upright.info.get("icc_profile")
    upright.info = {}

    save_options: dict = {"optimize": True}
    if output_format in ("JPEG", "WEBP"):
        save_options["quality"] = 90
    if icc_profile:
        save_options["icc_profile"] = icc_profile

    buffer = BytesIO()
    upright.save(buffer, output_format, **save_options)

    return ProcessedImage(
        data=buffer.getvalue(),
        content_type=content_type,
        extension=extension,
        width=upright.width,
        height=upright.height,
    )
