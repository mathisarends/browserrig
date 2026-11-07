from enum import Enum, auto


class Phase(Enum):
    WORKING = auto()
    # The last step that can still end with a final answer: only done may run.
    CLOSING = auto()
    # done succeeded; the next response is the final answer.
    FINISHED = auto()


# The single gate for what each phase may call; None permits every tool.
# Tools stay declared in every request so the prompt cache survives phase changes;
# the plugin's policy and execution hooks enforce this table instead.
PERMITTED: dict[Phase, frozenset[str] | None] = {
    Phase.WORKING: None,
    Phase.CLOSING: frozenset({"done"}),
    Phase.FINISHED: frozenset(),
}

DENIALS = {
    Phase.CLOSING: (
        "Only done is available now: the step limit leaves room for nothing but done "
        "and the final answer."
    ),
    Phase.FINISHED: (
        "Browser work has ended. Return the final answer without application tools."
    ),
}


def permits(phase: Phase, tool: str) -> bool:
    permitted = PERMITTED[phase]
    return permitted is None or tool in permitted


def closing_step(max_steps: int, *, summarize: bool) -> int | None:
    """The first step from which only done may run, or None if no step leaves room.

    done needs one step and the final answer another; a reserved summary takes one more.
    """
    step = max_steps - (2 if summarize else 1)
    return step if step >= 1 else None
