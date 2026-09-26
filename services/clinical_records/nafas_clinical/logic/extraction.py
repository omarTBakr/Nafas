"""
What a document says: the text of a PDF, OCR for pages that are pictures,
OCR for images. Tesseract reads Arabic and English (`ara+eng`); a scanned
page is rendered at twice its size first, which OCR needs.
"""

import asyncio
import io
import shutil
import subprocess
from dataclasses import dataclass, field

# below this many characters a PDF page has no real text layer: it is a scan
SCANNED_BELOW_CHARS = 25
RENDER_SCALE = 2.0
OCR_LANGUAGES = "ara+eng"
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/tiff"}
PDF = "application/pdf"


class ExtractionError(ValueError):
    """The file could not be read as what it claims to be."""


@dataclass
class Extracted:
    text: str
    page_count: int | None = None
    # page numbers (1-based) whose text came from OCR, so an answer can say so
    ocr_pages: list[int] = field(default_factory=list)


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr(image_png: bytes) -> str:
    if not ocr_available():
        raise ExtractionError("tesseract is not installed; scanned pages and images cannot be read")
    process = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", OCR_LANGUAGES], input=image_png, capture_output=True, check=False
    )
    if process.returncode != 0:
        raise ExtractionError("OCR failed on a page")
    return process.stdout.decode("utf-8", errors="replace").strip()


def _pdf(data: bytes) -> Extracted:
    import pypdf
    import pypdfium2

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        texts = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise ExtractionError("not a readable PDF") from exc

    ocr_pages = [i for i, text in enumerate(texts) if len(text) < SCANNED_BELOW_CHARS]
    if ocr_pages:
        rendered = pypdfium2.PdfDocument(data)
        try:
            for i in ocr_pages:
                image = rendered[i].render(scale=RENDER_SCALE).to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                texts[i] = _ocr(buffer.getvalue())
        finally:
            rendered.close()

    pages = [f"[page {i + 1}]\n{text}" for i, text in enumerate(texts) if text]
    return Extracted("\n\n".join(pages), page_count=len(texts), ocr_pages=[i + 1 for i in ocr_pages])


def _image(data: bytes) -> Extracted:
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise ExtractionError("not a readable image") from exc
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return Extracted(_ocr(buffer.getvalue()), page_count=1, ocr_pages=[1])


def extract_sync(data: bytes, mime: str) -> Extracted:
    if mime == PDF:
        return _pdf(data)
    if mime in IMAGE_TYPES:
        return _image(data)
    if mime.startswith("text/"):
        return Extracted(data.decode("utf-8", errors="replace"))
    raise ExtractionError(f"{mime} cannot be read yet")


async def extract(data: bytes, mime: str) -> Extracted:
    """In a thread: PDF parsing, rendering and OCR all block."""
    return await asyncio.to_thread(extract_sync, data, mime)
