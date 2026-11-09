import gzip
import json
import sqlite3
import struct
import sys
import tarfile
from email.message import EmailMessage
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from docx import Document
from odf.opendocument import OpenDocumentSpreadsheet, OpenDocumentText
from odf.table import Table, TableCell, TableRow
from odf.text import P
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation

from browserrig import FileOptions, FileSystem, LocalWorkspace


async def test_xlsx_preserves_coordinates_formulas_formats_and_hidden_content(files):
    path = files.workspace.directory / "report.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "Revenue"
    sheet.append(["Name", "Amount"])
    sheet.append(["Voyager", 0.125])
    sheet["B2"].number_format = "0.0%"
    sheet["C2"] = "=B2*2"
    sheet["A4"] = "Merged label"
    sheet.merge_cells("A4:B4")
    sheet.row_dimensions[2].hidden = True
    book.create_sheet("Internal").sheet_state = "hidden"
    book.save(path)
    before = path.read_bytes()
    result = await files.read_file(path.name, cell_range="A1:C4")
    assert result.sheets == ("Revenue", "Internal")
    assert result.sheet == "Revenue" and result.cell_range == "A1:C4"
    assert "Voyager" in result.text and "0.125 [format: 0.0%]" in result.text
    assert "=B2*2 [stored result: unavailable]" in result.text
    assert "Merged cells: A4:B4" in result.text
    assert "Hidden row: 2" in result.text and "Internal: hidden" in result.text
    assert path.read_bytes() == before
    assert result.status == "partial" and any(
        "recalculated" in item for item in result.limitations
    )
    with pytest.raises(ValueError, match="Unknown sheet"):
        await files.read_file(path.name, sheet="Missing")
    with pytest.raises(ValueError, match="A1 range"):
        await files.read_file(path.name, cell_range="A:Z")


async def test_format_detection_does_not_depend_on_download_extension(
    files, pdf_document
):
    pdf = files.workspace.directory / "download.bin"
    pdf.write_bytes(pdf_document)
    assert "Second page" in (await files.read_file(pdf.name, page_number=2)).text
    book = Workbook()
    book.active["B3"] = "Correct cell"
    buffer = BytesIO()
    book.save(buffer)
    path = files.workspace.directory / "workbook.bin"
    path.write_bytes(buffer.getvalue())
    result = await files.read_file(path.name, cell_range="B3:B3")
    assert result.format == "xlsx" and "Correct cell" in result.text


@pytest.mark.parametrize("dimension", [None, "A1:A1"])
async def test_xlsx_tolerates_bad_dimensions_and_irrelevant_invalid_formatting(
    files, dimension
):
    source = BytesIO()
    book = Workbook()
    book.active["B3"] = "Actual data"
    book.save(source)
    source.seek(0)
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    path = files.workspace.directory / "producer-edge.xlsx"
    with ZipFile(source) as original, ZipFile(path, "w") as output:
        for entry in original.infolist():
            value = original.read(entry)
            if entry.filename == "xl/worksheets/sheet1.xml":
                root = ElementTree.fromstring(value)
                node = root.find(namespace + "dimension")
                if dimension is None:
                    root.remove(node)
                else:
                    node.set("ref", dimension)
                formatting = ElementTree.SubElement(
                    root, namespace + "conditionalFormatting", sqref="B3"
                )
                ElementTree.SubElement(
                    formatting,
                    namespace + "cfRule",
                    type="cellIs",
                    operator="invalid",
                    priority="1",
                )
                value = ElementTree.tostring(root, encoding="utf-8")
            output.writestr(entry, value)
    before = path.read_bytes()
    result = await files.read_file(path.name)
    assert result.cell_range == "A1:B3" and "Actual data" in result.text
    assert path.read_bytes() == before


