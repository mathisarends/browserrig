import json
from pathlib import PurePosixPath

from openpyxl import Workbook
from PIL import Image
from pypdf import PdfWriter

from browserrig import FileOptions, FileSystem, LocalWorkspace
from browserrig.files import FileContent
from browserrig.files.indexing import Indexing


async def test_automatic_pdf_index_preserves_raw_file_and_indexes_all_native_pages(
    tmp_path, pdf_document
):
    path = tmp_path / "report.pdf"
    path.write_bytes(pdf_document)
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        await files.start_extraction(path.name, url="https://example.org/report")
        assert files.extraction(path.name).status == "processing"
    assert path.read_bytes() == pdf_document
    markdown = (tmp_path / "report.pdf.md").read_text(encoding="utf-8")
    assert "First page: Voyager 1" in markdown and "Second page: Voyager 2" in markdown
    metadata = json.loads((tmp_path / "report.pdf.extraction.json").read_text())
    assert metadata["status"] == "complete" and metadata["page_count"] == 2
    assert metadata["pending_ocr_pages"] == [] and metadata["url"].startswith(
        "https://"
    )
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        page = await files.read_file(path.name, page_number=2, max_chars=4)
        assert len(page.text) == 4 and page.document_path == "report.pdf.md"
    assert "Second page: Voyager 2" in (tmp_path / "report.pdf.md").read_text(
        encoding="utf-8"
    )


async def test_automatic_ocr_budget_leaves_other_pages_explicitly_pending(tmp_path):
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    for _ in range(12):
        writer.add_blank_page(width=100, height=100)
    writer.write(path)
    calls = []

    async def read(source, *, page_number=None, ocr=False):
        calls.append((page_number, ocr))
        return FileContent(
            path=source,
            media_type="application/pdf",
            format="pdf",
            page_count=12,
            page_number=page_number or 1,
            text=f"Recognized page {page_number}" if ocr else "",
            limitations=("Text was recognized with local OCR",) if ocr else (),
        )

    async def source(_path):
        return path

    workspace = LocalWorkspace(tmp_path)
    index = Indexing(workspace, FileOptions(auto_ocr_pages=2), read=read, source=source)
    await index.start(path.name, url="")
    await index.close()
    state = index.state(path.name)
    assert [page for page, ocr in calls if ocr] == [1, 2]
    assert state.status == "partial" and state.pending_ocr_pages == tuple(range(3, 13))
    content = await read(path.name, page_number=12, ocr=True)
    stat = await workspace.stat(PurePosixPath(path.name))
    await index.record(content, source=stat)
    assert index.state(path.name).pending_ocr_pages == tuple(range(3, 12))
    assert "Recognized page 12" in (tmp_path / "scan.pdf.md").read_text(
        encoding="utf-8"
    )


async def test_automatic_workbook_index_includes_every_sheet(tmp_path):
    book = Workbook()
    book.active["A1"] = "First sheet sentinel"
    book.create_sheet("Other")["B2"] = "Second sheet sentinel"
    book.save(tmp_path / "book.xlsx")
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        await files.start_extraction("book.xlsx")
    markdown = (tmp_path / "book.xlsx.md").read_text(encoding="utf-8")
    assert "First sheet sentinel" in markdown and "Second sheet sentinel" in markdown


async def test_indexing_failure_keeps_original_and_reports_failure_in_the_sidecar(
    tmp_path,
):
    original = b"%PDF-invalid document"
    (tmp_path / "broken.pdf").write_bytes(original)
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        await files.start_extraction("broken.pdf")
    assert (tmp_path / "broken.pdf").read_bytes() == original
    assert files.extraction("broken.pdf").status == "failed"
    assert "Extraction failed" in (tmp_path / "broken.pdf.md").read_text(
        encoding="utf-8"
    )


async def test_indexing_does_not_overwrite_unmanaged_markdown(tmp_path, pdf_document):
    (tmp_path / "report.pdf").write_bytes(pdf_document)
    (tmp_path / "report.pdf.md").write_text("User notes", encoding="utf-8")
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        await files.start_extraction("report.pdf")
    assert files.extraction("report.pdf").status == "failed"
    assert (tmp_path / "report.pdf.md").read_text() == "User notes"


async def test_image_metadata_does_not_claim_ocr_coverage(tmp_path):
    Image.new("RGB", (20, 10), "white").save(tmp_path / "image.png")
    async with FileSystem(
        LocalWorkspace(tmp_path), FileOptions(auto_ocr_pages=0)
    ) as files:
        await files.start_extraction("image.png")
    assert files.extraction("image.png").pending_ocr_pages == (1,)
    assert not files.extraction("image.png").indexed_pages
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        await files.read_file("image.png", ocr=False)
        assert files.extraction("image.png").pending_ocr_pages == (1,)
