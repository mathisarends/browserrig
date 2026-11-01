import json

import pytest
from harnessed import Agent, Context, Inject, Plugin, PolicyDecision, ToolCall
from harnessed.events import ToolExecutionFinishedEvent
from harnessed.models import ModelChunk, ToolMessage
from harnessed.plugins import Approvals
from harnessed.testing import CallbackModel

from browserrig import (
    Browser,
    Launch,
    Observe,
    Screenshots,
    ScreenshotTrigger,
    Secret,
    Secrets,
    browser_plugins,
    wait_for_page,
)
from browserrig.events import SecretEnteredEvent
from tests.javascript import evaluate
from tests.observations import latest

pytestmark = pytest.mark.integration

PASSWORD = "hunter2-Correct-Horse"


def _model(steps):
    """Replay `steps`, each turning the latest observation into a tool call or final text."""
    index = 0

    async def respond(request):
        nonlocal index
        step = steps[min(index, len(steps) - 1)]
        index += 1
        result = step(latest(request.messages), request)
        if isinstance(result, ToolCall):
            yield ModelChunk(tool_call=result)
        else:
            yield ModelChunk(text=result)

    return CallbackModel(respond)


def _ref(state, name):
    return next(
        element["ref"] for element in state["elements"] if element["name"] == name
    )


def _replies(model):
    return [m for m in model.requests[-1].messages if isinstance(m, ToolMessage)]


async def _email(holder):
    return await evaluate(
        holder["browser"].active_tab, "document.querySelector('#email').value"
    )


class _Hold(Plugin, needs=(Browser,)):
    def __init__(self, holder):
        super().__init__()
        self.holder = holder

    async def setup(self, _ctx: Context, browser: Inject[Browser]):
        self.holder["browser"] = browser


def _agent(site, model, domains, holder, *, path="/", screenshots=False, live=None):
    secrets = Secrets({"pw": Secret(PASSWORD, domains=domains)})
    plugins = [
        *browser_plugins(
            Launch(url=site + path, arguments=("--site-per-process",)),
            observe=Observe(
                screenshots=Screenshots(
                    trigger=ScreenshotTrigger.EACH_STEP
                    if screenshots
                    else ScreenshotTrigger.ON_REQUEST
                )
            ),
            secrets=secrets,
        ),
        _Hold(holder),
        Approvals(default=PolicyDecision.ALLOW),
    ]
    if live is not None:
        plugins.append(live)
    return Agent(model=model, plugins=plugins)


async def test_typed_secret_reaches_the_page_but_never_the_model(site):
    holder = {}
    model = _model(
        [
            lambda state, _: ToolCall(
                "type_text", {"ref": _ref(state, "Email"), "text": "{{secret:pw}}"}
            ),
            lambda state, _: "Done",
        ]
    )
    agent = _agent(site, model, (site,), holder, screenshots=True)
    async with agent.session() as session:
        result = await session.run("Log in", max_steps=3)
        page = holder["browser"].active_tab
        value = await evaluate(page, "document.querySelector('#email').value")
        masked = await evaluate(
            page,
            "getComputedStyle(document.querySelector('#email')).webkitTextSecurity",
        )
    assert result.text == "Done"
    assert value == PASSWORD
    assert masked == "disc"
    first = repr(model.requests[0].messages)
    assert "Secrets for 127.0.0.1: pw" in first and "{{secret:NAME}}" in first
    for request in model.requests:
        assert PASSWORD not in repr(request.messages)
    assert "{{secret:pw}}" in repr(model.requests[-1].messages)
    assert PASSWORD not in repr(result.events)
    entered = [
        event for event in result.events if isinstance(event, SecretEnteredEvent)
    ]
    assert [(event.names, event.origin) for event in entered] == [(("pw",), site)]
    assert not any(reply.is_error for reply in _replies(model))


async def test_secret_is_refused_on_other_domains_without_touching_the_field(site):
    holder = {}
    model = _model(
        [
            lambda state, _: ToolCall(
                "type_text", {"ref": _ref(state, "Email"), "text": "x{{secret:pw}}"}
            ),
            lambda state, _: "Done",
        ]
    )
    agent = _agent(site, model, ("example.org",), holder)
    async with agent.session() as session:
        result = await session.run("Log in", max_steps=3)
        value = await _email(holder)
    assert value == ""
    replies = _replies(model)
    assert replies[0].is_error and "Secret pw is not allowed on" in replies[0].text
    assert "Secrets for" not in repr(model.requests[0].messages)
    assert not any(isinstance(event, SecretEnteredEvent) for event in result.events)


async def test_send_keys_types_into_the_focused_field_and_blocks_javascript(site):
    holder = {}
    model = _model(
        [
            lambda state, _: ToolCall("click", {"ref": _ref(state, "Email")}),
            lambda state, _: ToolCall("send_keys", {"text": "me {{secret:pw}}"}),
            lambda state, _: ToolCall("execute_javascript", {"code": "document.title"}),
            lambda state, _: "Done",
        ]
    )
    agent = _agent(site, model, (site,), holder)
    async with agent.session() as session:
        result = await session.run("Log in", max_steps=5)
        value = await _email(holder)
    assert value == f"me {PASSWORD}"
    replies = _replies(model)
    assert not replies[1].is_error
    assert (
        replies[2].is_error and "JavaScript execution is unavailable" in replies[2].text
    )
    finished = [e for e in result.events if isinstance(e, ToolExecutionFinishedEvent)]
    assert PASSWORD not in repr(finished)


async def test_send_keys_without_a_text_field_is_refused(site):
    holder = {}
    model = _model(
        [
            lambda state, _: ToolCall("send_keys", {"text": "{{secret:pw}}"}),
            lambda state, _: "Done",
        ]
    )
    agent = _agent(site, model, (site,), holder)
    async with agent.session():
        await agent.run("Log in", max_steps=3)
    replies = _replies(model)
    assert replies[0].is_error and "Focus a text field" in replies[0].text


async def test_secret_is_refused_inside_a_cross_origin_frame_of_an_allowed_page(site):
    holder = {}

    class CrossFrame(Plugin, needs=(Browser,)):
        async def setup(self, _ctx: Context, browser: Inject[Browser]):
            await wait_for_page(browser.active_tab)
            leaf = site.replace("127.0.0.1", "localhost") + "/frame-leaf"
            await evaluate(
                browser.active_tab,
                f"document.querySelector('iframe').src = {json.dumps(leaf)};",
            )

    model = _model(
        [
            lambda state, _: ToolCall(
                "type_text",
                {"ref": _ref(state, "Frame input"), "text": "{{secret:pw}}"},
            ),
            lambda state, _: ToolCall("click", {"ref": _ref(state, "Frame input")}),
            lambda state, _: ToolCall("send_keys", {"text": "{{secret:pw}}"}),
            lambda state, _: "Done",
        ]
    )
    agent = _agent(site, model, (site,), holder, path="/frame-host", live=CrossFrame())
    async with agent.session():
        await agent.run("Log in", max_steps=5)
    replies = _replies(model)
    assert replies[0].is_error and "not allowed on http://localhost" in replies[0].text
    assert replies[2].is_error and "cross-origin frame" in replies[2].text


async def test_secrets_mounted_after_observe_fail_closed(site):
    secrets = Secrets({"pw": Secret(PASSWORD, domains=(site,))})
    agent = Agent(
        model=_model([lambda state, _: "Done"]),
        plugins=[*browser_plugins(Launch(url=site)), secrets],
    )
    with pytest.raises(ExceptionGroup) as failure:
        async with agent.session():
            pass
    assert failure.group_contains(ValueError, match="Mount Secrets before Observe")
