from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from harnessed import (
    Context,
    Inject,
    Observation,
    Plugin,
    PluginState,
    SessionLog,
    SystemSection,
    ToolInfo,
    ToolResult,
    hook,
)
from harnessed.hooks import (
    ExecuteTool,
    Next,
    PrepareRequest,
    Priority,
    ReviewToolResult,
)
from harnessed.models import TextPart

from browserrig.browser import Browser, BrowserEvents
from browserrig.core import ActionKind, BrowserToolMetadata, SecretError
from browserrig.events import SECRET_EVENTS, BrowserEvent, LiveEvent, SecretEnteredEvent
from browserrig.scripts import (
    SECRET_FIELD,
    SECRET_FOCUS,
    SecretFieldArgs,
    SecretFocusArgs,
)

from .models import NAME, PLACEHOLDER, Secret, resolve
from .redaction import Redactor
from .state import SecretsState

if TYPE_CHECKING:
    from browserrig.browser import Frame
    from browserrig.input import Keyboard
    from browserrig.observation import ElementHandle, Snapshot

# Only these tools resolve placeholders, and only in their `text` argument.
_TYPING_TOOLS = frozenset({"type_text", "send_keys"})
_SOURCE = "browser.secrets"


@dataclass(frozen=True, slots=True, eq=False)
class SecretEntry:
    """Text prepared for one field, checked against each secret's domains."""

    names: tuple[str, ...]
    origin: str
    target_id: str
    document_id: str
    parts: tuple[tuple[str, bool], ...] = dataclass_field(repr=False)
    guard: Callable[[], Awaitable[None]] = dataclass_field(repr=False)


