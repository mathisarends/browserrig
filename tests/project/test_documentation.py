"""Keep documented Browserrig imports aligned with the shipped public API."""

import ast
import importlib
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "path", [Path("README.md"), *sorted(Path("docs").glob("*.md"))], ids=str
)
def test_documented_browserrig_imports_exist(path):
    source = (_ROOT / path).read_text(encoding="utf-8")
    missing = []
    for block in re.finditer(r"```python\s*\n(.*?)```", source, re.DOTALL):
        try:
            tree = ast.parse(block.group(1))
        except SyntaxError:
            # Some examples intentionally show fragments rather than complete programs.
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "browserrig"
            ):
                module = importlib.import_module(node.module)
                for name in node.names:
                    if not hasattr(module, name.name):
                        missing.append((node.module, name.name))
    assert missing == [], path