async def test_xlsx_infers_omitted_row_and_cell_references(files):
    source = BytesIO()
    book = Workbook()
    book.active.append(["First row", 42])
    book.active.append(["Second row"])
    book.save(source)
    source.seek(0)
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    path = files.workspace.directory / "implicit-coordinates.xlsx"
    with ZipFile(source) as original, ZipFile(path, "w") as output:
        for entry in original.infolist():
            value = original.read(entry)
            if entry.filename == "xl/worksheets/sheet1.xml":
                root = ElementTree.fromstring(value)
                root.remove(root.find(namespace + "dimension"))
                for node in root.iter():
                    node.attrib.pop("r", None)
                value = ElementTree.tostring(root, encoding="utf-8")
            output.writestr(entry, value)
    result = await files.read_file(path.name)
    assert result.cell_range == "A1:B2"
    assert "| 1 | First row | 42 |" in result.text
    assert "| 2 | Second row |  |" in result.text


async def test_legacy_biff_xls_values_are_read_without_a_conversion_backend(files):
    def record(code, payload):
        return struct.pack("<HH", code, len(payload)) + payload

    content = (
        record(9, struct.pack("<HH", 2, 16))
        + record(3, struct.pack("<HH3sd", 0, 0, bytes(3), 42.0))
        + record(4, struct.pack("<HH3sB", 1, 0, bytes(3), 7) + b"Voyager")
        + record(10, b"")
    )
    (files.workspace.directory / "legacy.xls").write_bytes(content)
    result = await files.read_file("legacy.xls")
    assert (
        "42.0" in result.text and "Voyager" in result.text and result.sheet == "Sheet 1"
    )


async def test_nested_word_tables_are_not_silently_omitted(files):
    document = Document()
    outer = document.add_table(rows=1, cols=1)
    outer.cell(0, 0).text = "Outer cell"
    inner = outer.cell(0, 0).add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "Nested sentinel"
    document.save(files.workspace.directory / "nested.docx")
    result = await files.read_file("nested.docx")
    assert "Outer cell" in result.text and "Nested sentinel" in result.text


async def test_sparse_sheet_reports_view_and_allows_targeted_read(files):
    book = Workbook()
    book.active["A1"] = "Start"
    book.active["ZZ10000"] = "Far away"
    book.save(files.workspace.directory / "sparse.xlsx")
    preview = await files.read_file("sparse.xlsx")
    assert preview.status == "partial" and any(
        "ZZ10000" in item for item in preview.limitations
    )
    selected = await files.read_file("sparse.xlsx", cell_range="ZZ10000:ZZ10000")
    assert "Far away" in selected.text


async def test_derived_text_is_complete_cached_and_invalidated_after_source_changes(
    files,
):
    path = files.workspace.directory / "large.docx"
    document = Document()
    document.add_heading("Research", 1)
    document.add_paragraph("Grüße 🌍 " * 12000)
    document.add_paragraph("FINAL_SENTINEL")
    document.save(path)
    first = await files.read_file(path.name, max_chars=51)
    assert len(first.text) == 51 and first.next_offset == 51
    artifact = files.workspace.directory / first.extracted_path
    assert "FINAL_SENTINEL" in artifact.read_text(encoding="utf-8")
    stamp = artifact.stat().st_mtime_ns
    rest = await files.read_file(path.name, offset=first.next_offset, max_chars=200000)
    assert first.text + rest.text == artifact.read_text(encoding="utf-8")
    assert (
        rest.extracted_path == first.extracted_path
        and artifact.stat().st_mtime_ns == stamp
    )
    assert (await files.read_file(first.extracted_path)).text == artifact.read_text(
        encoding="utf-8"
    )[:20000]
    document.add_paragraph("ADDED_LATER")
    document.save(path)
    changed = await files.read_file(path.name, max_chars=200000)
    assert (
        "ADDED_LATER" in changed.text and changed.extracted_path != first.extracted_path
    )


async def test_presentation_reads_tables_notes_and_selected_slide(files):
    path = files.workspace.directory / "slides.pptx"
    deck = Presentation()
    first = deck.slides.add_slide(deck.slide_layouts[1])
    first.shapes.title.text = "First slide"
    first.notes_slide.notes_text_frame.text = "Speaker context"
    second = deck.slides.add_slide(deck.slide_layouts[1])
    second.shapes.title.text = "Second slide"
    deck.save(path)
    result = await files.read_file(path.name)
    assert result.page_count == 2 and "Speaker context" in result.text
    selected = await files.read_file(path.name, page_number=2)
    assert "Second slide" in selected.text and "First slide" not in selected.text


