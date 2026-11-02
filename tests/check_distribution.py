"""Install a built wheel in a clean environment and check its packaged API/assets."""

import argparse
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

_SMOKE = """
import importlib.metadata
from importlib.resources import files
from pathlib import Path

import browserrig
from browserrig.scripts import CONTENT, ELEMENT, SECRET_FIELD

assert browserrig.__version__ == importlib.metadata.version('browserrig')
distribution = importlib.metadata.distribution('browserrig')
assert distribution.metadata['License-Expression']
assert any(str(path).endswith('.dist-info/licenses/LICENSE') for path in distribution.files)
assert set(browserrig.__all__) <= set(dir(browserrig))
assert Path(browserrig.__file__).is_relative_to(Path.cwd())
assert files('browserrig').joinpath('py.typed').is_file()
assert all(script.declaration for script in (CONTENT, ELEMENT, SECRET_FIELD))
print('Installed wheel: public API, version, typing data and scripts OK')
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    wheels = list(args.dist.glob("browserrig-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected exactly one Browserrig wheel in {args.dist}")
    wheel = wheels[0].resolve()
    package = Path(__file__).resolve().parents[1] / "browserrig"
    assets = {
        path.relative_to(package.parent).as_posix() for path in package.rglob("*.js")
    }
    assets.add("browserrig/py.typed")
    with ZipFile(wheel) as archive:
        missing = assets - set(archive.namelist())
    if missing:
        raise ValueError(f"Wheel is missing package assets: {sorted(missing)}")

    with TemporaryDirectory(prefix="browserrig-wheel-check-") as directory:
        environment = Path(directory) / "venv"
        subprocess.run(
            ["uv", "venv", "--quiet", "--python", sys.executable, str(environment)],
            check=True,
            timeout=60,
        )
        python = environment / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        subprocess.run(
            ["uv", "pip", "install", "--quiet", "--python", str(python), str(wheel)],
            check=True,
            timeout=300,
        )
        subprocess.run(
            [str(python), "-I", "-c", _SMOKE], cwd=directory, check=True, timeout=60
        )


if __name__ == "__main__":
    main()
