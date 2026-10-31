from collections.abc import Callable
from pathlib import Path

from . import containers
from .config import FileSystemOptions
from .content import ParsedContent, ReadRequest

type Reader = Callable[[Path, ReadRequest, FileSystemOptions], ParsedContent]


def document(reader: Callable[[Path], ParsedContent]) -> Reader:
    return lambda path, _request, _options: reader(path)


def selected(reader: Callable[[Path, ReadRequest], ParsedContent]) -> Reader:
    return lambda path, request, _options: reader(path, request)


def ocr(reader: Callable[[Path, ReadRequest, bool], ParsedContent]) -> Reader:
    return lambda path, request, options: reader(path, request, options.ocr)


def container(format_: str) -> Reader:
    return lambda path, _request, options: containers.container_index(
        path, format_, options.max_expanded_bytes
    )
