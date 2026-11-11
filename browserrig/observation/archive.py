import json
from datetime import UTC, datetime
from uuid import uuid4

from browserrig.files import FileSystem

from .content import PageContent


async def save_content(
    files: FileSystem, content: PageContent, *, full_page: bool
) -> PageContent:
    directory = f"pages/{uuid4().hex}"
    path = f"{directory}/content.md"
    await files.write_file(path, content.render())
    metadata = content.model_dump(exclude={"markdown"})
    metadata.update(
        captured_at=datetime.now(UTC).isoformat(),
        full_page=full_page,
        extracted_path=path,
    )
    await files.write_file(
        f"{directory}/source.json", json.dumps(metadata, ensure_ascii=False, indent=2)
    )
    return content.model_copy(update={"extracted_path": path})
