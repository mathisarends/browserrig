from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator

from browserrig.core.options import Options


class Viewport(Options):
    width: int = Field(default=1280, ge=320, le=7680)
    height: int = Field(default=800, ge=240, le=4320)
    scale: float = Field(default=1, gt=0, le=4)


class BrowserKind(StrEnum):
    LAUNCH = "launch"
    CONNECT = "connect"


class LaunchBrowser(Options):
    kind: Literal[BrowserKind.LAUNCH] = BrowserKind.LAUNCH
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


class ConnectBrowser(Options):
    kind: Literal[BrowserKind.CONNECT] = BrowserKind.CONNECT
    endpoint: SecretStr
    target_id: str | None = None
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


type BrowserOptions = Annotated[
    LaunchBrowser | ConnectBrowser, Field(discriminator="kind")
]
