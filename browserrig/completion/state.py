from dataclasses import dataclass


@dataclass
class CompletionState:
    step: int = 0
    # First step from which only done may run; None when no step leaves room for it.
    closing_step: int | None = None
