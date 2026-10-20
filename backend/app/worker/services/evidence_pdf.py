"""The evidence pdf: html from a jinja template, printed with weasyprint.

Rendered from the snapshot frozen at submit, so the pdf shows exactly what the merchant
approved. Images are resized to at most 800px wide (spec 6.2) and embedded, so the pdf is
self-contained and stays well under paystack's upload limits.
"""

import base64
import re
from collections.abc import Callable
from datetime import datetime
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from PIL import Image, ImageOps

MAX_IMAGE_WIDTH: int = 800
JPEG_QUALITY: int = 80

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _datetime(value) -> str:
    parsed = _parse(value)
    return f"{parsed:%d %B %Y, %H:%M} UTC" if parsed else "—"


def _date(value) -> str:
    parsed = _parse(value)
    return f"{parsed:%d %B %Y}" if parsed else "—"


def _money(amount: int | None, currency: str) -> str:
    if amount is None:
        return "—"
    return f"{currency} {amount / 100:,.2f}"


def _humanize(value: str | None) -> str:
    return (value or "").replace("_", " ").capitalize()


def _paragraphs(text: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _css_string(value) -> Markup:
    """Safe inside a quoted css string (the page footer), where html escaping does not apply"""
    text: str = str(value or "")
    escaped: str = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    escaped = escaped.replace("<", "\\3C ").replace(">", "\\3E ")
    return Markup(escaped)


_env = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters.update(
    datetime=_datetime,
    date=_date,
    money=_money,
    humanize=_humanize,
    paragraphs=_paragraphs,
    css_string=_css_string,
)


def prepare_image(content: bytes) -> str:
    """A data uri of the image, rotated upright and at most MAX_IMAGE_WIDTH wide"""
    with Image.open(BytesIO(content)) as image:
        image = ImageOps.exif_transpose(image)
        if image.width > MAX_IMAGE_WIDTH:
            height: int = round(image.height * MAX_IMAGE_WIDTH / image.width)
            image = image.resize((MAX_IMAGE_WIDTH, height), Image.Resampling.LANCZOS)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        out = BytesIO()
        image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def _exhibits(document: dict) -> list[dict]:
    """Every image in the document, in order: fulfillment photos, then the merchant's"""
    refs: list[dict] = []
    for fulfillment in document.get("fulfillment_evidence") or []:
        for photo in fulfillment.get("photos") or []:
            refs.append(photo)
    refs.extend(document.get("supporting_documents") or [])
    return refs


def evidence_html(snapshot: dict, fetch: Callable[[str], bytes]) -> str:
    """fetch(object_name) returns an image's bytes; an image that can not be read is left out
    rather than failing the whole submission"""
    document: dict = snapshot["document"]
    files: dict[str, str] = snapshot.get("files") or {}
    exhibits: list[dict] = []
    for ref in _exhibits(document):
        object_name: str | None = files.get(str(ref["file_id"]))
        if not object_name:
            continue
        try:
            src: str = prepare_image(fetch(object_name))
        except Exception:
            continue
        exhibits.append(
            {"src": src, "label": ref.get("caption") or ref.get("file_name") or "Photo"}
        )
    return _env.get_template("evidence.html").render(doc=document, documents=exhibits)


def acceptance_html(
    business_name: str,
    dispute_reference: str,
    transaction_reference: str,
    amount: int,
    currency: str,
    message: str,
    document_date: datetime,
) -> str:
    return _env.get_template("acceptance.html").render(
        business_name=business_name,
        dispute_reference=dispute_reference,
        transaction_reference=transaction_reference,
        amount=amount,
        currency=currency,
        message=message,
        document_date=document_date,
    )


def render_pdf(html: str) -> bytes:
    """Imported here: weasyprint needs pango (apt install libpango-1.0-0 libpangoft2-1.0-0
    on debian/ubuntu; the gtk runtime on windows)"""
    from weasyprint import HTML

    return HTML(string=html, base_url=str(_TEMPLATES)).write_pdf()
