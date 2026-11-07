import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cdpify import CDPCommandError
from cdpify.domains.runtime import RemoteObject

from browserrig.browser import Frame
from browserrig.core import BrowserError
from browserrig.scripts import OWNER_SIZE, RESET, ScriptError, failure
from tests.fakes import FakeTab

_ROOT = Path(__file__).resolve().parents[2] / "browserrig"
_SCRIPTS = _ROOT / "scripts"
_JS_HINT = re.compile(
    r"\bfunction\s*\(|=>|globalThis\.|(?<![\\/])\bdocument\.\w|innerWidth"
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("document.body", True),
        ("word/document.xml", False),
        (r"word\document.xml", False),
    ],
)
def test_javascript_hint_distinguishes_ooxml_part_paths(text, expected):
    assert bool(_JS_HINT.search(text)) is expected


def test_python_contains_no_inline_javascript_except_loader_glue():
    offenders = []
    for path in _ROOT.rglob("*.py"):
        if path == _SCRIPTS / "__init__.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _JS_HINT.search(node.value)
            ):
                offenders.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
    assert not offenders


def test_scripts_are_single_matching_function_declarations():
    paths = sorted(_SCRIPTS.glob("*.js"))
    assert paths
    for path in paths:
        source = re.sub(
            r"^\s*/\*.*?\*/\s*", "", path.read_text(encoding="utf-8"), flags=re.S
        )
        name = "browserrig" + "".join(part.title() for part in path.stem.split("_"))
        assert source.startswith(f"function {name}("), path.name
        assert len(re.findall(r"^function ", source, flags=re.M)) == 1


def test_thrown_codes_are_known_script_errors():
    thrown = {
        code
        for path in _SCRIPTS.rglob("*.js")
        for code in re.findall(
            r"new Error\('([A-Z_]+)'\)", path.read_text(encoding="utf-8")
        )
    }
    assert thrown == {code.value for code in ScriptError}


@pytest.mark.parametrize("owner", [False, True])
async def test_script_errors_are_identical_for_frame_and_owner(owner):
    details = SimpleNamespace(
        exception=SimpleNamespace(description="Error: ELEMENT_BLOCKED\n at test")
    )
    release = AsyncMock()
    cdp = SimpleNamespace(
        session_id="session",
        page=SimpleNamespace(
            create_isolated_world=AsyncMock(
                return_value=SimpleNamespace(execution_context_id=1)
            )
        ),
        runtime=SimpleNamespace(
            call_function_on=AsyncMock(
                return_value=SimpleNamespace(exception_details=details)
            ),
            release_object=release,
        ),
        dom=SimpleNamespace(
            resolve_node=AsyncMock(
                return_value=SimpleNamespace(object=SimpleNamespace(object_id="owner"))
            )
        ),
    )
    parent = Frame("parent", cdp)
    frame = Frame("frame", cdp, parent=parent, owner_id=2)
    with pytest.raises(BrowserError, match="^ELEMENT_BLOCKED$"):
        if owner:
            await frame.run_on_owner(OWNER_SIZE)
        else:
            await frame.run(RESET)
    assert release.await_count == int(owner)


def test_unexpected_page_exception_does_not_expose_its_message():
    details = SimpleNamespace(
        exception=SimpleNamespace(description="Error: private value")
    )
    assert failure(RESET, details) == "reset failed in the page"


async def test_fake_tab_rejects_unknown_scripts():
    with pytest.raises(AssertionError, match="Unexpected fake script"):
        await FakeTab().run(RESET)


@pytest.mark.parametrize("by_value", [True, False])
async def test_script_undefined_result_is_none_or_preserves_handle(by_value):
    value = RemoteObject(type="undefined")
    frame, _ = _node_call(value)
    result = await frame.run(RESET, by_value=by_value)
    assert result is None if by_value else result is value


@pytest.mark.parametrize("by_value", [True, False])
async def test_node_calls_use_the_resolved_receiver_and_preserve_result_handles(
    by_value,
):
    value = RemoteObject(type="object", value=[80, 20], object_id="result")
    frame, cdp = _node_call(value)
    result = await frame.run_on_node(
        7, OWNER_SIZE, by_value=by_value, user_gesture=True
    )
    assert result == (80, 20) if by_value else result is value
    cdp.dom.resolve_node.assert_awaited_once_with(
        backend_node_id=7, execution_context_id=1
    )
    arguments = cdp.runtime.call_function_on.await_args.kwargs
    assert arguments["object_id"] == "receiver"
    assert arguments["execution_context_id"] is None
    assert arguments["return_by_value"] is by_value
    assert arguments["user_gesture"]
    cdp.runtime.release_object.assert_awaited_once_with(object_id="receiver")


@pytest.mark.parametrize(
    "error", [RuntimeError("disconnected"), asyncio.CancelledError()]
)
async def test_node_calls_release_the_receiver_on_failure_and_cancellation(error):
    frame, cdp = _node_call()
    cdp.runtime.call_function_on.side_effect = error
    with pytest.raises(type(error)):
        await frame.run_on_node(7, RESET)
    cdp.runtime.call_function_on.assert_awaited_once()
    cdp.runtime.release_object.assert_awaited_once_with(object_id="receiver")


@pytest.mark.parametrize("missing_handle", [False, True])
async def test_stale_nodes_fail_before_calling_the_script(missing_handle):
    frame, cdp = _node_call()
    if missing_handle:
        cdp.dom.resolve_node.return_value.object.object_id = None
    else:
        cdp.dom.resolve_node.side_effect = CDPCommandError(
            "DOM.resolveNode", -32000, "No node with given id found"
        )
    with pytest.raises(BrowserError, match="^STALE_ELEMENT$"):
        await frame.run_on_node(7, RESET)
    cdp.runtime.call_function_on.assert_not_awaited()
    cdp.runtime.release_object.assert_not_awaited()


def _node_call(value=None):
    cdp = SimpleNamespace(
        session_id="session",
        page=SimpleNamespace(
            create_isolated_world=AsyncMock(
                return_value=SimpleNamespace(execution_context_id=1)
            )
        ),
        dom=SimpleNamespace(
            resolve_node=AsyncMock(
                return_value=SimpleNamespace(
                    object=SimpleNamespace(object_id="receiver")
                )
            )
        ),
        runtime=SimpleNamespace(
            call_function_on=AsyncMock(
                return_value=SimpleNamespace(exception_details=None, result=value)
            ),
            release_object=AsyncMock(),
        ),
    )
    return Frame("frame", cdp), cdp
