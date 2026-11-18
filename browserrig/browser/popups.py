import asyncio
from contextlib import AsyncExitStack, suppress

from cdpify import CDPCommandError, CdpSession, EventSubscription
from cdpify.domains.runtime import ExecutionContextCreatedEvent

from browserrig.scripts import SINGLE_TAB, SingleTabArgs

SINGLE_TAB_BLOCKED = "browserrigSingleTabBlocked"


class SingleTabSession:
    """Install same-context navigation before page scripts, undoing it at disconnect."""

    def __init__(self, cdp: CdpSession) -> None:
        self._cdp = cdp
        self._contexts: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._script = ""

    async def start(self, stack: AsyncExitStack) -> None:
        subscription = await stack.enter_async_context(
            self._cdp.listen(ExecutionContextCreatedEvent)
        )
        self._task = asyncio.create_task(self._watch(subscription))
        stack.push_async_callback(self._close)
        await self._cdp.runtime.add_binding(name=SINGLE_TAB_BLOCKED)
        installed = await self._cdp.page.add_script_to_evaluate_on_new_document(
            source=self._source(enabled=True), run_immediately=True
        )
        self._script = installed.identifier

    async def _watch(
        self, subscription: EventSubscription[ExecutionContextCreatedEvent]
    ) -> None:
        async for event in subscription:
            context = event.context
            if context.aux_data is not None and context.aux_data.get("isDefault"):
                self._contexts.add(context.unique_id)

    async def _close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        for context in self._contexts:
            # Documents may have navigated or closed since their context was reported.
            with suppress(CDPCommandError):
                await self._cdp.runtime.evaluate(
                    expression=self._source(enabled=False), unique_context_id=context
                )
        if self._script:
            with suppress(CDPCommandError):
                await self._cdp.page.remove_script_to_evaluate_on_new_document(
                    identifier=self._script
                )
        with suppress(CDPCommandError):
            await self._cdp.runtime.remove_binding(name=SINGLE_TAB_BLOCKED)

    @staticmethod
    def _source(*, enabled: bool) -> str:
        args = SingleTabArgs(enabled=enabled, binding=SINGLE_TAB_BLOCKED)
        return f"({SINGLE_TAB.declaration})({args.model_dump_json(by_alias=True)})"
