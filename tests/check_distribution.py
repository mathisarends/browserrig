"""Install a built wheel in a clean environment and check its packaged API/assets."""

import argparse
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

_SMOKE = """
import asyncio
import importlib.metadata
from importlib.util import find_spec
from importlib.resources import files
from pathlib import Path

import browserrig
from browserrig import ActionKind, Browser, DownloadReceiving, FileTransfers, WorkspaceTools
from browserrig.files import FileSystem, LocalWorkspace
from harnessed import Agent, Session
from harnessed.plugins import Service
from harnessed.services import ToolRegistry
from harnessed.testing import ScriptedModel
from browserrig.scripts import CHOREOGRAPHY, CONTENT, ELEMENT, OVERLAY, SECRET_FIELD

assert callable(Session.append_message)
assert ActionKind.MOVE_MOUSE.value == 'move_mouse'
assert any(isinstance(plugin, FileTransfers) for plugin in browserrig.browser_plugins())
assert any(isinstance(plugin, DownloadReceiving) for plugin in browserrig.browser_plugins())
assert browserrig.__version__ == importlib.metadata.version('browserrig')
distribution = importlib.metadata.distribution('browserrig')
assert distribution.metadata['License-Expression']
assert any(str(path).endswith('.dist-info/licenses/LICENSE') for path in distribution.files)
assert set(browserrig.__all__) <= set(dir(browserrig))
assert Path(browserrig.__file__).is_relative_to(Path.cwd())
assert files('browserrig').joinpath('py.typed').is_file()
assert all(script.declaration for script in (CHOREOGRAPHY, CONTENT, ELEMENT, OVERLAY, SECRET_FIELD))
assert files('browserrig.choreography').joinpath('view.html').is_file()
assert files('browserrig.choreography').joinpath('view.css').is_file()


async def read_without_file_extras():
    # The base install reads text; richer formats point to the optional extra.
    async with FileSystem(LocalWorkspace('workspace')) as workspace:
        await workspace.write_file('notes.txt', 'hello')
        await workspace.write_file('table.csv', 'a,b')
        assert (await workspace.read_file('notes.txt')).text == 'hello'
        table = await workspace.read_file('table.csv')
        assert table.status == 'partial' and table.text == 'a,b'
        assert 'browserrig[files]' in table.limitations[0]
        agent = Agent(
            model=ScriptedModel([]),
            plugins=[Service(FileSystem, workspace), WorkspaceTools()],
        )
        async with agent.session() as session:
            assert Browser not in session.scope
            assert {tool.name for tool in session.scope[ToolRegistry].definitions} == {
                'list_files', 'read_file', 'write_file',
            }


assert find_spec('openpyxl') is None and find_spec('rapidocr') is None
asyncio.run(read_without_file_extras())
print('Installed wheel: public API, version, typing data, scripts and base file reading OK')
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
        path.relative_to(package.parent).as_posix()
        for path in package.rglob("*")
        if path.suffix in {".js", ".html", ".css"}
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
