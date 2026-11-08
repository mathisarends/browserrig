import asyncio
from time import monotonic

import pytest
from cdpify.domains.network import (
    LoadingFailedEvent,
    LoadingFinishedEvent,
    RequestWillBeSentEvent,
    ResourceType,
)

from browserrig.browser.network import NetworkActivity
from browserrig.core import ReadinessPhase
from browserrig.readiness import NetworkQuiet, ReadinessOptions, wait_for_page
from tests.fakes import FakeTab

_OPTIONS = ReadinessOptions(
    timeout=5,
    navigation_min_ms=0,
    action_min_ms=0,
    quiet_ms=0,
    poll_interval=0.005,
)
_POLICY = NetworkQuiet(reaction_ms=100, chain_ms=50, settle_ms=20, extra_ms=400)


def _sent(rid, kind=ResourceType.FETCH):
    return RequestWillBeSentEvent(
        request_id=rid,
        loader_id="loader",
        document_url="https://example.org/",
        request=None,
        timestamp=0,
        wall_time=0,
        initiator=None,
        redirect_has_extra_info=False,
        type=kind,
    )


def _finished(rid):
    return LoadingFinishedEvent(request_id=rid, timestamp=0, encoded_data_length=0)


def _failed(rid):
    return LoadingFailedEvent(
        request_id=rid, timestamp=0, type=ResourceType.FETCH, error_text="aborted"
    )


async def _wait(tab, phase=ReadinessPhase.AFTER_ACTION, since=None, options=_OPTIONS):
    started = monotonic()
    report = await wait_for_page(
        tab, options=options, phase=phase, policy=_POLICY, since=since
    )
    assert report.status == "ready"
    return monotonic() - started


async def _later(seconds, *events, tab):
    await asyncio.sleep(seconds)
    for event in events:
        tab.network.handle(event)


async def test_a_request_the_action_started_holds_readiness_until_it_is_applied():
    tab = FakeTab()
    since = monotonic()
    tab.network.handle(_sent("search"))
    finish = asyncio.create_task(_later(0.15, _finished("search"), tab=tab))
    assert await _wait(tab, since=since) >= 0.15 + 0.02
    await asyncio.wait_for(finish, 1)


async def test_a_failed_request_releases_readiness_like_a_finished_one():
    tab = FakeTab()
    since = monotonic()
    tab.network.handle(_sent("search"))
    finish = asyncio.create_task(_later(0.05, _failed("search"), tab=tab))
    assert await _wait(tab, since=since) < 0.3
    await asyncio.wait_for(finish, 1)


async def test_a_request_starting_within_the_reaction_floor_still_counts():
    """The action floor gives a debounced handler time to start its request."""
    tab = FakeTab()
    late = asyncio.create_task(_later(0.03, _sent("debounced"), tab=tab))
    finish = asyncio.create_task(_later(0.2, _finished("debounced"), tab=tab))
    floor = _OPTIONS.model_copy(update={"action_min_ms": 60})
    assert await _wait(tab, options=floor) >= 0.2
    await asyncio.wait_for(asyncio.gather(late, finish), 1)


async def test_a_request_chain_is_followed_but_a_later_poll_is_not():
    tab = FakeTab()
    since = monotonic()
    tab.network.handle(_sent("first"))
    steps = asyncio.create_task(
        _later(0.05, _finished("first"), _sent("second"), tab=tab)
    )
    finish = asyncio.create_task(_later(0.15, _finished("second"), tab=tab))
    elapsed = await _wait(tab, since=since)
    assert 0.15 <= elapsed < 0.4
    await asyncio.wait_for(asyncio.gather(steps, finish), 1)


async def test_requests_open_before_the_action_never_count():
    """Long polls and streams the page held open do not hold readiness."""
    tab = FakeTab()
    tab.network.handle(_sent("long-poll"))
    await asyncio.sleep(0.01)
    assert await _wait(tab, since=monotonic()) < 0.1


async def test_background_polling_outside_the_reaction_window_never_counts():
    tab = FakeTab()

    async def poll():
        for index in range(100):
            await asyncio.sleep(0.15)
            tab.network.handle(_sent(f"poll-{index}"))

    poller = asyncio.create_task(poll())
    try:
        assert await _wait(tab) < 0.15
    finally:
        poller.cancel()


@pytest.mark.parametrize(
    "kind",
    [
        ResourceType.WEB_SOCKET,
        ResourceType.EVENT_SOURCE,
        ResourceType.PING,
        ResourceType.IMAGE,
        ResourceType.MEDIA,
    ],
)
async def test_sockets_streams_beacons_and_media_are_not_recorded(kind):
    tab = FakeTab()
    since = monotonic()
    tab.network.handle(_sent("open", kind))
    assert not tab.network.since(since)
    assert await _wait(tab, since=since) < 0.1


async def test_a_request_that_never_finishes_delays_readiness_by_at_most_extra_ms():
    tab = FakeTab()
    since = monotonic()
    tab.network.handle(_sent("stream"))
    elapsed = await _wait(tab, since=since)
    assert 0.4 <= elapsed < 0.6


async def test_a_page_that_keeps_requesting_is_bounded_by_extra_ms_too():
    tab = FakeTab()

    async def chatter():
        for index in range(1000):
            tab.network.handle(_sent(f"r{index}"))
            await asyncio.sleep(0.01)
            tab.network.handle(_finished(f"r{index}"))

    noise = asyncio.create_task(chatter())
    try:
        elapsed = await _wait(tab)
    finally:
        noise.cancel()
    assert 0.4 <= elapsed < 0.6


@pytest.mark.parametrize("phase", [ReadinessPhase.OBSERVATION, ReadinessPhase.ACTION])
async def test_waits_we_did_not_cause_ignore_the_network(phase):
    tab = FakeTab()
    since = monotonic()
    tab.network.handle(_sent("unrelated"))
    assert await _wait(tab, phase=phase, since=since) < 0.1


def test_a_redirect_keeps_the_start_of_the_original_request():
    network = NetworkActivity()
    network.handle(_sent("doc", ResourceType.DOCUMENT))
    (first,) = network.since(0)
    network.handle(_sent("doc", ResourceType.DOCUMENT))
    network.handle(_finished("doc"))
    (request,) = network.since(0)
    assert request.started == first.started and request.finished is not None
