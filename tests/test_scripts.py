import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from browserrig.browser.tab import Frame
from browserrig.core.errors import BrowserError
from browserrig.scripts import OWNER_SIZE, RESET, ScriptError, failure
from tests.fakes import FakeTab

_ROOT = Path(__file__).resolve().parents[1] / "browserrig"
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
    for path in _SCRIPTS.glob("*.js"):
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
