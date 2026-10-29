"""Guard the dependency boundaries established by the review."""

import ast
from pathlib import Path


def test_core_has_no_dependencies_on_browser_services():
    root = Path(__file__).resolve().parents[1] / "browserrig" / "core"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("browserrig.") or node.module.startswith(
                    "browserrig.core."
                ), (path.name, node.module)
