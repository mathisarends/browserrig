"""Guard the dependency boundaries established by the review."""

import ast
from pathlib import Path

import pytest


def test_core_has_no_dependencies_on_browser_services():
    root = Path(__file__).resolve().parents[1] / "browserrig" / "core"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("browserrig.") or node.module.startswith(
                    "browserrig.core."
                ), (path.name, node.module)


def test_tools_do_not_use_cdp():
    root = Path(__file__).resolve().parents[1] / "browserrig" / "tools"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("cdpify"), path.name
            if isinstance(node, ast.Attribute):
                assert node.attr != "cdp", (path.name, node.lineno)


@pytest.mark.parametrize(
    "package, forbidden",
    [
        ("input", ("browserrig.browser",)),
        ("files", ("browserrig.browser",)),
        ("readiness", ("browserrig.observation",)),
        ("scripts", ("browserrig.browser", "browserrig.observation", "browserrig.readiness")),
    ],
)
def test_service_packages_respect_dependency_boundaries(package, forbidden):
    root = Path(__file__).resolve().parents[1] / "browserrig" / package
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), (path.name, node.module)
