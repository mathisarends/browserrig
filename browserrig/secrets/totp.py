import base64
import binascii
import hashlib
import hmac
import re
import struct
import time
from collections.abc import Callable

from browserrig.core import SecretError


class Totp:
    """RFC 6238 one-time codes; each use types the code that is valid at that moment.

    `seed` is base32 text or a callable returning it, e.g. `Totp(env("GITHUB_TOTP_SEED"))`.
    """

    __slots__ = ("_seed", "_digits", "_period", "_digest")

    def __init__(
        self,
        seed: str | Callable[[], str],
        *,
        digits: int = 6,
        period: int = 30,
        digest: str = "sha1",
    ) -> None:
        if (
            not 6 <= digits <= 10
            or period <= 0
            or digest not in {"sha1", "sha256", "sha512"}
        ):
            raise ValueError("Invalid TOTP settings")
        if isinstance(seed, str):
            _key(seed)
        self._seed = seed
        self._digits = digits
        self._period = period
        self._digest = digest

    def __repr__(self) -> str:
        return f"Totp(digits={self._digits}, period={self._period})"

    def __call__(self) -> str:
        return self.at(time.time())

    def at(self, timestamp: float) -> str:
        seed = self._seed if isinstance(self._seed, str) else self._seed()
        counter = struct.pack(">Q", int(timestamp // self._period))
        mac = hmac.new(_key(seed), counter, getattr(hashlib, self._digest)).digest()
        offset = mac[-1] & 0x0F
        code = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
        return f"{code % 10**self._digits:0{self._digits}d}"


def _key(seed: str) -> bytes:
    normalized = re.sub(r"[\s-]", "", seed).upper()
    try:
        return base64.b32decode(normalized + "=" * (-len(normalized) % 8))
    except (binascii.Error, ValueError):
        raise SecretError("TOTP seed is not valid base32") from None