async def test_open_document_text_and_spreadsheet(files):
    document = OpenDocumentText()
    document.text.addElement(P(text="OpenDocument research"))
    document.save(str(files.workspace.directory / "notes.odt"))
    assert "OpenDocument research" in (await files.read_file("notes.odt")).text
    (files.workspace.directory / "renamed.bin").write_bytes(
        (files.workspace.directory / "notes.odt").read_bytes()
    )
    assert (await files.read_file("renamed.bin")).format == "odt"
    workbook = OpenDocumentSpreadsheet()
    table = Table(name="Data")
    row = TableRow()
    cell = TableCell(valuetype="string")
    cell.addElement(P(text="ODS sentinel"))
    row.addElement(cell)
    table.addElement(row)
    workbook.spreadsheet.addElement(table)
    workbook.save(str(files.workspace.directory / "table.ods"))
    result = await files.read_file("table.ods")
    assert result.sheets == ("Data",) and "A1: ODS sentinel" in result.text


async def test_csv_handles_quoted_delimiters_newlines_and_ranges(files):
    path = files.workspace.directory / "data.csv"
    path.write_text('Name;Value\n"A;B";"first\nsecond"\nTail;42\n', encoding="utf-8")
    result = await files.read_file("data.csv", cell_range="A2:B2")
    assert (
        "A;B" in result.text
        and "first<br>second" in result.text
        and "Tail" not in result.text
    )


async def test_utf16_text_pagination_is_character_based_and_large_text_is_streamed(
    files,
):
    path = files.workspace.directory / "notes.txt"
    text = "Grüße aus dem Weltall 🌍\r\n" * 20
    path.write_bytes(text.encode("utf-16"))
    first = await files.read_file("notes.txt", max_chars=19)
    rest = await files.read_file("notes.txt", offset=first.next_offset)
    assert first.text + rest.text == text and first.encoding == "utf-16"
    tiny = FileSystem(
        LocalWorkspace(files.workspace.directory), options=FileOptions(max_file_bytes=2)
    )
    assert (await tiny.read_file("notes.txt", max_chars=19)).text == text[:19]
    await files.write_file("manufacturer.txt", "BMW research notes")
    assert (await files.read_file("manufacturer.txt")).text == "BMW research notes"


async def test_html_and_rtf_are_read_without_running_scripts(files):
    await files.write_file(
        "page.html", "<h1>Title</h1><p>Visible</p><script>secret()</script>"
    )
    html = await files.read_file("page.html")
    assert "# Title" in html.text and "secret" not in html.text
    await files.write_file("notes.rtf", r"{\rtf1\ansi Hello \b world\b0\par Next line}")
    assert "Hello world" in (await files.read_file("notes.rtf")).text


@pytest.mark.parametrize("encrypted", [None, "OPS/font.ttf", "OPS/two.xhtml"])
async def test_epub_preserves_spine_order_and_rejects_encrypted_chapters(
    files, encrypted
):
    path = files.workspace.directory / "book.epub"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/book.opf",
            '<package><manifest><item id="one" href="one.xhtml"/>'
            '<item id="two" href="two.xhtml"/></manifest><spine>'
            '<itemref idref="two"/><itemref idref="one"/></spine></package>',
        )
        archive.writestr("OPS/one.xhtml", "<h1>Chapter one</h1>")
        archive.writestr("OPS/two.xhtml", "<h1>Chapter two</h1>")
        if encrypted:
            archive.writestr(
                "META-INF/encryption.xml",
                f'<encryption><EncryptedData><CipherData><CipherReference URI="{encrypted}"/>'
                "</CipherData></EncryptedData></encryption>",
            )
    if encrypted == "OPS/two.xhtml":
        with pytest.raises(ValueError, match="EPUB chapter is encrypted"):
            await files.read_file("book.epub")
        return
    result = await files.read_file("book.epub")
    assert result.text.index("Chapter two") < result.text.index("Chapter one")


