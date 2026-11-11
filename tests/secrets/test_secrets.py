import base64
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from harnessed import (
    Agent,
    Inject,
    Plugin,
    PolicyDecision,
    ToolResult,
    tool,
)
from harnessed.events import InboxAddedEvent, UserMessageEvent
from harnessed.kernel import PluginScope, needs
from harnessed.plugins import Approvals
from harnessed.testing import ScriptedModel, call
from PIL import Image

from browserrig import BrowserPerception, Readiness, Secret, Secrets, Totp, env
from browserrig.core import ActionKind, Bounds, SecretError
from browserrig.events import ActionFailedEvent, KeyPressedEvent, SecretEnteredEvent
from browserrig.input import Input
from browserrig.input import keyboard as keyboard_module
from browserrig.observation import CaptureContent, DomPerception, Element, Snapshot
from browserrig.observation.capture import _redact
from browserrig.observation.extraction import Extraction
from browserrig.observation.marks import blackout
from browserrig.secrets import SecretEntry
from browserrig.secrets.models import resolve
from browserrig.secrets.origin import OriginPattern
from browserrig.secrets.redaction import Redactor
from tests.fakes import FakeChrome

PASSWORD = "hunter2-Correct-Horse"


@pytest.mark.parametrize(
    "pattern,origin,allowed",
    [
        ("github.com", "https://github.com", True),
        ("github.com", "https://github.com:8443", True),
        ("github.com", "http://github.com", False),
        ("github.com", "https://gist.github.com", False),
        ("github.com", "https://github.com.evil.example", False),
        ("github.com", "https://evilgithub.com", False),
        ("GitHub.com", "https://GITHUB.com", True),
        ("*.github.com", "https://gist.github.com", True),
        ("*.github.com", "https://github.com", False),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000", True),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8001", False),
        ("https://example.org", "https://example.org:443", True),
        ("https://example.org", "https://example.org:8443", False),
        ("bücher.de", "https://xn--bcher-kva.de", True),
        ("github.com", "null", False),
        ("github.com", "file://github.com", False),
    ],
)
def test_origin_patterns_match_scheme_host_and_port_exactly(pattern, origin, allowed):
    assert OriginPattern.parse(pattern).allows(origin) is allowed


@pytest.mark.parametrize(
    "pattern",
    [
        "github.com/login",
        "https://github.com/login",
        "https://user@github.com",
        "ftp://github.com",
        "git*.com",
        "*",
        "",
        "https://github.com?x=1",
    ],
)
def test_origin_patterns_reject_paths_credentials_and_wildcards(pattern):
    with pytest.raises(ValueError):
        OriginPattern.parse(pattern)


def test_secret_reprs_never_show_values():
    secret = Secret(PASSWORD, domains="github.com")
    assert PASSWORD not in repr(secret)
    assert PASSWORD not in repr(Secrets({"pw": secret}))
    assert "JBSWY3DP" not in repr(Totp("JBSWY3DPEHPK3PXP"))
    assert secret.domains == ("github.com",)


def test_secrets_reject_invalid_names_and_domainless_secrets():
    with pytest.raises(ValueError):
        Secrets({"bad name": Secret(PASSWORD, domains=("github.com",))})
    with pytest.raises(ValueError):
        Secret(PASSWORD, domains=())


@pytest.mark.parametrize(
    "timestamp,code",
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
    ],
)
def test_totp_matches_rfc_6238_vectors(timestamp, code):
    seed = base64.b32encode(b"12345678901234567890").decode()
    assert Totp(seed, digits=8).at(timestamp) == code


def test_totp_rejects_invalid_seeds_without_echoing_them():
    with pytest.raises(SecretError) as error:
        Totp("not base32 !!")
    assert "not base32" not in str(error.value)


async def test_resolve_errors_name_the_secret_but_never_its_value(monkeypatch):
    def broken():
        raise RuntimeError(f"backend failed for {PASSWORD}")

    with pytest.raises(SecretError) as error:
        await resolve("pw", broken)
    assert "pw" in str(error.value) and PASSWORD not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__
    with pytest.raises(SecretError):
        await resolve("pw", "abc")
    monkeypatch.delenv("BROWSERRIG_TEST_SECRET", raising=False)
    with pytest.raises(SecretError, match="BROWSERRIG_TEST_SECRET"):
        await resolve("pw", env("BROWSERRIG_TEST_SECRET"))
    monkeypatch.setenv("BROWSERRIG_TEST_SECRET", PASSWORD)
    assert await resolve("pw", env("BROWSERRIG_TEST_SECRET")) == PASSWORD


