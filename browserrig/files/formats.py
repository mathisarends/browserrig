from dataclasses import dataclass

from . import data, documents, imaging, spreadsheets
from ._adapters import Reader
from ._adapters import container as _container
from ._adapters import document as _document
from ._adapters import ocr as _ocr
from ._adapters import selected as _selected
from .kinds import FileExtension as Ext


@dataclass(frozen=True, slots=True)
class FileFormat:
    read: Reader
    pages: bool = False
    sheets: bool = False
    cell_ranges: bool = False
    members: bool = False
    signatures: tuple[bytes, ...] = ()


FORMATS = {
    (Ext.XLSX, Ext.XLSM, Ext.XLTX, Ext.XLTM): FileFormat(
        _selected(spreadsheets.read_xlsx), sheets=True, cell_ranges=True
    ),
    (Ext.XLS,): FileFormat(
        _selected(spreadsheets.read_xls), sheets=True, cell_ranges=True
    ),
    (Ext.ODS,): FileFormat(
        _selected(spreadsheets.read_ods), sheets=True, cell_ranges=True
    ),
    (Ext.CSV, Ext.TSV): FileFormat(
        _selected(spreadsheets.read_delimited), sheets=True, cell_ranges=True
    ),
    (Ext.SQLITE,): FileFormat(
        _selected(data.read_sqlite), sheets=True, signatures=(b"SQLite format 3\0",)
    ),
    (Ext.PDF,): FileFormat(_ocr(imaging.read_pdf), pages=True, signatures=(b"%PDF-",)),
    (Ext.PNG,): FileFormat(
        _ocr(imaging.read_image), pages=True, signatures=(b"\x89PNG\r\n\x1a\n",)
    ),
    (Ext.JPEG, Ext.JPG): FileFormat(
        _ocr(imaging.read_image), pages=True, signatures=(b"\xff\xd8\xff",)
    ),
    (Ext.TIFF, Ext.TIF): FileFormat(
        _ocr(imaging.read_image), pages=True, signatures=(b"II*\0", b"MM\0*")
    ),
    (Ext.GIF,): FileFormat(
        _ocr(imaging.read_image), pages=True, signatures=(b"GIF87a", b"GIF89a")
    ),
    (Ext.BMP,): FileFormat(_ocr(imaging.read_image), pages=True),
    (Ext.WEBP, Ext.ICO): FileFormat(_ocr(imaging.read_image), pages=True),
    (Ext.PPTX,): FileFormat(_selected(documents.read_pptx), pages=True),
    (Ext.DOCX,): FileFormat(_document(documents.read_docx)),
    (Ext.ODT, Ext.ODP): FileFormat(_document(documents.read_odf)),
    (Ext.HTML,): FileFormat(_document(documents.read_html)),
    (Ext.RTF,): FileFormat(_document(documents.read_rtf)),
    (Ext.EPUB,): FileFormat(_document(documents.read_epub)),
    (Ext.EML,): FileFormat(_document(documents.read_email), members=True),
    (Ext.MHTML,): FileFormat(_document(documents.read_mhtml)),
    (Ext.ZIP,): FileFormat(_container(Ext.ZIP), members=True),
    (Ext.TAR,): FileFormat(_container(Ext.TAR), members=True),
    (Ext.GZ,): FileFormat(_container(Ext.GZ), members=True),
    (Ext.BZ2,): FileFormat(_container(Ext.BZ2), members=True),
    (Ext.XZ,): FileFormat(_container(Ext.XZ), members=True),
    (Ext.MBOX,): FileFormat(_container(Ext.MBOX), members=True),
    (
        Ext.MP3,
        Ext.WAV,
        Ext.M4A,
        Ext.AAC,
        Ext.FLAC,
        Ext.OGG,
        Ext.MP4,
        Ext.WEBM,
        Ext.MOV,
        Ext.AVI,
    ): FileFormat(_document(data.read_media)),
}

READERS = {str(name): format_ for names, format_ in FORMATS.items() for name in names}


def signature_format(sample: bytes) -> str | None:
    return next(
        (
            names[0]
            for names, format_ in FORMATS.items()
            if format_.signatures and sample.startswith(format_.signatures)
        ),
        None,
    )
