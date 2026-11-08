import gzip
import tarfile
from email.message import EmailMessage
from io import BytesIO
from zipfile import ZipFile

import pytest

from browserrig import FileOptions, FileSystem, LocalWorkspace


@pytest.mark.parametrize("extension", ["zip", "tar", "gz", "eml"])
async def test_member_selection_checks_outer_input_size_before_extraction(
    tmp_path, extension
):
    payload = b"Readable content"
    path = tmp_path / f"notes.{extension}"
    member = "notes.txt"
    if extension == "zip":
        with ZipFile(path, "w") as archive:
            archive.writestr(member, payload)
    elif extension == "tar":
        with tarfile.open(path, "w") as archive:
            entry = tarfile.TarInfo(member)
            entry.size = len(payload)
            archive.addfile(entry, BytesIO(payload))
    elif extension == "gz":
        path.write_bytes(gzip.compress(payload))
        member = "notes"
    else:
        message = EmailMessage()
        message.set_content("Report attached")
        message.add_attachment(
            payload, maintype="text", subtype="plain", filename=member
        )
        path.write_bytes(message.as_bytes())
    size = path.stat().st_size
    bounded = FileSystem(
        LocalWorkspace(tmp_path), options=FileOptions(max_file_bytes=size - 1)
    )
    with pytest.raises(ValueError, match="max_file_bytes"):
        await bounded.read_file(path.name, member=member)
    assert not (tmp_path / ".content").exists()
    exact = FileSystem(
        LocalWorkspace(tmp_path), options=FileOptions(max_file_bytes=size)
    )
    assert payload.decode() in (await exact.read_file(path.name, member=member)).text


async def test_nested_member_cannot_bypass_input_size_limit(tmp_path):
    inner = BytesIO()
    with ZipFile(inner, "w") as archive:
        archive.writestr("notes.txt", "x" * 4096)
    path = tmp_path / "outer.zip"
    with ZipFile(path, "w", compression=8) as archive:
        archive.writestr("inner.zip", inner.getvalue())
    assert path.stat().st_size < len(inner.getvalue())
    files = FileSystem(
        LocalWorkspace(tmp_path),
        options=FileOptions(max_file_bytes=path.stat().st_size),
    )
    with pytest.raises(ValueError, match="max_file_bytes"):
        await files.read_file(path.name, member="inner.zip!/notes.txt")
