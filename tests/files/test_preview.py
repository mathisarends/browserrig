import base64
import sys
from io import BytesIO

import pytest
from openpyxl import Workbook
from PIL import Image

from browserrig import FileSystem, LocalWorkspace


async def test_visual_image_read_is_bounded_without_ocr_and_preserves_source(
    tmp_path, monkeypatch
):
    path = tmp_path / "large.png"
    Image.new("RGB", (3000, 1000), "red").save(path)
    original = path.read_bytes()
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        result = await files.read_file(path.name, view="auto")
        assert result.image is not None and "OCR was not run" in result.text
        with Image.open(
            BytesIO(base64.b64decode(result.image.split(",", 1)[1]))
        ) as delivered:
            assert delivered.size == (2048, 683)
        assert path.read_bytes() == original
        text = await files.read_file(path.name, view="text", ocr=False)
        assert text.image is None and text.status == "metadata_only"


async def test_pdf_visual_reads_select_pages_and_offer_continuation(
    tmp_path, pdf_document
):
    (tmp_path / "report.pdf").write_bytes(pdf_document)
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        first = await files.read_file("report.pdf", view="image")
        second = await files.read_file("report.pdf", page_number=2, view="image")
        assert first.page_count == 2 and first.next_page_number == 2
        assert second.page_number == 2 and second.next_page_number is None
        assert first.image != second.image and second.image is not None
        with pytest.raises(ValueError, match="2 pages"):
            await files.read_file("report.pdf", page_number=3, view="image")
        partial = await files.read_file("report.pdf", max_chars=4)
        assert partial.next_offset == 4 and partial.next_page_number is None
        rest = await files.read_file("report.pdf", offset=partial.next_offset)
        assert rest.next_page_number == 2


async def test_spreadsheet_continuation_waits_for_the_current_text_page(tmp_path):
    book = Workbook()
    book.active["A1"] = "First sheet"
    book.create_sheet("Second")["A1"] = "Other sheet"
    book.save(tmp_path / "book.xlsx")
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        first = await files.read_file("book.xlsx", max_chars=4)
        assert first.next_sheet is None and first.next_offset == 4
        rest = await files.read_file("book.xlsx", offset=first.next_offset)
        assert rest.next_sheet == "Second"
        last = await files.read_file("book.xlsx", sheet=rest.next_sheet)
        assert last.next_sheet is None and "Other sheet" in last.text


async def test_visual_reads_reject_text_files_and_text_offsets(tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    Image.new("RGB", (10, 10)).save(tmp_path / "image.png")
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        with pytest.raises(ValueError, match="Image views support"):
            await files.read_file("note.txt", view="image")
        with pytest.raises(ValueError, match="text offset"):
            await files.read_file("image.png", view="image", offset=1)
