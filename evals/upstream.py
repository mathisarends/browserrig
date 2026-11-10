"""Run the pinned upstream tools in their own locked Python environment."""

import asyncio
import os
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).with_name("evaluator")


async def invoke(
    *arguments: str,
    log: Path,
    timeout: float = 180,
    check: bool = True,
) -> int:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("Install uv to run the locked WebArena evaluator")
    return await command(
        uv,
        "run",
        "--project",
        str(PROJECT),
        "--locked",
        "--no-dev",
        "--python",
        sys.executable,
        "webarena-verified",
        *arguments,
        log=log,
        timeout=timeout,
        check=check,
    )


async def command(
    *arguments: str, log: Path, timeout: float = 180, check: bool = True
) -> int:
    """Capture diagnostics and reap the subprocess on timeout or cancellation."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as output:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=output,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        try:
            async with asyncio.timeout(timeout):
                code = await process.wait()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    if check and code:
        raise RuntimeError(f"{arguments[0]} exited with {code}; see {log}")
    return code
