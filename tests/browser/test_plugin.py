from pathlib import Path
from unittest.mock import Mock

import pytest
from harnessed import Agent as HarnessedAgent
from harnessed.testing import ScriptedModel
from pydantic import SecretStr, ValidationError

from browserrig import (
    Agent,
    Chrome,
    MountedWorkspace,
    Viewport,
    browser_pack,
    browser_plugins,
)
from browserrig.browser import Connect, Launch
from browserrig.browser import plugin as chrome_plugin


def test_factories_validate_options_without_opening_resources(monkeypatch):
    runtime = Mock(side_effect=AssertionError("Browser opened before session entry"))
    monkeypatch.setattr(chrome_plugin, "ChromeBrowser", runtime)
    bridge = MountedWorkspace("/workspace")
    setup = _SessionProbe()
    launched = Chrome.launch(
        executable=Path("chrome"),
        headless=False,
        url="https://example.org",
        viewport=Viewport(width=900),
        timeout=12,
        arguments=("--disable-extensions",),
        session_setup=(setup,),
    )
    connected = Chrome.connect(
        endpoint="http://localhost:9222",
        url="https://example.org",
        timeout=12,
        headers={"Authorization": "Bearer credential"},
        viewport=Viewport(width=900),
        bridge=bridge,
        session_setup=(setup,),
    )
    for browser in (launched, connected):
        agent = Agent(model=ScriptedModel([]), browser=browser)
        assert (
            next(item for item in agent.plugins if isinstance(item, Chrome)) is browser
        )
        assert browser.options.url == "https://example.org"
        assert browser.options.viewport.width == 900
        assert browser.options.timeout == 12
        assert browser.options.session_setup == (setup,)
    assert isinstance(launched.options, Launch)
    assert launched.options.executable == Path("chrome")
    assert not launched.options.headless
    assert launched.options.arguments == ("--disable-extensions",)
    # A launched Chrome shares this machine's disk with the workspace.
    assert launched.options.bridge == MountedWorkspace()
    assert connected.options.bridge is bridge
    assert isinstance(connected.options, Connect)
    assert (
        connected.options.headers["Authorization"].get_secret_value()
        == "Bearer credential"
    )
    assert "credential" not in repr(connected.options)
    runtime.assert_not_called()


@pytest.mark.parametrize("mode", ["launch", "connect"])
@pytest.mark.parametrize("composition", ["facade", "kit", "flat", "manual"])
def test_configured_plugin_is_used_once_across_composition_apis(mode, composition):
    browser = (
        Chrome.launch()
        if mode == "launch"
        else Chrome.connect(endpoint="http://localhost:9222")
    )
    match composition:
        case "facade":
            agent = Agent(model=ScriptedModel([]), browser=browser)
        case "kit":
            agent = HarnessedAgent(
                model=ScriptedModel([]), plugins=[browser_pack(browser=browser)]
            )
        case "flat":
            agent = HarnessedAgent(
                model=ScriptedModel([]),
                plugins=browser_plugins(browser=browser),
            )
        case "manual":
            agent = HarnessedAgent(model=ScriptedModel([]), plugins=[browser])
    assert [item for item in agent.plugins if isinstance(item, Chrome)] == [browser]
    assert next(item for item in agent.plugins if isinstance(item, Chrome)) is browser


def test_factory_defaults_and_secret_inputs_preserve_existing_options():
    assert Chrome.launch().options == Chrome().options == Launch()
    endpoint = SecretStr("ws://localhost:9222/devtools/browser/credential")
    header = SecretStr("Bearer credential")
    connected = Chrome.connect(endpoint=endpoint, headers={"Authorization": header})
    assert connected.options == Connect(
        endpoint=endpoint, headers={"Authorization": header}
    )
    assert "credential" not in repr(connected.options)
    assert connected.options.bridge is None
    assert connected.options.viewport is None


@pytest.mark.parametrize("composition", ["facade", "kit", "flat"])
@pytest.mark.parametrize(
    "options", [Launch(), Connect(endpoint=SecretStr("http://localhost:9222"))]
)
def test_browser_recipe_rejects_low_level_options_with_migration_guidance(
    composition, options
):
    with pytest.raises(TypeError, match=r"use Chrome\.launch.*Chrome\.connect"):
        match composition:
            case "facade":
                Agent(model=ScriptedModel([]), browser=options)
            case "kit":
                browser_pack(browser=options)
            case "flat":
                browser_plugins(browser=options)


@pytest.mark.parametrize(
    ("factory", "options"),
    [
        (Chrome.launch, {"arguments": ("--user-data-dir=unexpected",)}),
        (Chrome.launch, {"timeout": 0}),
        (Chrome.connect, {"endpoint": "invalid"}),
        (Chrome.connect, {"endpoint": "ws://localhost:9222/devtools/page/tab"}),
        (
            Chrome.connect,
            {
                "endpoint": "http://localhost:9222",
                "target_id": "tab",
                "url": "https://example.org",
            },
        ),
    ],
)
def test_factories_keep_ownership_and_endpoint_validation(factory, options):
    with pytest.raises(ValidationError):
        factory(**options)


class _SessionProbe:
    async def apply(self, _cdp, *, frame):
        pass


def test_only_headless_launches_pin_the_viewport_so_visible_windows_can_be_resized():
    viewport = Viewport(width=900)
    assert Launch(viewport=viewport).emulated_viewport == viewport
    assert Launch(viewport=viewport, headless=False).emulated_viewport is None
    endpoint = SecretStr("http://127.0.0.1:9222")
    assert Connect(endpoint=endpoint).emulated_viewport is None
    assert Connect(endpoint=endpoint, viewport=viewport).emulated_viewport == viewport
