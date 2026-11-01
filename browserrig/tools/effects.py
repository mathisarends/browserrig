from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Effect:
    text: str
    prepared_scroll: bool = False
    break_chain: bool = False