@pytest.mark.parametrize(
    "shown",
    [
        PASSWORD,
        PASSWORD.upper(),
        "p%40ss%2Fword%20x",
        "p%40ss%2Fword+x",
        "p%40ss/word%20x",
    ],
)
def test_redactor_hides_values_case_insensitively_and_in_common_encodings(shown):
    redactor = Redactor()
    redactor.add("pw", PASSWORD)
    redactor.add("enc", "p@ss/word x")
    text = redactor.text(f"before {shown} after")
    assert text.startswith("before {{secret:") and text.endswith("}} after")


def test_redactor_hides_html_and_json_escaped_values():
    redactor = Redactor()
    redactor.add("pw", 'a<b>"c"&d')
    assert redactor.text("x a&lt;b&gt;&quot;c&quot;&amp;d y") == "x {{secret:pw}} y"
    assert redactor.text('{"v": "a<b>\\"c\\"&d"}') == '{"v": "{{secret:pw}}"}'


def test_redactor_prefers_the_longest_value():
    redactor = Redactor()
    redactor.add("short", "abcd")
    redactor.add("long", "abcdefgh")
    assert redactor.text("abcdefgh abcd") == "{{secret:long}} {{secret:short}}"


class _Color(StrEnum):
    RED = "red-hunter2-Correct-Horse"


@dataclass(frozen=True)
class _Record:
    text: str
    color: _Color
    action_id: str
    nested: tuple[str, ...]


def test_scrub_redacts_nested_text_but_keeps_identifiers_and_enums():
    redactor = Redactor()
    redactor.add("pw", PASSWORD)
    record = _Record(PASSWORD, _Color.RED, PASSWORD, (f"x{PASSWORD}",))
    scrubbed = redactor.scrub({"items": [record], "count": 3})
    assert scrubbed["items"][0] == _Record(
        "{{secret:pw}}", _Color.RED, PASSWORD, ("x{{secret:pw}}",)
    )
    assert scrubbed["count"] == 3
    clean = _Record("clean", _Color.RED, "id", ())
    assert redactor.scrub(clean) is clean


def test_blackout_paints_regions_in_image_pixels():
    output = BytesIO()
    Image.new("RGB", (200, 100), "white").save(output, format="PNG")
    image = base64.b64encode(output.getvalue()).decode()
    area = Bounds(x=50, y=0, width=100, height=50)
    masked = blackout(image, (Bounds(x=60, y=10, width=20, height=10),), area, scale=2)
    with Image.open(BytesIO(base64.b64decode(masked))) as result:
        assert result.getpixel((30, 30)) == (0, 0, 0)
        assert result.getpixel((19, 30)) == (0, 0, 0)
        assert result.getpixel((5, 5)) == (255, 255, 255)
        assert result.getpixel((70, 70)) == (255, 255, 255)


async def test_capture_redacts_page_text_and_blacks_out_fields_showing_a_secret():
    redactor = Redactor()
    redactor.add("pw", PASSWORD)
    redaction = SimpleNamespace(redact=redactor.scrub)
    field = Element(
        ref="e1",
        frame_id="f",
        backend_id=1,
        role="textbox",
        name="Password",
        tag="input",
        value=PASSWORD,
        bounds=Bounds(x=10, y=10, width=40, height=10),
    )
    other = field.model_copy(update={"ref": "e2", "value": "visible", "bounds": None})
    page = Extraction(
        url="https://example.org/",
        title="Login",
        width=100,
        height=50,
        scroll_y=0,
        page_height=50,
        elements=(field, other),
        text="Log in to continue",
    )
    output = BytesIO()
    Image.new("RGB", (100, 50), "white").save(output, format="PNG")
    image = base64.b64encode(output.getvalue()).decode()
    area = Bounds(x=0, y=0, width=100, height=50)
    content = CaptureContent(page=page, image=image, area=area)
    redacted, masked = await _redact(page, image, content, redaction)
    assert PASSWORD not in repr(redacted)
    assert redacted.elements[0].value == "{{secret:pw}}"
    assert redacted.elements[1] is other
    assert masked is not None
    with Image.open(BytesIO(base64.b64decode(masked))) as result:
        assert result.getpixel((20, 15)) == (0, 0, 0)
        assert result.getpixel((80, 40)) == (255, 255, 255)
    # Without a known image area the screenshot is withheld instead of shown.
    _, withheld = await _redact(
        page, image, CaptureContent(page=page, image=image), redaction
    )
    assert withheld is None


