from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator

from browserrig.core import Options, TargetId

from .process import ChromeProcess


class Viewport(Options):
    width: int = Field(default=1280, ge=320, le=7680)
    height: int = Field(default=800, ge=240, le=4320)
    scale: float = Field(default=1, gt=0, le=4)


@dataclass(frozen=True, slots=True)
class CdpEndpoint:
    """Where to reach a browser over CDP, and the headers that request needs."""

    url: str
    headers: dict[str, str]


class Launch(Options):
    """Start a Chrome process that browserrig owns and stops again."""

    owns_process: ClassVar[bool] = True
    # A launched browser always starts in a fresh tab of its own context.
    target_id: ClassVar[None] = None
    executable: Path | None = None
    headless: bool = True
    url: str = "about:blank"
    viewport: Viewport = Viewport()
    timeout: float = Field(default=20, gt=0, le=120)
    arguments: tuple[str, ...] = ()
    download_directory: str | None = None

    @field_validator("arguments")
    @classmethod
    def _owned_arguments(cls, arguments: tuple[str, ...]) -> tuple[str, ...]:
        reserved = ("--remote-debugging", "--user-data-dir", "--headless")
        if any(
            arg.startswith(reserved) or not arg.startswith("--") for arg in arguments
        ):
            raise ValueError(
                "Arguments must be flags and cannot override process ownership"
            )
        return arguments

    def process(self) -> ChromeProcess:
        """The Chrome process these options describe, not started yet."""
        flags = [f"--window-size={self.viewport.width},{self.viewport.height}"]
        if self.headless:
            flags.append("--headless=new")
        return ChromeProcess(
            executable=self.executable,
            flags=(*flags, *self.arguments),
            timeout=self.timeout,
        )

    async def cdp_endpoint(self, stack: AsyncExitStack) -> CdpEndpoint:
        """Start Chrome and return its endpoint; closing `stack` stops the process."""
        process = await stack.enter_async_context(self.process())
        return CdpEndpoint(url=process.endpoint, headers={})


class Connect(Options):
    """Attach to a browser that runs elsewhere; browserrig never stops it."""

    owns_process: ClassVar[bool] = False
    endpoint: SecretStr
    target_id: TargetId | None = None
    url: str = "about:blank"
    timeout: float = Field(default=20, gt=0, le=120)
    headers: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    viewport: Viewport | None = None
    download_directory: str | None = None

    @model_validator(mode="after")
    def _target_ownership(self) -> Self:
        if self.target_id and (self.url != "about:blank" or self.download_directory):
            raise ValueError(
                "An attached target keeps its URL and browser-wide download policy"
            )
        return self

    @field_validator("endpoint")
    @classmethod
    def _browser_endpoint(cls, endpoint: SecretStr) -> SecretStr:
        parsed = urlsplit(endpoint.get_secret_value())
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
            raise ValueError(
                "Expected an HTTP(S) discovery endpoint or browser WebSocket"
            )
        if parsed.scheme in {"ws", "wss"} and "/devtools/page/" in parsed.path:
            raise ValueError(
                "A browser WebSocket is required; a page WebSocket cannot manage tabs"
            )
        return endpoint

    async def cdp_endpoint(self, _stack: AsyncExitStack) -> CdpEndpoint:
        """Return the configured endpoint and its request headers."""
        headers = {key: value.get_secret_value() for key, value in self.headers.items()}
        return CdpEndpoint(url=self.endpoint.get_secret_value(), headers=headers)


type BrowserOptions = Launch | Connect
