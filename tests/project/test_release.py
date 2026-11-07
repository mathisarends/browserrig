from pathlib import Path

import pytest

from tests.check_release import check_release


@pytest.fixture(name="release_project")
def prepared_release_project(tmp_path: Path) -> Path:
    (tmp_path / "browserrig").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "browserrig"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    # A metadata check must not execute package imports or other module code.
    (tmp_path / "browserrig/__init__.py").write_text(
        'raise RuntimeError("Do not import")\n__version__ = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.1.0 (unreleased)\n\nInitial release.\n", encoding="utf-8"
    )
    return tmp_path


@pytest.mark.parametrize("tag", [None, "v0.1.0"])
def test_release_metadata_without_importing_package(release_project, tag):
    assert check_release(release_project, tag) == "0.1.0"


@pytest.mark.parametrize("tag", ["0.1.0", "v0.2.0", "v0.1.0-rc1"])
def test_release_rejects_mismatched_tags(release_project, tag):
    with pytest.raises(ValueError, match="Release tag must be v0.1.0"):
        check_release(release_project, tag)


def test_release_rejects_inconsistent_package_version(release_project):
    (release_project / "browserrig/__init__.py").write_text(
        '__version__ = "0.2.0"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="must agree"):
        check_release(release_project, "v0.1.0")


def test_release_rejects_missing_notes_for_exact_version(release_project):
    (release_project / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.1.01\n\nDifferent release.\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="release notes for 0.1.0"):
        check_release(release_project, "v0.1.0")
