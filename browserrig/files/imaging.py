from __future__ import annotations

from functools import cache
from importlib import import_module
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

import pypdfium2
from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import DictionaryObject

if TYPE_CHECKING:
    from rapidocr import RapidOCR

from .content import ParsedContent, ReadRequest

_OCR_LOCK = Lock()
_PDF_LOCK = Lock()


def read_pdf(path: Path, request: ReadRequest, enable_ocr: bool) -> ParsedContent:
    number = 1 if request.page_number is None else request.page_number
    try:
        with path.open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted:
                raise ValueError(
                    "PDF is encrypted; a password is required to extract its contents"
                )
            count = len(reader.pages)
            if not 1 <= number <= count:
                raise ValueError(
                    f"PDF has {count} pages; choose an existing page_number"
                )
            page = reader.pages[number - 1]
            text = page.extract_text() or ""
            resources = page.get("/Resources", DictionaryObject()).get_object()
            graphics = bool(resources.get("/XObject"))
    except PyPdfError as error:
        raise ValueError("Could not read PDF: invalid or damaged document") from error
    details = ParsedContent((), "pdf", page_number=number, page_count=count)
    if request.ocr is True or (
        not text.strip() and enable_ocr and request.ocr is not False
    ):
        with _pdf_image(path, number) as image:
            text = _image_text(image)
        details.limitations.append(
            "Text was recognized with local OCR and may contain recognition errors"
        )
    elif graphics:
        details.limitations.append(
            "Embedded graphics are not interpreted; use ocr=true to recognize text in the full page"
        )
    if not text.strip():
        details.limitations.append("No extractable text on this page")
    details.blocks = (text,)
    return details


def read_image(path: Path, request: ReadRequest, enable_ocr: bool) -> ParsedContent:
    number = 1 if request.page_number is None else request.page_number
    with Image.open(path) as image:
        format_ = (image.format or path.suffix.lstrip(".")).lower()
        count = getattr(image, "n_frames", 1)
        if not 1 <= number <= count:
            raise ValueError(
                f"Image has {count} frames; choose an existing page_number"
            )
        image.seek(number - 1)
        metadata = (
            f"# Image\n\nFormat: {image.format}\n"
            f"Dimensions: {image.width} × {image.height}\n\n"
        )
        if request.ocr is False or (request.ocr is None and not enable_ocr):
            return ParsedContent(
                (metadata,),
                format_,
                ["OCR is disabled; only image metadata is available"],
                status="metadata_only",
                page_number=number,
                page_count=count,
            )
        text = _image_text(image)
    details = ParsedContent(
        (metadata, "## Recognized text\n\n", text),
        format_,
        [
            "Local OCR extracts text, not a complete interpretation of pictures or diagrams"
        ],
        page_number=number,
        page_count=count,
    )
    if not text.strip():
        details.status = "metadata_only"
        details.limitations.append("No readable text was recognized in this image")
    return details


def _image_text(image: Image.Image) -> str:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((4000, 4000))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    with _OCR_LOCK:
        result = _engine()(buffer.getvalue())
    return "\n".join(getattr(result, "txts", None) or ())


@cache
def _engine() -> RapidOCR:
    return import_module("rapidocr").RapidOCR(
        params={
            "Global.log_level": "error",
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        }
    )


def _pdf_image(path: Path, number: int) -> Image.Image:
    # PDFium is not thread-safe even for different documents.
    with _PDF_LOCK, pypdfium2.PdfDocument(str(path)) as document:
        page = document[number - 1]
        try:
            scale = min(2, 4000 / max(page.get_size()))
            bitmap = page.render(scale=scale)
            try:
                return bitmap.to_pil().copy()
            finally:
                bitmap.close()
        finally:
            page.close()
