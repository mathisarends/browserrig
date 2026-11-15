import asyncio
from dataclasses import dataclass, field
from typing import NamedTuple

from harnessed.kernel import PluginScope

from browserrig.core import TargetId

from .models import ReadinessReport


class LoadedDocument(NamedTuple):
    """A tab's document whose initial load readiness already waited for."""

    tab_id: str
    document_id: str


@dataclass
class ReadinessState:
    pending: dict[tuple[str, ...], asyncio.Task[ReadinessReport]] = field(
        default_factory=dict
    )
    cancelling: set[asyncio.Task[ReadinessReport]] = field(default_factory=set)
    initialized: set[LoadedDocument] = field(default_factory=set)
    deferred: dict[TargetId, ReadinessReport] = field(default_factory=dict)
    spent: dict[TargetId, float] = field(default_factory=dict)
    context: PluginScope | None = None