class Secrets(Plugin, provides=True, needs=(SessionLog, BrowserEvents)):
    """Let the agent type credentials as `{{secret:NAME}}` without ever seeing them.

    Values live only in this plugin. Each secret is typed only on its domains; every text
    that reaches the model, the session log or event subscribers is redacted.
    """

    events = SECRET_EVENTS
    _state = PluginState(SecretsState)
    _events: Inject[BrowserEvents]

    def __init__(self, secrets: Mapping[str, Secret]) -> None:
        super().__init__()
        for name, secret in secrets.items():
            if not isinstance(name, str) or not NAME.fullmatch(name):
                raise ValueError(
                    f"Secret name {name!r} may only use letters, digits, _ . and -"
                )
            if not isinstance(secret, Secret):
                raise TypeError(f"Secret {name} must be a Secret")
        self._secrets = dict(secrets)
        self._values: dict[str, str] = {}
        self._redactor = Redactor()

    def __repr__(self) -> str:
        return f"Secrets({', '.join(self._secrets)})"

    instructions = SystemSection(
        title="Secrets",
        text=(
            "Credentials are never shown to you. Type one by writing its placeholder, such as "
            "{{secret:NAME}}, in the text of type_text or send_keys; the browser types the "
            "value. Observations list the secrets available on the current page. A secret "
            "works only on its own sites, other tools reject placeholders, and page content "
            "shows typed secrets as their placeholder. JavaScript execution is unavailable "
            "after a secret was entered."
        ),
    )

    async def setup(self, ctx: Context) -> None:
        # Imported here: observation imports this package to redact snapshots.
        from browserrig.observation import (  # pylint: disable=import-outside-toplevel,cyclic-import
            Observe,
        )

        if Observe in ctx:
            # Observe binds Secrets when mounted; mounted earlier, it would never redact.
            raise ValueError(
                "Mount Secrets before Observe, e.g. via browser_plugins(secrets=...)"
            )
        for name, secret in self._secrets.items():
            if not secret.rotating:
                self._learn(name, await resolve(name, secret.value))
        ctx.effect(self._events.add_filter(self._filter_event))

    def redact[T](self, value: T) -> T:
        """Replace every known secret value in `value` with its placeholder."""
        return self._redactor.scrub(value)

    def contains(self, text: str) -> bool:
        return self._redactor.contains(text)

    def available(self, url: str) -> tuple[str, ...]:
        origin = _origin(url)
        return tuple(
            name for name, secret in self._secrets.items() if secret.allows(origin)
        )

    def project(self, snapshot: Snapshot) -> Observation | None:
        """List the secrets usable on the observed page; values are never part of it."""
        names = self.available(snapshot.url)
        if not names and not self._state.listed:
            return None
        self._state.listed = bool(names)
        host = urlsplit(snapshot.url).hostname or snapshot.url
        content = (
            f"Secrets for {host}: {', '.join(names)}\n"
            "Type them as {{secret:NAME}} with type_text or send_keys."
            if names
            else "No secrets are available for this page."
        )
        return Observation(
            source=_SOURCE,
            content=content,
        )

    async def prepare(  # pylint: disable=too-many-branches
        self, text: str, *, browser: Browser, field: ElementHandle | None = None
    ) -> SecretEntry | None:
        """Check where `text`'s placeholders would be typed; None when it has none.

        `field` is the target element, otherwise the current focus. Call before focusing or
        clearing, so a rejected secret leaves the page untouched.
        """
        segments = PLACEHOLDER.split(text)
        names = tuple(dict.fromkeys(segments[1::2]))
        if not names:
            return None
        for name in names:
            if name not in self._secrets:
                raise SecretError(
                    f"Unknown secret {name}; use a name listed for this page"
                )
        tab = browser.active_tab
        if field is not None:
            origins = await _field_origins(field)
        else:
            main = await tab.main_frame()
            focus = await main.run(SECRET_FOCUS, SecretFocusArgs())
            if focus.cross_origin:
                raise SecretError(
                    "The focused field is in a cross-origin frame; use type_text with its ref"
                )
            if not focus.editable:
                raise SecretError("Focus a text field before typing a secret")
            origins = focus.origins
        for name in names:
            denied = next(
                (o for o in origins if not self._secrets[name].allows(o)), None
            )
            if denied is not None:
                shown = denied if denied != "null" else "an opaque origin"
                raise SecretError(f"Secret {name} is not allowed on {shown}")
        values = {name: await self._value(name) for name in names}
        parts = tuple(
            (values[segment], True) if index % 2 else (segment, False)
            for index, segment in enumerate(segments)
            if segment
        )
        if field is not None:
            marked = await field.run(SECRET_FIELD, SecretFieldArgs(mask=True))
            if marked.origin != origins[0]:
                raise SecretError(
                    "The field's page changed; retry with refs from the next observation"
                )
            guard = _field_guard(browser, tab.id, field, origins)
        else:
            start = await main.run(SECRET_FOCUS, SecretFocusArgs(start=True))
            if not start.same or start.origins != origins:
                raise SecretError(
                    "Focus changed while preparing the secret; observe first"
                )
            guard = _focus_guard(browser, tab.id, main, origins)
        return SecretEntry(names, origins[0], tab.id, tab.document_id, parts, guard)

    async def enter(self, entry: SecretEntry, keyboard: Keyboard) -> None:
        """Type prepared text; focus is re-checked before each secret character."""
        # The page may keep the value beyond the field, so mark the session before typing.
        self._state.entered = True
        await self._events.emit(
            SecretEnteredEvent(
                names=entry.names,
                origin=entry.origin,
                target_id=entry.target_id,
                document_id=entry.document_id,
            )
        )
        try:
            for text, secret in entry.parts:
                if secret:
                    await keyboard.type_text(text, sensitive=True, guard=entry.guard)
                else:
                    await keyboard.type_text(text)
        except SecretError:
            raise
        except Exception:  # pylint: disable=broad-exception-caught
            # Lower-level errors may carry typed text; report only that typing stopped.
            raise SecretError(
                "Typing the secret stopped; the field may be partly filled. Observe before retrying"
            ) from None

    @hook(ExecuteTool, priority=Priority.GUARD)
    async def _guard_tool(
        self, event: ExecuteTool, next_: Next[ToolResult]
    ) -> ToolResult:
        call = event.call
        allowed = ("text",) if call.name in _TYPING_TOOLS else ()
        if any(
            _has_placeholder(value)
            for key, value in call.arguments.items()
            if key not in allowed
        ):
            return ToolResult.error(
                "Secret placeholders work only in the text of type_text or send_keys."
            )
        if self._state.entered and _runs_javascript(call.name, event.tool):
            return ToolResult.error(
                "JavaScript execution is unavailable after a secret was entered in this session."
            )
        return self._redact_result(await next_())

    @hook(ReviewToolResult, priority=Priority.GUARD)
    async def _review_tool(
        self, _event: ReviewToolResult, next_: Next[ToolResult]
    ) -> ToolResult:
        return self._redact_result(await next_())

    @hook(PrepareRequest, priority=Priority.GUARD)
    async def _prepare_request(self, _event: PrepareRequest, next_: Next[Any]) -> Any:
        request = await next_()
        if not self._redactor:
            return request
        messages = tuple(
            _redact_message(self._redactor, message) for message in request.messages
        )
        if all(new is old for new, old in zip(messages, request.messages, strict=True)):
            return request
        return replace(request, messages=messages)

    def _filter_event(
        self, event: BrowserEvent | LiveEvent
    ) -> BrowserEvent | LiveEvent:
        return self._redactor.scrub(event)

    def _redact_result(self, result: ToolResult) -> ToolResult:
        if not self._redactor:
            return result
        content = _redact_content(self._redactor, result.content)
        return result if content is result.content else replace(result, content=content)

    async def _value(self, name: str) -> str:
        secret = self._secrets[name]
        if not secret.rotating and name in self._values:
            return self._values[name]
        value = await resolve(name, secret.value)
        self._learn(name, value)
        return value

    def _learn(self, name: str, value: str) -> None:
        if not self._secrets[name].rotating:
            self._values[name] = value
        self._redactor.add(name, value)


