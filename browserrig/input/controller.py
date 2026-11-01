from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace

from browserrig.events import InputEvent

from .keyboard import Keyboard
from .mouse import Mouse
from .presenter import Presenter, Unseen
from .target import Focus, InputTarget


class Input:
    """The browser's mouse and keyboard, aimed at whichever tab has focus.

    It correlates every input event with the action that caused it, and reports input
    through the installed `Presenter`.
    """

    def __init__(self, focus: Focus) -> None:
        self._action_id = ""
        self._presenter: Presenter = Unseen()
        self.mouse = Mouse(focus, emit=self._emit, presenter=self.presenter)
        self.keyboard = Keyboard(focus, emit=self._emit, presenter=self.presenter)

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

    def presenter(self) -> Presenter:
        return self._presenter

    def present(self, presenter: Presenter) -> Callable[[], None]:
        """Pace and report input through `presenter` until the returned callback runs."""
        previous, self._presenter = self._presenter, presenter

        def restore() -> None:
            if self._presenter is presenter:
                self._presenter = previous

        return restore

    async def _emit(self, target: InputTarget, event: InputEvent) -> None:
        await self._presenter.show(target, replace(event, action_id=self._action_id))
