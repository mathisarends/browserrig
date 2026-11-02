import pytest
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P

from browserrig import FileSystem, FileSystemOptions


async def test_ods_repetition_respects_output_budget_and_allows_a_small_selection(
    tmp_path,
):
    book = OpenDocumentSpreadsheet()
    table = Table(name="Data")
    row = TableRow(numberrowsrepeated=1048576)
    cell = TableCell(numbercolumnsrepeated=64, valuetype="string")
    cell.addElement(P(text="value"))
    row.addElement(cell)
    table.addElement(row)
    book.spreadsheet.addElement(table)
    path = tmp_path / "repeat.ods"
    book.save(str(path))
    source = path.read_bytes()
    files = FileSystem(FileSystemOptions(directory=tmp_path, max_expanded_bytes=8192))
    with pytest.raises(
        ValueError, match="Extracted content exceeds max_expanded_bytes"
    ):
        await files.read_file(path.name, max_chars=1)
    assert not list((tmp_path / ".content").iterdir())
    assert path.read_bytes() == source
    selected = await files.read_file(path.name, cell_range="A1:B2")
    assert "A1: value" in selected.text and "B2: value" in selected.text


@pytest.mark.parametrize(
    "name,source",
    [("unicode.html", "<p>" + "é" * 12 + "</p>"), ("notes.rtf", r"{\rtf1\ansi Hello}")],
)
async def test_extraction_budget_counts_utf8_bytes_and_limitations(
    tmp_path, name, source
):
    (tmp_path / name).write_text(source, encoding="utf-8")
    files = FileSystem(FileSystemOptions(directory=tmp_path, max_expanded_bytes=16))
    with pytest.raises(
        ValueError, match="Extracted content exceeds max_expanded_bytes"
    ):
        await files.read_file(name, max_chars=1)
    assert not list((tmp_path / ".content").iterdir())
