"""Validate release metadata without importing Browserrig or its dependencies."""

import argparse
import ast
import re
import tomllib
from pathlib import Path


def check_release(root: Path, tag: str | None = None) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    source = ast.parse((root / "browserrig/__init__.py").read_text(encoding="utf-8"))
    versions = [
        ast.literal_eval(node.value)
        for node in source.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
    ]
    if versions != [version]:
        raise ValueError("pyproject.toml and browserrig.__version__ must agree")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Release tag must be v{version}, got {tag!r}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(
        rf"^## {re.escape(version)}(?:[ \t].*)?$", changelog, re.MULTILINE
    ):
        raise ValueError(f"CHANGELOG.md must contain release notes for {version}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Exact release tag, for example v0.1.0")
    args = parser.parse_args()
    try:
        version = check_release(Path(__file__).resolve().parents[1], args.tag)
    except ValueError as error:
        parser.error(str(error))
    print(f"Release metadata OK: browserrig {version}")


if __name__ == "__main__":
    main()
