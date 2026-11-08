"""Wait for the requests our input started, without letting a busy network hold readiness.

A request counts only when the page started it in response to us: during the action
or navigation, within `reaction_ms` after it, or within `chain_ms` after another
counted request finished (a request chain). Requests that were already open, such as
long polls or streams, and sockets, beacons and media never count.

However busy the page stays, the network delays readiness by at most `extra_ms` past
the moment the inner policy alone was ready.
"""

from dataclasses import dataclass, field
from time import monotonic

from browserrig.core import ReadinessPhase, ReadinessStatus, record

from .policies import DomReady, ReadinessContext, ReadinessPolicy
from .strategy import ReadinessStrategy

# Plain observations and the check before an action did not cause any request.
_CAUSED = frozenset(
    {ReadinessPhase.INITIAL, ReadinessPhase.NAVIGATION, ReadinessPhase.AFTER_ACTION}
)


@dataclass(frozen=True)
class NetworkQuiet:
    """Hold `inner`'s verdict until the requests our input started have been applied."""

    inner: ReadinessPolicy = field(default_factory=DomReady)
    reaction_ms: int = 500
    chain_ms: int = 250
    settle_ms: int = 150
    extra_ms: int = 2000

    def create(self, context: ReadinessContext) -> ReadinessStrategy:
        strategy = self.inner.create(context)
        if context.phase not in _CAUSED:
            return strategy
        return NetworkReadiness(context, strategy, self)


class NetworkReadiness(ReadinessStrategy):
    def __init__(
        self, context: ReadinessContext, inner: ReadinessStrategy, policy: NetworkQuiet
    ) -> None:
        super().__init__(context.tab, context.options)
        self._inner = inner
        self._policy = policy
        self.budget = inner.budget
        self.delay = inner.delay
        now = monotonic()
        self._since = now if context.since is None else min(context.since, now)
        self._window = now + policy.reaction_ms / 1000
        self._inner_ready: float | None = None

    async def check(self) -> bool:
        ready = await self._inner.check()
        self.reason = self._inner.reason
        self.delay = self._inner.delay
        if not ready:
            return False
        now = monotonic()
        if self._inner_ready is None:
            self._inner_ready = now
        waiting = self._waiting(now)
        held = now - self._inner_ready
        if not waiting:
            record(network_ms=round(held * 1000))
            return True
        if held >= self._policy.extra_ms / 1000:
            record(network_ms=round(held * 1000), network_capped=True)
            return True
        self.reason = waiting
        return False

    def timeout_status(self) -> ReadinessStatus:
        return self._inner.timeout_status()

    def _waiting(self, now: float) -> str:
        """Why caused requests still hold readiness; empty once they are applied."""
        chain = self._policy.chain_ms / 1000
        counted_until, pending, last = self._window, 0, None
        for request in self._tab.network.since(self._since):
            if request.started > counted_until:
                break
            if request.finished is None:
                pending += 1
                counted_until = float("inf")
            else:
                last = request.finished if last is None else max(last, request.finished)
                counted_until = max(counted_until, request.finished + chain)
        if pending:
            return f"Waiting for {pending} request(s) the page started in response"
        if last is not None and now - last < self._policy.settle_ms / 1000:
            return "Waiting for the page to apply a response"
        return ""
