from enum import Enum, auto


class Phase(Enum):
    WORKING = auto()
    # The last step that can still end with a final answer: only done may run.
    CLOSING = auto()
    # done succeeded; the next response is the final answer.
    FINISHED = auto()


DENIALS = {
    Phase.CLOSING: (
        "Only {tool} is available now: the step limit leaves room for nothing but "
        "{tool} and the final answer."
    ),
    Phase.FINISHED: (
        "Browser work has ended. Return the final answer without application tools."
    ),
}


def permits(phase: Phase, *, is_done: bool) -> bool:
    return phase is Phase.WORKING or (phase is Phase.CLOSING and is_done)


def closing_step(last_tool_step: int) -> int | None:
    """The first step from which only done may run, or None if no step leaves room.

    Leave one step after done for the final answer within the work budget.
    """
    step = last_tool_step - 1
    return step if step >= 1 else None
