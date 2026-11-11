import base64
from importlib import import_module
from io import BytesIO
from pathlib import Path
from threading import Lock

from PIL import Image, ImageOps

from .content import ReadContext
from .models import FileContent

_PDF_LOCK = Lock()
_MAX_DIMENSION = 2048
_MAX_PIXELS = 40_000_000


def render_image(context: ReadContext) -> FileContent:
    """Render one bounded page/frame without running OCR or altering the source."""
    number = context.request.page_number or 1
    if context.format == "pdf":
        image, count = pdf_image(context.path, number)
    else:
        try:
            with Image.open(context.path) as source:
                count = getattr(source, "n_frames", 1)
                if not 1 <= number <= count:
                    raise ValueError(
                        f"Image has {count} frames; choose an existing page_number"
                    )
                source.seek(number - 1)
                if source.width * source.height > _MAX_PIXELS:
                    raise ValueError(
                        "Image exceeds the 40000000-pixel visual read limit"
                    )
                image = ImageOps.exif_transpose(source).copy()
        except Image.UnidentifiedImageError as error:
            raise ValueError(
                "Image views support PDF pages and supported image files"
            ) from error
    with image:
        original = image.size
        image.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))
        with BytesIO() as output:
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(
                output, format="PNG"
            )
            encoded = base64.b64encode(output.getvalue()).decode("ascii")
        text = (
            f"Visual read: {context.path.name}; page/frame {number} of {count}; "
            f"source {original[0]} × {original[1]}, delivered {image.width} × {image.height}. "
            "OCR was not run. Use view=text for text extraction."
        )
    return FileContent(
        path=str(context.path),
        media_type="application/pdf" if context.format == "pdf" else "image/png",
        text=text,
        format=context.format,
        page_number=number,
        page_count=count,
        size=context.path.stat().st_size,
        image=f"data:image/png;base64,{encoded}",
    )


def pdf_image(
    path: Path, number: int, *, max_dimension: int = _MAX_DIMENSION
) -> tuple[Image.Image, int]:
    """Serialize PDFium access, shared with the OCR reader."""
    try:
        pdfium = import_module("pypdfium2")
    except ModuleNotFoundError as error:
        raise ValueError(
            "PDF image views require pypdfium2; install browserrig[files]"
        ) from error
    with _PDF_LOCK, pdfium.PdfDocument(str(path)) as document:
        count = len(document)
        if not 1 <= number <= count:
            raise ValueError(f"PDF has {count} pages; choose an existing page_number")
        page = document[number - 1]
        try:
            scale = min(2, max_dimension / max(page.get_size()))
            bitmap = page.render(scale=scale)
            try:
                return bitmap.to_pil().copy(), count
            finally:
                bitmap.close()
        finally:
            page.close()
