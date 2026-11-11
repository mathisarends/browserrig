import json
import re

import pytest

from browserrig import FileOptions, FileSystem, LocalWorkspace


async def test_search_finds_text_beyond_preview_limits_even_on_a_long_line(tmp_path):
    (tmp_path / "report.md").write_text(
        "x" * 300000 + "TAIL_SENTINEL\n", encoding="utf-8"
    )
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        result = await files.grep("tail_sentinel")
    assert result.scanned_files == 1 and len(result.matches) == 1
    assert (
        result.matches[0].startswith("report.md:1:")
        and "TAIL_SENTINEL" in result.matches[0]
    )
    assert len(result.matches[0]) < 1500


async def test_glob_and_search_exclude_internal_caches_by_default(tmp_path):
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        await files.write_file("report.md", "Visible sentinel")
        await files.write_file("pages/one/content.md", "Page sentinel")
        await files.write_file(".content/cache.md", "Hidden sentinel")
        paths = await files.glob("**/*.md")
        assert set(paths.paths) == {"report.md", "pages/one/content.md"}
        assert not paths.truncated
        visible = await files.grep("sentinel")
        hidden = await files.grep("Hidden", include_hidden=True)
        assert len(visible.matches) == 2 and len(hidden.matches) == 1
        assert hidden.matches[0].startswith(".content/cache.md:")


async def test_partial_extraction_is_reported_even_when_the_query_has_no_hits(tmp_path):
    (tmp_path / "scan.pdf.md").write_text("First page only", encoding="utf-8")
    (tmp_path / "scan.pdf.extraction.json").write_text(
        json.dumps(
            {
                "status": "partial",
                "pending_ocr_pages": [2, 3],
            }
        ),
        encoding="utf-8",
    )
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        result = await files.grep("not present")
    assert not result.matches and result.scanned_files == 1
    assert any(
        "2 page(s)" in note and "saved text only" in note for note in result.notes
    )


async def test_search_reports_match_and_byte_budgets(tmp_path):
    (tmp_path / "many.md").write_text("needle\n" * 4, encoding="utf-8")
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        result = await files.grep("needle", limit=2)
        assert len(result.matches) == 2 and any(
            "Match limit" in note for note in result.notes
        )
    async with FileSystem(
        LocalWorkspace(tmp_path), FileOptions(max_expanded_bytes=2)
    ) as files:
        result = await files.grep("needle")
        assert not result.matches and any(
            "byte budget" in note for note in result.notes
        )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
async def test_search_offsets_read_the_same_unicode_and_crlf_excerpt(
    tmp_path, encoding
):
    (tmp_path / "report.md").write_bytes(
        ("Überblick\r\n" + "🙂" * 400 + "needle\r\n").encode(encoding)
    )
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        result = await files.grep("needle")
        match = re.search(r"offset=(\d+)", result.matches[0])
        assert match is not None
        excerpt = await files.read_file(
            "report.md", offset=int(match[1]), max_chars=206
        )
    assert excerpt.text == "🙂" * 200 + "needle"


async def test_search_bounds_notes_when_many_files_cannot_be_searched(tmp_path):
    for index in range(30):
        (tmp_path / f"report{index}.md").write_text("too large", encoding="utf-8")
    async with FileSystem(
        LocalWorkspace(tmp_path), FileOptions(max_expanded_bytes=2)
    ) as files:
        result = await files.grep("needle")
    assert not result.matches and len(result.notes) == 21
    assert "10 additional search notes omitted" in result.notes[-1]


async def test_search_rejects_escaping_patterns_without_reading_outside(tmp_path):
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        with pytest.raises(ValueError, match="outside"):
            await files.glob("../**/*.md")
        with pytest.raises(ValueError, match="non-empty"):
            await files.grep("")


async def test_search_reports_when_the_original_changed_since_extraction(tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"old source")
    captured = source.stat()
    (tmp_path / "report.pdf.md").write_text("Old needle", encoding="utf-8")
    (tmp_path / "report.pdf.extraction.json").write_text(
        json.dumps(
            {
                "source": "report.pdf",
                "size": captured.st_size,
                "modified": captured.st_mtime,
                "status": "complete",
                "pending_ocr_pages": [],
            }
        ),
        encoding="utf-8",
    )
    source.write_bytes(b"new and longer source")
    async with FileSystem(LocalWorkspace(tmp_path)) as files:
        result = await files.grep("needle")
    assert len(result.matches) == 1 and any(
        "source changed" in note for note in result.notes
    )
