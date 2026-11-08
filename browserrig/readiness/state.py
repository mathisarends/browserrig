import asyncio
from dataclasses import dataclass, field

from harnessed.kernel import PluginScope

from browserrig.core import TargetId

from .models import ReadinessReport


@dataclass
class ReadinessState:
    pending: dict[tuple[str, ...], asyncio.Task[ReadinessReport]] = field(
        default_factory=dict
    )
    cancelling: set[asyncio.Task[ReadinessReport]] = field(default_factory=set)
    initialized: set[tuple[str, str]] = field(default_factory=set)
    deferred: dict[TargetId, ReadinessReport] = field(default_factory=dict)
    spent: dict[TargetId, float] = field(default_factory=dict)
    context: PluginScope | None = None
