import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from browserrig.files import FileSystem

from .content import PageContent

SNAPSHOT_NAME = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
_SNAPSHOT_NAME = re.compile(SNAPSHOT_NAME)


async def save_content(
    files: FileSystem,
    content: PageContent,
    *,
    full_page: bool,
    name: str | None = None,
) -> PageContent:
    """Save a new unique snapshot, or replace the snapshot with a predictable `name`."""
    if name is not None and not _SNAPSHOT_NAME.fullmatch(name):
        raise ValueError(
            "Use a snapshot name of 1-64 letters, digits, '_' or '-', starting with "
            "a letter or digit"
        )
    directory = f"pages/{name if name is not None else uuid4().hex}"
    path = f"{directory}/content.md"
    replace = name is not None
    await files.write_file(path, content.render(), overwrite=replace)
    metadata = content.model_dump(exclude={"markdown"})
    metadata.update(
        captured_at=datetime.now(UTC).isoformat(),
        full_page=full_page,
        extracted_path=path,
    )
    await files.write_file(
        f"{directory}/source.json",
        json.dumps(metadata, ensure_ascii=False, indent=2),
        overwrite=replace,
    )
    return content.model_copy(update={"extracted_path": path})
