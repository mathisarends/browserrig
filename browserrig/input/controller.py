from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace

from browserrig.events import InputEvent

from .keyboard import Keyboard
from .motor import Instant, Motor
from .mouse import Mouse
from .presenter import Presenter, Unseen
from .target import Focus, InputTarget


class Input:
    """The browser's mouse and keyboard, aimed at whichever tab has focus.

    The installed `Motor` decides how input is performed and the installed `Presenter`
    what viewers see of it. Every input event is correlated with the action that caused it.
    """

    def __init__(self, focus: Focus) -> None:
        self._action_id = ""
        self._default_motor: Motor = Instant()
        self._default_presenter: Presenter = Unseen()
        self._motors: dict[object, Motor] = {}
        self._presenters: dict[object, Presenter] = {}
        self.mouse = Mouse(
            focus,
            emit=self._emit,
            motor=self.motor,
            presenter=self.presenter,
            action_id=lambda: self._action_id,
        )
        self.keyboard = Keyboard(focus, emit=self._emit, motor=self.motor)

    @property
    def action_id(self) -> str:
        return self._action_id

    @contextmanager
    def action(self, action_id: str):
        previous, self._action_id = self._action_id, action_id
        try:
            yield
        finally:
            self._action_id = previous

    def motor(self) -> Motor:
        return next(reversed(self._motors.values()), self._default_motor)

    def pace(self, motor: Motor) -> Callable[[], None]:
        """Override the motor; the idempotent undo may run in any order."""
        token = object()
        self._motors[token] = motor

        def restore() -> None:
            self._motors.pop(token, None)

        return restore

    def presenter(self) -> Presenter:
        return next(reversed(self._presenters.values()), self._default_presenter)

    def present(self, presenter: Presenter) -> Callable[[], None]:
        """Override presentation; the idempotent undo may run in any order."""
        token = object()
        self._presenters[token] = presenter

        def restore() -> None:
            self._presenters.pop(token, None)

        return restore

    async def _emit(self, target: InputTarget, event: InputEvent) -> None:
        await self.presenter().show(target, replace(event, action_id=self._action_id))
