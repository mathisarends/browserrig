"""Guard what smelt cannot express; package boundaries live in smelt.yml."""

import ast
from pathlib import Path


def test_tools_do_not_reach_into_cdp_sessions():
    paths = sorted(
        (Path(__file__).resolve().parents[2] / "browserrig" / "tools").glob("*.py")
    )
    assert paths
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                assert node.attr != "cdp", (path.name, node.lineno)