async def test_sensitive_typing_hides_keys_and_stops_when_the_guard_fails(monkeypatch):
    monkeypatch.setattr(keyboard_module.asyncio, "sleep", AsyncMock())
    events, chars = [], []

    async def dispatch_key(kind, **arguments):
        if kind == "char":
            chars.append(arguments["text"])

    async def emit(event):
        events.append(event)

    tab = SimpleNamespace(id="tab-1", dispatch_key=dispatch_key, emit=emit)
    devices = Input(lambda: tab)
    monkeypatch.setattr(devices.keyboard, "_emit", lambda _target, event: emit(event))
    checks = 0

    async def guard():
        nonlocal checks
        checks += 1
        if checks > 3:
            raise SecretError("Focus left the field")

    with pytest.raises(SecretError):
        await devices.keyboard.type_text("Ab#defg", sensitive=True, guard=guard)
    keys = [event for event in events if isinstance(event, KeyPressedEvent)]
    assert chars == list("Ab#")
    assert [event.key for event in keys] == ["•"] * 3
    assert all(event.modifiers == () for event in keys)


def _agent(secrets, *, model, plugins=()):
    holder = {}

    class Capture(Plugin, needs=(Secrets,)):
        _setup_mounted = needs(Secrets)

        async def setup(self, _ctx: PluginScope):
            mounted = self._setup_mounted
            holder["secrets"] = mounted

    # The fake browser also produces events that tests emit through it.
    class Chrome(FakeChrome):
        events = (ActionFailedEvent,)

    allow = Approvals(default=PolicyDecision.ALLOW)
    agent = Agent(
        model=model,
        plugins=[Chrome(holder), secrets, Capture(), allow, *plugins],
    )
    return agent, holder


def _secrets():
    return Secrets(
        {
            "pw": Secret(PASSWORD, domains=("example.org",)),
            "otp": Secret(Totp("JBSWY3DPEHPK3PXP"), domains=("example.org",)),
        }
    )


class Leaky(Plugin):
    @tool(description="Return the page title.")
    async def leak(self) -> ToolResult:
        return ToolResult(f"Title: welcome back {PASSWORD}")

    @tool(description="Run JavaScript.")
    async def execute_javascript(self, code: str) -> ToolResult:
        return ToolResult(f"ran {code}")

    @tool(description="Navigate.")
    async def navigate(self, url: str) -> ToolResult:
        return ToolResult(f"navigated to {url}")


async def test_model_requests_never_contain_secret_values():
    model = ScriptedModel([call("leak"), "done"])
    agent, _ = _agent(_secrets(), model=model, plugins=[Leaky()])
    result = await agent.run(f"My password is {PASSWORD}, log in", max_steps=3)
    assert result.text == "done"
    for request in model.requests:
        assert PASSWORD not in repr(request.messages)
    assert "{{secret:pw}}" in repr(model.requests[-1].messages)
    assert "{{secret:NAME}}" in repr(model.requests[0].messages)
    # Only the user's own prompt keeps the value in the log; tool output never does.
    leaked = {type(event) for event in result.events if PASSWORD in repr(event)}
    assert leaked == {InboxAddedEvent, UserMessageEvent}


async def test_placeholders_are_rejected_outside_typing_tools():
    model = ScriptedModel(
        [call("navigate", url="https://example.org/?q={{secret:pw}}"), "done"]
    )
    agent, _ = _agent(_secrets(), model=model, plugins=[Leaky()])
    await agent.run("go", max_steps=3)
    reply = repr(model.requests[-1].messages)
    assert "only in the text of type_text or send_keys" in reply
    assert "navigated to" not in reply


