import posixpath
import re
from collections.abc import Iterator
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from bs4 import BeautifulSoup
from defusedxml.ElementTree import fromstring
from docx import Document
from docx.table import Table
from markdownify import markdownify
from odf.odf2xhtml import ODF2XHTML
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from striprtf.striprtf import rtf_to_text

from .content import ParsedContent, ReadRequest, cell_text


def html_text(source: str | bytes) -> str:
    soup = BeautifulSoup(source, "html.parser")
    for node in soup.select(
        "script, style, template, noscript, input, textarea, select"
    ):
        node.decompose()
    return markdownify(str(soup), heading_style="ATX")


def read_html(path: Path) -> ParsedContent:
    return ParsedContent((html_text(path.read_bytes()),), "html")


def read_docx(path: Path) -> ParsedContent:
    document = Document(str(path))

    def blocks() -> Iterator[str]:
        for section in document.sections:
            for paragraph in section.header.paragraphs:
                if paragraph.text:
                    yield paragraph.text + "\n\n"
        yield from _docx_blocks(document)
        for section in document.sections:
            for paragraph in section.footer.paragraphs:
                if paragraph.text:
                    yield paragraph.text + "\n\n"

    return ParsedContent(
        blocks(),
        "docx",
        [
            "Images, drawings, revision history, footnotes and comments are not extracted"
        ],
    )


def read_pptx(path: Path, request: ReadRequest) -> ParsedContent:
    presentation = Presentation(str(path))
    count = len(presentation.slides)
    if request.page_number is not None and not 1 <= request.page_number <= count:
        raise ValueError(
            f"Presentation has {count} slides; choose an existing page_number"
        )

    def shapes_text(shapes) -> Iterator[str]:
        for shape in shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from shapes_text(shape.shapes)
            if shape.has_text_frame:
                yield shape.text + "\n\n"
            if shape.has_table:
                for index, row in enumerate(shape.table.rows, 1):
                    yield (
                        f"Row {index}: "
                        + " | ".join(cell_text(cell.text) for cell in row.cells)
                        + "\n\n"
                    )

    def blocks() -> Iterator[str]:
        for index, slide in enumerate(presentation.slides, 1):
            if request.page_number is not None and index != request.page_number:
                continue
            yield f"# Slide {index} of {count}\n\n"
            yield from shapes_text(slide.shapes)
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame
                if notes is not None and notes.text:
                    yield "## Speaker notes\n\n" + notes.text + "\n\n"

    return ParsedContent(
        blocks(),
        "pptx",
        ["Images, chart graphics, animations and embedded files are not extracted"],
        page_count=count,
        page_number=request.page_number,
    )


def read_odf(path: Path) -> ParsedContent:
    converter = ODF2XHTML()
    converter.load(str(path))
    with ZipFile(path) as archive:
        format_ = "odp" if archive.read("mimetype").endswith(b"presentation") else "odt"
    return ParsedContent(
        (html_text(converter.xhtml()),),
        format_,
        ["Embedded images and document-specific annotations are not extracted"],
    )


def read_rtf(path: Path) -> ParsedContent:
    data = path.read_bytes()
    match = re.search(rb"\\ansicpg(\d+)", data[:4096])
    encoding = "cp" + match[1].decode("ascii") if match else "cp1252"
    return ParsedContent(
        (rtf_to_text(data.decode(encoding)),),
        "rtf",
        ["RTF text only; images and layout are not extracted"],
    )


def read_epub(path: Path) -> ParsedContent:
    def blocks() -> Iterator[str]:
        with ZipFile(path) as archive:
            encrypted = set()
            if "META-INF/encryption.xml" in archive.namelist():
                encryption = fromstring(archive.read("META-INF/encryption.xml"))
                encrypted = {
                    posixpath.normpath(unquote(urlsplit(node.attrib["URI"]).path))
                    for node in encryption.iter()
                    if node.tag.rsplit("}", 1)[-1] == "CipherReference"
                    and "URI" in node.attrib
                }
            container = fromstring(archive.read("META-INF/container.xml"))
            rootfile = next(
                (
                    node
                    for node in container.iter()
                    if node.tag.rsplit("}", 1)[-1] == "rootfile"
                ),
                None,
            )
            if rootfile is None:
                raise ValueError("EPUB has no root document")
            package_path = rootfile.attrib["full-path"]
            package = fromstring(archive.read(package_path))
            manifest = {
                node.get("id"): node.get("href")
                for node in package.iter()
                if node.tag.rsplit("}", 1)[-1] == "item"
            }
            references = [
                node
                for node in package.iter()
                if node.tag.rsplit("}", 1)[-1] == "itemref"
            ]
            for index, reference in enumerate(references, 1):
                href = manifest.get(reference.get("idref"))
                if not href:
                    raise ValueError("EPUB chapter is missing from the manifest")
                chapter = posixpath.normpath(
                    posixpath.join(
                        posixpath.dirname(package_path),
                        unquote(urlsplit(str(href)).path),
                    )
                )
                if chapter in encrypted:
                    raise ValueError(
                        "EPUB chapter is encrypted; DRM-protected content is unavailable"
                    )
                yield (
                    f"# Chapter {index}\n\n" + html_text(archive.read(chapter)) + "\n\n"
                )

    return ParsedContent(blocks(), "epub", ["Embedded images are not extracted"])


def read_email(path: Path) -> ParsedContent:
    with path.open("rb") as stream:
        message = BytesParser(policy=policy.default).parse(stream)
    blocks = [
        f"{name}: {message[name]}\n"
        for name in ("Subject", "From", "To", "Date")
        if message[name]
    ]
    blocks.append("\n")
    attachments = []
    body = message.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        blocks.append(
            html_text(content)
            if body.get_content_type() == "text/html"
            else str(content)
        )
    for part in message.iter_attachments():
        attachments.append(part.get_filename() or f"attachment-{len(attachments) + 1}")
    if attachments:
        blocks.append(
            "\n\n## Attachments\n\n" + "\n".join(f"- {name}" for name in attachments)
        )
    limitations = (
        ["Attachments are listed separately; use member to read their contents"]
        if attachments
        else []
    )
    return ParsedContent(blocks, "eml", limitations, entry_count=len(attachments))


def read_mhtml(path: Path) -> ParsedContent:
    with path.open("rb") as stream:
        message = BytesParser(policy=policy.default).parse(stream)
    blocks = []
    for part in message.walk():
        if part.get_content_type() == "text/html":
            blocks.append(html_text(part.get_content()) + "\n\n")
    return ParsedContent(
        blocks, "mhtml", ["Non-HTML embedded resources are not extracted"]
    )


def _docx_table(table: Table) -> Iterator[str]:
    for index, row in enumerate(table.rows, 1):
        yield f"### Table row {index}\n\n"
        for column, cell in enumerate(row.cells, 1):
            yield f"Cell {index},{column}:\n\n"
            yield from _docx_blocks(cell)


def _docx_blocks(parent) -> Iterator[str]:
    for block in parent.iter_inner_content():
        if isinstance(block, Table):
            yield from _docx_table(block)
        else:
            style = block.style.name if block.style is not None else ""
            prefix = ""
            if style.startswith("Heading ") and style[-1:].isdigit():
                prefix = "#" * min(6, int(style[-1:])) + " "
            yield prefix + block.text + "\n\n"
