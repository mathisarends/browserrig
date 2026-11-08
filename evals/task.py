from dataclasses import dataclass, field

from browserrig import Secret

from .checks import Answer, Check, Probe

STAGES = ("practice", "reference", "wild")


@dataclass(frozen=True, eq=False)
class Task:
    """One mission: where it starts, what to do, and the milestones that prove it."""

    name: str
    stage: str
    url: str
    prompt: str
    checks: tuple[Check, ...]
    max_steps: int = 40
    tags: tuple[str, ...] = ()
    # Credentials the agent types as {{secret:NAME}}.
    secrets: dict[str, Secret] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError(f"{self.name}: unknown stage {self.stage!r}")
        if not self.checks:
            raise ValueError(f"{self.name}: a task needs at least one check")

    @property
    def probes(self) -> tuple[str, ...]:
        """JavaScript to read from the active tab before the browser closes."""
        return tuple(
            dict.fromkeys(c.expression for c in self.checks if isinstance(c, Probe))
        )


def answer(*patterns, label: str = "answer") -> Answer:
    """The final answer matches every pattern."""
    return Answer(label, patterns)