async def test_email_body_and_attachment_use_the_same_read_path(files):
    message = EmailMessage()
    message["Subject"] = "Research"
    message["From"] = "source@example.test"
    message.set_content("Message body")
    message.add_attachment(
        b"# Attached research\nPayload",
        maintype="text",
        subtype="markdown",
        filename="notes.md",
    )
    (files.workspace.directory / "mail.eml").write_bytes(message.as_bytes())
    result = await files.read_file("mail.eml")
    assert (
        "Message body" in result.text
        and "notes.md" in result.text
        and result.entry_count == 1
    )
    attachment = await files.read_file("mail.eml", member="#1")
    assert attachment.text == "# Attached research\nPayload"
    assert attachment.path.endswith("mail.eml") and attachment.member == "#1"


async def test_nested_archives_and_compressed_text_are_accessible(files):
    inner = BytesIO()
    with ZipFile(inner, "w") as archive:
        archive.writestr("notes.md", "# Nested payload")
    with ZipFile(files.workspace.directory / "outer.zip", "w") as archive:
        archive.writestr("folder/inner.zip", inner.getvalue())
    listing = await files.read_file("outer.zip")
    assert "folder/inner.zip" in listing.text and listing.entry_count == 1
    nested = await files.read_file("outer.zip", member="folder/inner.zip!/notes.md")
    assert nested.text == "# Nested payload"
    limited = FileSystem(
        LocalWorkspace(files.workspace.directory),
        options=FileOptions(max_archive_depth=1),
    )
    with pytest.raises(ValueError, match="max_archive_depth"):
        await limited.read_file("outer.zip", member="folder/inner.zip!/notes.md")
    with gzip.open(files.workspace.directory / "note.txt.gz", "wb") as stream:
        stream.write(b"Compressed payload")
    assert (
        await files.read_file("note.txt.gz", member="note.txt")
    ).text == "Compressed payload"


async def test_archive_members_cannot_escape_follow_links_or_expand_without_bound(
    files,
):
    path = files.workspace.directory / "unsafe.zip"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../escape.md", "outside")
        archive.writestr("large.txt", "x" * 10000)
        link = ZipInfo("link.md")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "../outside")
    with pytest.raises(ValueError, match="traversal"):
        await files.read_file("unsafe.zip", member="../escape.md")
    with pytest.raises(ValueError, match="regular"):
        await files.read_file("unsafe.zip", member="link.md")
    bounded = FileSystem(
        LocalWorkspace(files.workspace.directory),
        options=FileOptions(max_expanded_bytes=100),
    )
    with pytest.raises(ValueError, match="max_expanded_bytes"):
        await bounded.read_file("unsafe.zip", member="large.txt")
    assert not (files.workspace.directory.parent / "escape.md").exists()


