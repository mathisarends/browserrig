import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

from browserrig import FileSystem, FileSystemOptions

_MANIFEST = Path(__file__).with_name("file_corpus.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--workspace", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = args.directory.resolve()
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if args.worker is not None:
        entry = manifest[args.worker]
        print(json.dumps(_worker(directory / entry["name"], args.workspace, entry)))
        return 0
    directory.mkdir(parents=True, exist_ok=True)
    workspace = directory / ".validation" / uuid4().hex
    results = []
    for index, entry in enumerate(manifest):
        _source(directory, entry, args.download)
        result = _run(directory, workspace, index, entry)
        results.append(result)
        print(json.dumps(result), flush=True)
        (directory / "corpus-results.json").write_text(
            json.dumps(results, indent=2) + "\n", encoding="utf-8"
        )
    return int(any(not result["passed"] for result in results))


def _source(directory: Path, entry: dict, download: bool) -> Path:
    path = directory / entry["name"]
    if not path.exists() and download:
        with urlopen(entry["url"], timeout=30) as response:
            content = response.read(50_000_001)
        if len(content) > 50_000_000:
            raise ValueError(f"Corpus source exceeds 50 MB: {path.name}")
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"Downloaded corpus source has changed: {path.name}")
        path.write_bytes(content)
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError(f"Corpus source digest mismatch: {path.name}")
    return path


async def _inspect(path: Path, workspace: Path, entry: dict) -> dict:
    files = FileSystem(
        FileSystemOptions(directory=workspace), download_directory=str(path.parent)
    )
    first = await files.read_file(str(path), max_chars=200000)
    selections = [{}]
    if first.sheets:
        selections = [{"sheet": sheet} for sheet in first.sheets]
    elif first.format == "pdf" and first.page_count:
        selections = [{"page_number": page} for page in range(1, first.page_count + 1)]
    chunks, limitations = [], set()
    for selection in selections:
        offset = 0
        while True:
            result = await files.read_file(
                str(path), offset=offset, max_chars=200000, **selection
            )
            chunks.append(result.text)
            limitations.update(result.limitations)
            if result.next_offset is None:
                break
            if result.next_offset <= offset:
                raise ValueError("Reader pagination did not advance")
            offset = result.next_offset
    text = "".join(chunks)
    missing = [marker for marker in entry.get("contains", []) if marker not in text]
    if missing:
        raise ValueError(f"Expected content missing: {missing}")
    if (
        first.status != entry["expected_status"]
        or len(selections) != entry["expected_views"]
    ):
        raise ValueError("Reader status or number of document views changed")
    return {
        "format": first.format,
        "status": first.status,
        "views": len(selections),
        "characters": len(text),
        "limitations": sorted(limitations),
    }


def _worker(path: Path, workspace: Path, entry: dict) -> dict:
    try:
        result = asyncio.run(_inspect(path, workspace, entry))
    except (OSError, ValueError) as error:
        if entry.get("expected_error") and entry["expected_error"] in str(error):
            return {"name": path.name, "passed": True, "expected_error": str(error)}
        return {"name": path.name, "passed": False, "error": str(error)}
    if entry.get("expected_error"):
        return {
            "name": path.name,
            "passed": False,
            "error": "Expected corrupt-file error",
        }
    return {"name": path.name, "passed": True, **result}


def _run(directory: Path, workspace: Path, index: int, entry: dict) -> dict:
    try:
        process = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                str(directory),
                "--worker",
                str(index),
                "--workspace",
                str(workspace),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return json.loads(process.stdout.strip().splitlines()[-1])
    except (subprocess.SubprocessError, ValueError) as error:
        return {"name": entry["name"], "passed": False, "error": str(error)}


if __name__ == "__main__":
    raise SystemExit(main())
