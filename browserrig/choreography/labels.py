from harnessed import Plugin
from harnessed.events import ToolCallFinishedEvent, ToolCallRequestedEvent
from harnessed.kernel import PluginScope, hook, needs, observes
from harnessed.sessions.log import SessionLog
from harnessed.tools import ToolRegistry, envelope_value

from browserrig.core import ActionLabel
from browserrig.secrets import Secrets

from .events import ActionEnvelope, ToolCallPhase, ToolCallPresentedEvent


class ActionLabels(Plugin, slot="browserrig.action-labels"):
    """Ask for model-written labels and publish redacted envelopes for host UIs.

    Works independently of Choreography and its overlay. No browser is required
    unless the session's other plugins require one.
    """

    events = (ToolCallPresentedEvent,)
    _registry = needs(ToolRegistry)
    _log = needs(SessionLog)
    _secrets = observes(Secrets)

    async def setup(self, scope: PluginScope) -> None:
        self._registry.envelope(ActionLabel, owner=scope)

    @hook(ToolCallRequestedEvent, ToolCallFinishedEvent)
    async def _present(
        self, event: ToolCallRequestedEvent | ToolCallFinishedEvent
    ) -> None:
        label = envelope_value(event.call, ActionLabel)
        finished = isinstance(event, ToolCallFinishedEvent)
        receipt = ToolCallPresentedEvent(
            call_id=event.call.id,
            tool_name=event.call.name,
            phase=ToolCallPhase.FINISHED if finished else ToolCallPhase.REQUESTED,
            envelope=ActionEnvelope(label.action_label if label is not None else ""),
            status=event.result.status
            if isinstance(event, ToolCallFinishedEvent)
            else None,
        )
        secrets = self._secrets
        if secrets is not None:
            receipt = secrets.redact(receipt)
        await self._log.emit(receipt)
