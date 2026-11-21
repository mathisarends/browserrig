"""Immutable generation tokens for invalidating cached browser state."""

from collections.abc import Hashable
from dataclasses import dataclass
from typing import Annotated

from pydantic import BeforeValidator


def _freeze_arrays(value: object) -> object:
    if isinstance(value, list | tuple):
        return tuple(_freeze_arrays(item) for item in value)
    return value


type _GenerationKey = Annotated[Hashable, BeforeValidator(_freeze_arrays)]


@dataclass(frozen=True, slots=True)
class Generation:
    """Identity of what an observation shows.

    A state change makes its targets stale. A layout change makes its coordinates stale.
    Use JSON scalars and tuples of those values when snapshots need JSON round trips.
    """

    state: _GenerationKey
    layout: _GenerationKey | None = None