async def test_javascript_is_blocked_before_and_after_secret_entry(monkeypatch):
    monkeypatch.setattr(keyboard_module.asyncio, "sleep", AsyncMock())
    entered = False

    class Enter(Plugin, needs=(Secrets,)):
        @tool(description="Enter.")
        async def enter(self, mounted: Inject[Secrets]) -> ToolResult:
            nonlocal entered
            entry = SecretEntry(
                ("pw",),
                "https://example.org",
                "tab-1",
                "doc-1",
                ((PASSWORD, True),),
                AsyncMock(),
            )
            await mounted.enter(entry, SimpleNamespace(type_text=AsyncMock()))
            entered = True
            return ToolResult("ok")

    model = ScriptedModel(
        [
            call("execute_javascript", code="1"),
            call("enter"),
            call("execute_javascript", code="2"),
            "done",
        ]
    )
    agent, _ = _agent(_secrets(), model=model, plugins=[Leaky(), Enter()])
    result = await agent.run("go", max_steps=5)
    assert entered
    replies = repr(model.requests[-1].messages)
    assert "ran 1" not in replies and "ran 2" not in replies
    assert "JavaScript execution is unavailable" in replies
    events = [event for event in result.events if isinstance(event, SecretEnteredEvent)]
    assert [(event.names, event.origin) for event in events] == [
        (("pw",), "https://example.org")
    ]


async def test_browser_events_are_redacted_before_they_are_logged():
    agent, holder = _agent(_secrets(), model=ScriptedModel(["done"]))
    async with agent.session() as session:
        await holder["browser"].events.emit(
            ActionFailedEvent(
                action_id="a",
                kind=ActionKind.TYPE,
                dispatched=True,
                reason=f"bad {PASSWORD}",
            )
        )
        failed = [
            event for event in session.events if isinstance(event, ActionFailedEvent)
        ]
    assert failed[0].reason == "bad {{secret:pw}}"


async def test_project_lists_names_for_allowed_origins_only():
    agent, holder = _agent(_secrets(), model=ScriptedModel(["done"]))

    def snapshot(url):
        return Snapshot(
            id="s",
            tab_id="t",
            document_id="d",
            url=url,
            title="",
            readiness="ready",
            width=1,
            height=1,
            scroll_y=0,
            fingerprint="f",
        )

    async with agent.session():
        secrets = holder["secrets"]
        assert secrets.project(snapshot("https://other.example/")) is None
        listed = secrets.project(snapshot("https://example.org/login"))
        assert listed is not None
        assert "Secrets for example.org: pw, otp" in listed.content
        assert PASSWORD not in listed.content
        assert secrets.project(snapshot("http://example.org/")).content == (
            "No secrets are available for this page."
        )
        assert secrets.project(snapshot("https://other.example/")) is None


async def test_prepare_rejects_unknown_names_before_touching_the_page():
    agent, holder = _agent(_secrets(), model=ScriptedModel(["done"]))
    async with agent.session():
        browser = SimpleNamespace(active_tab=SimpleNamespace(main_frame=AsyncMock()))
        assert await holder["secrets"].prepare("plain text", browser=browser) is None
        with pytest.raises(SecretError, match="Unknown secret missing"):
            await holder["secrets"].prepare("{{secret:missing}}", browser=browser)
        browser.active_tab.main_frame.assert_not_awaited()


async def test_observe_redacts_with_secrets_mounted_after_it():
    holder = {}

    class Hold(Plugin, needs=(BrowserPerception,)):
        _setup_observe = needs(BrowserPerception)

        async def setup(self, _ctx: PluginScope):
            observe = self._setup_observe
            holder["observe"] = observe

    agent = Agent(
        model=ScriptedModel(["done"]),
        plugins=[
            FakeChrome(holder),
            Readiness(),
            DomPerception(),
            Hold(),
            _secrets(),
        ],
    )
    snapshot = Snapshot(
        id="s",
        tab_id="t",
        document_id="d",
        url="https://example.org/",
        title=f"Welcome {PASSWORD}",
        readiness="ready",
        width=1,
        height=1,
        scroll_y=0,
        fingerprint="f",
    )
    async with agent.session():
        observation = holder["observe"].project(snapshot)
    assert "Welcome {{secret:pw}}" in observation.content
    assert PASSWORD not in observation.content
