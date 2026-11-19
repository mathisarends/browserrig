"""Read browser pages from the DOM: extraction, rendering, refs and DOM handles."""

from .changes import decision_change
from .content import ExtractedContent, extract_document
from .find import FindMark, FoundMatch, PageMatches, close_find, find_text
from .handle import DomElementHandle, DomReferences
from .model import DomModel, PageProse
from .models import (
    Canvas,
    ContentGroup,
    ContentNode,
    CookieBanner,
    DomContent,
    DomView,
    Element,
    ElementInfo,
    ElementRef,
    Extraction,
    Heading,
    Modal,
    Offscreen,
    Option,
    ScrollInfo,
    TextBlock,
)
from .plugin import DomPage, ResolveDomElement
from .rendering import render
from .search import PageSearch, search_content

__all__ = [
    "Canvas",
    "ContentGroup",
    "ContentNode",
    "CookieBanner",
    "DomContent",
    "DomElementHandle",
    "DomModel",
    "DomPage",
    "DomReferences",
    "DomView",
    "Element",
    "ElementInfo",
    "ElementRef",
    "Extraction",
    "ExtractedContent",
    "FindMark",
    "FoundMatch",
    "Heading",
    "Modal",
    "Offscreen",
    "Option",
    "PageMatches",
    "PageProse",
    "PageSearch",
    "ResolveDomElement",
    "ScrollInfo",
    "TextBlock",
    "close_find",
    "decision_change",
    "extract_document",
    "find_text",
    "render",
    "search_content",
]
