"""Native Harnessed extension points; these requests are not durable receipts."""

from dataclasses import dataclass

from harnessed.kernel import Bail, Waterfall

from .policies import ReadinessContext, ReadinessPolicy


@dataclass(frozen=True)
class ReadinessCheck:
    ready: bool
    reason: str = ""


@dataclass(frozen=True)
class SelectReadiness(Bail[ReadinessPolicy]):
    """First non-None policy wins; otherwise use the configured stage policy."""

    context: ReadinessContext


@dataclass(frozen=True)
class CheckReadiness(Waterfall[ReadinessCheck]):
    """Compose application checks around the current policy's probe."""

    context: ReadinessContext
