from harnessed import Plugin
from harnessed.events import StepStartedEvent
from harnessed.hooks import Next, PrepareRequest
from harnessed.kernel import hook, needs, observes
from harnessed.models import ModelRequest, UserMessage
from harnessed.plugins import FinalStepPolicy
from harnessed.sessions import SessionContext

from .plugin import Done


class StepBudgetHints(Plugin):
    """Tell the model its step limit and warn when work needs to wrap up.

    The warning threshold counts work steps including the current step. Set
    show_every_step to also show the count on intermediate work requests.
    """

    _session = needs(SessionContext)
    _done = observes(Done)

    def __init__(
        self, *, warn_at_remaining: int = 3, show_every_step: bool = False
    ) -> None:
        super().__init__()
        if (
            isinstance(warn_at_remaining, bool)
            or not isinstance(warn_at_remaining, int)
            or warn_at_remaining < 1
        ):
            raise ValueError("warn_at_remaining must be a positive integer")
        self._warn_at_remaining = warn_at_remaining
        self._show_every_step = show_every_step

    @hook(PrepareRequest)
    async def _prepare(
        self, event: PrepareRequest, next_: Next[ModelRequest]
    ) -> ModelRequest:
        request = await next_()
        if event.session.log is not self._session.log:
            return request
        turn = event.session.log.current_turn()
        started = event.session.last(StepStartedEvent)
        limit = turn.start.limits.max_steps
        if started is None or started.turn_id != turn.id or limit is None:
            return request
        summarize = turn.start.final_step is FinalStepPolicy.SUMMARIZE
        hint = self._hint(started.step, limit, summarize=summarize)
        if hint is None:
            return request
        return request.append_message(UserMessage(hint))

    def _hint(self, step: int, limit: int, *, summarize: bool) -> str | None:
        status = f"Model step {step} of {limit}."
        done = self._done
        remaining = done.remaining_work_steps if done is not None else limit - step
        if remaining == 0:
            if done is not None or summarize:
                return None
            return f"{status} Return the final answer now. Report any unfinished work."
        if remaining <= self._warn_at_remaining:
            unit = "step" if remaining == 1 else "steps"
            return (
                f"{status} {remaining} work {unit} left, including this step. "
                "Prioritize the most important remaining check and prepare to finish."
            )
        if step == 1:
            return f"{status} Finish as soon as the task is complete."
        return status if self._show_every_step else None