async def test_sqlite_is_read_only_and_retains_null_and_binary_values(files):
    path = files.workspace.directory / "data.sqlite"
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE "odd table" (name TEXT, value BLOB)')
    connection.execute('INSERT INTO "odd table" VALUES (?, ?)', (None, b"abc"))
    connection.commit()
    connection.close()
    before = path.read_bytes()
    result = await files.read_file("data.sqlite", sheet="odd table")
    assert (
        result.sheets == ("odd table",)
        and "NULL" in result.text
        and "binary: 3 bytes" in result.text
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("suffix", ["png", "pdf"])
async def test_local_ocr_reads_real_image_and_scanned_pdf(files, suffix):
    image = Image.new("RGB", (900, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (30, 45),
        "MISSION REPORT 2026",
        fill="black",
        font=ImageFont.load_default(size=52),
    )
    path = files.workspace.directory / f"scan.{suffix}"
    image.save(path)
    result = await files.read_file(path.name)
    assert "MISSION" in result.text.upper() and "2026" in result.text
    assert any("OCR" in item for item in result.limitations)
    assert result.extracted_path is not None


async def test_image_without_ocr_extra_returns_metadata_and_install_hint(
    files, monkeypatch
):
    # A None entry makes the package unimportable, as if it were not installed.
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    Image.new("RGB", (20, 10), "white").save(files.workspace.directory / "scan.png")
    result = await files.read_file("scan.png")
    assert result.status == "metadata_only" and "20 × 10" in result.text
    assert any("browserrig[ocr]" in item for item in result.limitations)


async def test_missing_file_extra_falls_back_to_raw_text_or_install_hint(
    files, monkeypatch
):
    monkeypatch.delitem(sys.modules, "browserrig.files.spreadsheets")
    monkeypatch.setitem(sys.modules, "xlrd", None)
    (files.workspace.directory / "table.csv").write_bytes(b"a,b\n1,2\n")
    table = await files.read_file("table.csv")
    assert table.status == "partial" and table.text == "a,b\n1,2\n"
    assert "browserrig[files]" in table.limitations[0]
    assert "xlrd" in table.limitations[0]
    Workbook().save(files.workspace.directory / "report.xlsx")
    book = await files.read_file("report.xlsx")
    assert book.status == "unsupported" and "browserrig[files]" in book.limitations[0]


async def test_unsupported_binary_has_explicit_status_and_no_screenshot_instruction(
    files,
):
    (files.workspace.directory / "unknown.bin").write_bytes(b"\0\xff\x01binary")
    result = await files.read_file("unknown.bin")
    assert result.status == "unsupported" and result.size == 9
    assert (
        result.limitations
        and "screenshot" not in json.dumps(result.model_dump()).lower()
    )
    preview = await files.read_file("unknown.bin", max_chars=4)
    assert len(preview.text) == 4 and preview.next_offset == 4


async def test_tar_index_and_selected_entry_enforce_expansion_budget(files):
    path = files.workspace.directory / "large.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        entry = tarfile.TarInfo("large.txt")
        entry.size = 10000
        archive.addfile(entry, BytesIO(b"x" * entry.size))
    bounded = FileSystem(
        LocalWorkspace(files.workspace.directory),
        options=FileOptions(max_expanded_bytes=100),
    )
    with pytest.raises(ValueError, match="max_expanded_bytes"):
        await bounded.read_file("large.tar.gz")
    with pytest.raises(ValueError, match="max_expanded_bytes"):
        await bounded.read_file("large.tar.gz", member="large.txt")


async def test_archive_pagination_reuses_entry_and_rejects_bad_crc(files):
    path = files.workspace.directory / "archive.zip"
    content = b"CONTAINER_PAYLOAD_0123456789"
    with ZipFile(path, "w") as archive:
        archive.writestr("notes.txt", content)
    first = await files.read_file("archive.zip", member="notes.txt", max_chars=7)
    sources = list((files.workspace.directory / ".content").glob("*.source.txt"))
    assert len(sources) == 1
    stamp = sources[0].stat().st_mtime_ns
    rest = await files.read_file(
        "archive.zip", member="notes.txt", offset=first.next_offset
    )
    assert first.text + rest.text == content.decode()
    assert sources[0].stat().st_mtime_ns == stamp
    corrupted = path.read_bytes().replace(b"CONTAINER_PAYLOAD", b"CORRUPTED_PAYLOAD", 1)
    (files.workspace.directory / "broken.zip").write_bytes(corrupted)
    with pytest.raises(ValueError, match="CRC"):
        await files.read_file("broken.zip", member="notes.txt")


async def test_derived_cache_cannot_follow_a_directory_symlink_outside_workspace(
    files, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (files.workspace.directory / ".content").symlink_to(
            outside, target_is_directory=True
        )
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    await files.write_file("page.html", "<p>Cached text</p>")
    with pytest.raises(ValueError, match="outside the workspace"):
        await files.read_file("page.html")
    assert not list(outside.iterdir())


@pytest.fixture(name="files")
async def _files(tmp_path):
    (tmp_path / "workspace").mkdir()
    return FileSystem(LocalWorkspace(tmp_path / "workspace"))
