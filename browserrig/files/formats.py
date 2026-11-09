from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module

from .content import ParsedContent, ReadContext
from .kinds import FileExtension as Ext

type Reader = Callable[[ReadContext], ParsedContent]


@dataclass(frozen=True, slots=True)
class FileFormat:
    reader: str
    """`module.function` in this package, imported on first use so that formats
    from the optional `files` extra do not load their parsers at import time."""
    pages: bool = False
    sheets: bool = False
    cell_ranges: bool = False
    members: bool = False
    signatures: tuple[bytes, ...] = ()

    def load(self) -> Reader:
        module, _, name = self.reader.partition(".")
        return getattr(import_module(f"{__package__}.{module}"), name)


FORMATS = {
    (Ext.XLSX, Ext.XLSM, Ext.XLTX, Ext.XLTM): FileFormat(
        "spreadsheets.read_xlsx", sheets=True, cell_ranges=True
    ),
    (Ext.XLS,): FileFormat("spreadsheets.read_xls", sheets=True, cell_ranges=True),
    (Ext.ODS,): FileFormat("spreadsheets.read_ods", sheets=True, cell_ranges=True),
    (Ext.CSV, Ext.TSV): FileFormat(
        "spreadsheets.read_delimited", sheets=True, cell_ranges=True
    ),
    (Ext.SQLITE,): FileFormat(
        "data.read_sqlite", sheets=True, signatures=(b"SQLite format 3\0",)
    ),
    (Ext.PDF,): FileFormat("imaging.read_pdf", pages=True, signatures=(b"%PDF-",)),
    (Ext.PNG,): FileFormat(
        "imaging.read_image", pages=True, signatures=(b"\x89PNG\r\n\x1a\n",)
    ),
    (Ext.JPEG, Ext.JPG): FileFormat(
        "imaging.read_image", pages=True, signatures=(b"\xff\xd8\xff",)
    ),
    (Ext.TIFF, Ext.TIF): FileFormat(
        "imaging.read_image", pages=True, signatures=(b"II*\0", b"MM\0*")
    ),
    (Ext.GIF,): FileFormat(
        "imaging.read_image", pages=True, signatures=(b"GIF87a", b"GIF89a")
    ),
    (Ext.BMP,): FileFormat("imaging.read_image", pages=True),
    (Ext.WEBP, Ext.ICO): FileFormat("imaging.read_image", pages=True),
    (Ext.PPTX,): FileFormat("documents.read_pptx", pages=True),
    (Ext.DOCX,): FileFormat("documents.read_docx"),
    (Ext.ODT, Ext.ODP): FileFormat("documents.read_odf"),
    (Ext.HTML,): FileFormat("documents.read_html"),
    (Ext.RTF,): FileFormat("documents.read_rtf"),
    (Ext.EPUB,): FileFormat("documents.read_epub"),
    (Ext.EML,): FileFormat("documents.read_email", members=True),
    (Ext.MHTML,): FileFormat("documents.read_mhtml"),
    (Ext.ZIP, Ext.TAR, Ext.GZ, Ext.BZ2, Ext.XZ, Ext.MBOX): FileFormat(
        "containers.read_container", members=True
    ),
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
    ): FileFormat("media.read_media"),
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
