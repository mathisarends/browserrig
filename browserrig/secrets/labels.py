from harnessed import envelope_value
from harnessed.events import ToolCallFinishedEvent, ToolCallRequestedEvent
from harnessed.kernel import PluginScope, Scope

from browserrig.core import ActionLabel

from .plugin import Secrets


def action_label(
    event: ToolCallRequestedEvent | ToolCallFinishedEvent,
    *,
    scope: Scope | PluginScope,
) -> str:
    """Read a call's display label, redacting the active session's known secrets.

    Missing or invalid labels return an empty string. The session scope is required
    so callers cannot accidentally skip configured redaction. Raw events stay intact.
    """
    value = envelope_value(event.call, ActionLabel)
    if value is None:
        return ""
    text = value.action_label
    return scope[Secrets].redact(text) if Secrets in scope else text
