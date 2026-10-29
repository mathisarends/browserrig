import asyncio
import os
import shutil
import subprocess
from asyncio.subprocess import Process
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self

from .config import LaunchBrowser
from .errors import BrowserError


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


class ChromeProcess:
    """Own exactly one child browser and its temporary profile."""

    def __init__(self, options: LaunchBrowser) -> None:
        self.options = options
        self.process: Process | None = None
        self.profile: TemporaryDirectory[str] | None = None
        self.endpoint = ""

    async def __aenter__(self) -> Self:
        binary = _chrome_executable(self.options.executable)
        self.profile = TemporaryDirectory(prefix="browserrig-chrome-")
        flags = [
            binary,
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            f"--user-data-dir={self.profile.name}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--window-size={self.options.viewport.width},{self.options.viewport.height}",
        ]
        if self.options.headless:
            flags.append("--headless=new")
        flags.extend(self.options.arguments)
        flags.append("about:blank")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            active_port = Path(self.profile.name) / "DevToolsActivePort"
            async with asyncio.timeout(self.options.timeout):
                while True:
                    if self.process.returncode is not None:
                        raise BrowserError(
                            f"Chrome exited during startup ({self.process.returncode})"
                        )
                    if active_port.is_file():
                        lines = (await asyncio.to_thread(active_port.read_text)).splitlines()
                        if len(lines) >= 2 and lines[0].isdigit():
                            self.endpoint = f"ws://127.0.0.1:{lines[0]}{lines[1]}"
                            return self
                    await asyncio.sleep(0.05)
        except BaseException:
            await self.aclose()
            raise

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            try:
                async with asyncio.timeout(5):
                    await self.process.wait()
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
        if self.profile is not None:
            profile, self.profile = self.profile, None
            await asyncio.to_thread(profile.cleanup)
