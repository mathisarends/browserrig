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
    missing = [
        (module, name)
        for module, name in _browserrig_imports(source)
        if not hasattr(importlib.import_module(module), name)
    ]
    assert not missing, path


def _browserrig_imports(source):
    for block in re.finditer(r"```python\s*\n(.*?)```", source, re.DOTALL):
        try:
            tree = ast.parse(block.group(1))
        except SyntaxError:
            # Some examples intentionally show fragments rather than complete programs.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not (
                node.module or ""
            ).startswith("browserrig"):
                continue
            for name in node.names:
                yield node.module, name.name