async def _field_origins(field: ElementHandle) -> tuple[str, ...]:
    """The field's origin, then each embedding document's origin up to the main frame."""
    origins = [(await field.run(SECRET_FIELD, SecretFieldArgs())).origin]
    frame: Frame | None = field.frame
    while frame is not None and frame.parent is not None:
        origins.append(
            (await frame.run_on_owner(SECRET_FIELD, SecretFieldArgs())).origin
        )
        frame = frame.parent
    return tuple(origins)


def _field_guard(
    browser: Browser, tab_id: str, field: ElementHandle, origins: tuple[str, ...]
) -> Callable[[], Awaitable[None]]:
    async def guard() -> None:
        if browser.active_tab.id != tab_id:
            raise SecretError(
                "The active tab changed while typing a secret; typing stopped"
            )
        state = await field.run(SECRET_FIELD, SecretFieldArgs())
        if not state.focused or state.origin != origins[0]:
            raise _left_field()
        frame: Frame | None = field.frame
        while frame is not None and frame.parent is not None:
            # Focus inside a frame counts only while its iframe holds focus in the parent.
            owner = await frame.run_on_owner(SECRET_FIELD, SecretFieldArgs())
            if not owner.focused:
                raise _left_field()
            frame = frame.parent

    return guard


def _focus_guard(
    browser: Browser, tab_id: str, main: Frame, origins: tuple[str, ...]
) -> Callable[[], Awaitable[None]]:
    async def guard() -> None:
        if browser.active_tab.id != tab_id:
            raise SecretError(
                "The active tab changed while typing a secret; typing stopped"
            )
        state = await main.run(SECRET_FOCUS, SecretFocusArgs())
        if state.cross_origin or not state.same or state.origins != origins:
            raise _left_field()

    return guard


def _left_field() -> SecretError:
    return SecretError(
        "Focus left the field while typing a secret; typing stopped. Observe first"
    )


def _origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return "null"
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def _has_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return PLACEHOLDER.search(value) is not None
    if isinstance(value, Mapping):
        return any(
            _has_placeholder(key) or _has_placeholder(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_has_placeholder(item) for item in value)
    return False


def _runs_javascript(name: str, tool: ToolInfo | None) -> bool:
    metadata = tool.metadata.get(BrowserToolMetadata) if tool is not None else None
    return name == "execute_javascript" or (
        metadata is not None and metadata.kind == ActionKind.JAVASCRIPT
    )


def _redact_content(redactor: Redactor, content: Any) -> Any:
    if isinstance(content, str):
        redacted = redactor.text(content)
        return content if redacted == content else redacted
    parts = tuple(
        TextPart(redactor.text(part.text)) if isinstance(part, TextPart) else part
        for part in content
    )
    return content if parts == tuple(content) else parts


def _redact_message(redactor: Redactor, message: Any) -> Any:
    content = getattr(message, "content", None)
    if content is None or isinstance(content, (bytes, bytearray)):
        return message
    redacted = _redact_content(redactor, content)
    return message if redacted is content else replace(message, content=redacted)
