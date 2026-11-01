import asyncio
import errno
import os
import shutil
import subprocess
from asyncio.subprocess import Process
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

from browserrig.core import BrowserError

from .config import LaunchBrowser


class ChromeProcess:
    def __init__(self, options: LaunchBrowser) -> None:
        self._options = options
        self._process: Process | None = None
        self._profile: TemporaryDirectory[str] | None = None
        self.endpoint = ""

    async def __aenter__(self) -> Self:
        binary = _chrome_executable(self._options.executable)
        # The profile outlives this method; __aexit__ removes it with the process.
        self._profile = TemporaryDirectory(  # pylint: disable=consider-using-with
            prefix="browserrig-chrome-"
        )
        flags = [
            binary,
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            f"--user-data-dir={self._profile.name}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-size={self._options.viewport.width},{self._options.viewport.height}",
        ]
        if self._options.headless:
            flags.append("--headless=new")
        flags.extend(self._options.arguments)
        flags.append("about:blank")
        try:
            self._process = await asyncio.create_subprocess_exec(
                *flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            active_port = Path(self._profile.name) / "DevToolsActivePort"
            async with asyncio.timeout(self._options.timeout):
                while True:
                    if self._process.returncode is not None:
                        raise BrowserError(
                            f"Chrome exited during startup ({self._process.returncode})"
                        )
                    endpoint = await asyncio.to_thread(_active_endpoint, active_port)
                    if endpoint is not None:
                        self.endpoint = endpoint
                        return self
                    await asyncio.sleep(0.05)
        except (Exception, asyncio.CancelledError):
            await self.aclose()
            raise

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                async with asyncio.timeout(5):
                    await self._process.wait()
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None
        if self._profile is not None:
            profile = self._profile
            deadline = asyncio.get_running_loop().time() + 10
            while True:
                try:
                    await asyncio.to_thread(profile.cleanup)
                    self._profile = None
                    break
                except OSError as error:
                    # Chrome helpers can retain handles or repopulate profile
                    # directories briefly after the browser parent exits.
                    if (
                        not isinstance(error, PermissionError)
                        and error.errno != errno.ENOTEMPTY
                    ):
                        raise
                    if asyncio.get_running_loop().time() >= deadline:
                        # A leftover temp profile is not worth failing the session for.
                        await asyncio.to_thread(
                            shutil.rmtree, profile.name, ignore_errors=True
                        )
                        self._profile = None
                        break
                    await asyncio.sleep(0.1)


def _chrome_executable(explicit: Path | None = None) -> str:
    candidates = [explicit, os.environ.get("BROWSERRIG_CHROME")]
    candidates.extend(
        shutil.which(name) for name in ("chromium", "chromium-browser", "google-chrome")
    )
    for root in (
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ):
        if root:
            candidates.extend(
                Path(root) / part
                for part in (
                    "Google/Chrome/Application/chrome.exe",
                    "Microsoft/Edge/Application/msedge.exe",
                )
            )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise BrowserError(
        "Chrome was not found; set LaunchBrowser(executable=...) or BROWSERRIG_CHROME"
    )


def _active_endpoint(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError):
        # Chrome can still hold the port file while publishing its endpoint on Windows.
        return None
    if (
        len(lines) >= 2
        and lines[0].isdigit()
        and lines[1].startswith("/devtools/browser/")
    ):
        return f"ws://127.0.0.1:{lines[0]}{lines[1]}"
    return None
