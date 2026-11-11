import asyncio
import fnmatch
import json
import re
from collections.abc import Iterable
from functools import lru_cache
from io import StringIO
from pathlib import Path, PurePosixPath

from harnessed.plugins.filesystem import PathMatches, SearchResult

from .workspace import FileStat, LocalWorkspace, Workspace, workspace_path

_MAX_DIRECTORIES = 1000
_MAX_FILES = 1000
_MAX_NOTES = 20


class Search:
    """Search workspace text to EOF, independently of read_file preview limits."""

    def __init__(self, workspace: Workspace, max_bytes: int) -> None:
        self._workspace = workspace
        self._max_bytes = max_bytes

    async def glob(
        self, pattern: str, *, limit: int, include_hidden: bool
    ) -> PathMatches:
        paths, stopped = await self._paths(pattern, limit + 1, include_hidden)
        return PathMatches(
            tuple(str(item.path) for item in paths[:limit]),
            stopped or len(paths) > limit,
        )

    async def grep(
        self, query: str, *, pattern: str, limit: int, include_hidden: bool
    ) -> SearchResult:
        if not query or len(query) > 1000 or not 1 <= limit <= 500:
            raise ValueError(
                "Use a non-empty query up to 1000 characters and a limit in [1, 500]"
            )
        paths, stopped = await self._paths(pattern, _MAX_FILES + 1, include_hidden)
        notes, matches, scanned, remaining = [], [], 0, self._max_bytes
        if stopped or len(paths) > _MAX_FILES:
            notes.append(
                "Path limit reached; narrow the pattern. Search is incomplete."
            )
        expression = re.compile(re.escape(query), re.IGNORECASE)
        for entry in paths[:_MAX_FILES]:
            note = await self._coverage(entry.path)
            if note:
                notes.append(note)
            if entry.size is None or entry.size > remaining:
                notes.append(
                    f"{entry.path}: skipped; size exceeds the remaining search byte budget."
                )
                continue
            try:
                found, clipped, consumed = await self._scan(
                    entry, expression, limit - len(matches), remaining
                )
            except (OSError, UnicodeError, ValueError) as error:
                notes.append(f"{entry.path}: not searched ({type(error).__name__}).")
                continue
            remaining -= consumed
            scanned += 1
            matches.extend(
                f"{entry.path}:{line}: [offset={offset}] {text}"
                for line, offset, text in found
            )
            if clipped:
                notes.append(
                    "Match limit reached; narrow the query or pattern. Search is incomplete."
                )
                break
        if len(notes) > _MAX_NOTES:
            omitted = len(notes) - _MAX_NOTES
            notes = notes[:_MAX_NOTES] + [
                f"{omitted} additional search notes omitted; narrow the pattern."
            ]
        return SearchResult(tuple(matches), scanned, tuple(notes))

    async def _paths(
        self, pattern: str, limit: int, include_hidden: bool
    ) -> tuple[list[FileStat], bool]:
        pattern = str(workspace_path(pattern))
        if len(pattern) > 1000 or len(pattern.split("/")) > 32:
            raise ValueError("Glob pattern is too long or too deeply nested")
        if limit < 1:
            raise ValueError("Glob limit must be positive")
        pending, paths, visited = [PurePosixPath(".")], [], set()
        directories = 0
        while pending:
            parent = pending.pop()
            if isinstance(self._workspace, LocalWorkspace):
                resolved = self._workspace.host_path(parent)
                if resolved in visited:
                    continue
                visited.add(resolved)
            directories += 1
            if directories > _MAX_DIRECTORIES:
                return paths, True
            for entry in sorted(
                await self._workspace.list(parent), key=lambda item: str(item.path)
            ):
                if not include_hidden and entry.path.name.startswith("."):
                    continue
                if entry.is_directory:
                    pending.append(entry.path)
                elif _matches(entry.path.parts, tuple(pattern.split("/"))):
                    paths.append(entry)
                if len(paths) >= limit:
                    return paths, True
        return sorted(paths, key=lambda item: str(item.path)), False

    async def _scan(
        self, entry: FileStat, expression: re.Pattern[str], limit: int, budget: int
    ):
        if isinstance(self._workspace, LocalWorkspace):
            return await asyncio.to_thread(
                _scan_file,
                self._workspace.host_path(entry.path),
                expression,
                limit,
                budget,
            )
        data = await self._workspace.read_bytes(entry.path)
        if len(data) > budget:
            raise ValueError("Remote file grew beyond the remaining search byte budget")
        found, clipped = _scan_lines(
            StringIO(data.decode("utf-8-sig")), expression, limit, budget
        )
        return found, clipped, len(data)

    async def _coverage(self, path: PurePosixPath) -> str | None:
        if path.suffix != ".md":
            return None
        metadata = path.with_name(path.name[:-3] + ".extraction.json")
        stat = await self._workspace.stat(metadata)
        if stat is None and path.name == "content.md":
            metadata = path.with_name("source.json")
            stat = await self._workspace.stat(metadata)
        if stat is None:
            return None
        if stat.size is None or stat.size > 1_000_000:
            return (
                f"{path}: extraction coverage metadata was not inspected (size limit)."
            )
        try:
            details = json.loads(await self._workspace.read_bytes(metadata))
            return await self._coverage_note(path, details)
        except (OSError, ValueError, AttributeError, TypeError):
            return f"{path}: extraction coverage metadata could not be read."

    async def _coverage_note(self, path: PurePosixPath, details: dict) -> str | None:
        status = details.get(
            "status", "partial" if details.get("partial") else "complete"
        )
        pending = details.get("pending_ocr_pages", [])
        source = details.get("source")
        if isinstance(source, str) and "modified" in details and "size" in details:
            current = await self._workspace.stat(workspace_path(source))
            if current is None or (current.size, current.modified) != (
                details["size"],
                details["modified"],
            ):
                return f"{path}: source changed; saved extraction may be stale."
        if status not in {"complete", "partial", "processing", "failed"}:
            status = "unknown"
        if status != "complete" or pending or details.get("partial"):
            waiting = f"; {len(pending)} page(s) await OCR" if pending else ""
            return f"{path}: extraction is {status}{waiting}. Search covers saved text only."
        return None


@lru_cache(maxsize=8192)
def _matches(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        return _matches(path, pattern[1:]) or bool(path and _matches(path[1:], pattern))
    return bool(
        path
        and fnmatch.fnmatchcase(path[0], pattern[0])
        and _matches(path[1:], pattern[1:])
    )


def _scan_file(path: Path, expression: re.Pattern[str], limit: int, budget: int):
    before = path.stat()
    if before.st_size > budget:
        raise ValueError("File grew beyond the remaining search byte budget")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        found, clipped = _scan_lines(stream, expression, limit, budget)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("File changed during search; search it again")
    return found, clipped, before.st_size


def _scan_lines(
    lines: Iterable[str], expression: re.Pattern[str], limit: int, budget: int
) -> tuple[list[tuple[int, int, str]], bool]:
    matches, offset, consumed = [], 0, 0
    for number, line in enumerate(lines, 1):
        line_offset = offset
        offset += len(line)
        consumed += len(line.encode("utf-8"))
        if consumed > budget:
            raise ValueError("File grew beyond the remaining search byte budget")
        match = expression.search(line)
        if match is None:
            continue
        start = max(0, match.start() - 200)
        end = min(len(line), max(match.end(), match.start() + 800))
        preview = ("…" if start else "") + line[start:end].rstrip()
        if end < len(line.rstrip()):
            preview += "…"
        matches.append((number, line_offset + start, preview))
        if len(matches) >= limit:
            return matches, True
    return matches, False
