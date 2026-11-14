from dataclasses import fields
from typing import get_args, get_type_hints

import pytest
from harnessed.events import EventRegistry
from pydantic import TypeAdapter

from browserrig import events
from browserrig.choreography import (
    SCENE_EVENTS,
    CaptureRegion,
    DomScrolledEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from browserrig.core import ActionKind


def test_enum_tags_and_registry_roundtrip():
    registry = EventRegistry(
        events.BROWSER_EVENTS
        + events.ACTION_EVENTS
        + events.READINESS_EVENTS
        + events.NUDGE_EVENTS
        + events.SECRET_EVENTS
        + events.HANDOFF_EVENTS
        + events.ACTIVITY_EVENTS
        + events.FILE_EVENTS
        + events.UPLOAD_EVENTS
        + (events.ObservationCapturedEvent,)
    )
    event = events.ConnectedEvent(owned_process=True, browser_id="browser-1")
    restored = registry.decode(registry.encode(event))
    assert restored == event
    assert restored.type is events.EventKind.CONNECTED
    assert restored.type == "browser.connected"


def test_action_page_state_roundtrips_as_a_typed_nested_value():
    registry = EventRegistry(events.ACTION_EVENTS)
    event = events.ActionFinishedEvent(
        action_id="action",
        kind="click",
        after_url="https://example.org/",
        before=events.PageState(
            url="https://example.org/", document_id="document", scroll_y=100
        ),
    )
    restored = registry.decode(registry.encode(event))
    assert restored == event
    assert isinstance(restored.before, events.PageState)


def test_dom_scroll_receipt_roundtrips_as_transient_with_local_offsets():
    adapter = TypeAdapter(DomScrolledEvent)
    event = DomScrolledEvent(
        frame_id="frame",
        frame_document_id="frame-document",
        ref="ref",
        before=(12.5, 80),
        after=(12.5, 300),
        blocked=True,
        target_id="tab",
        document_id="document",
        action_id="action",
    )
    restored = adapter.validate_json(adapter.dump_json(event))
    EventRegistry(SCENE_EVENTS).validate(restored)
    assert restored == event
    assert isinstance(restored, events.LiveEvent)
    assert not isinstance(restored, events.BrowserEvent)


def test_canvas_work_contract_roundtrips_with_typed_geometry_and_phase():
    adapter = TypeAdapter(WorkPresentedEvent)
    event = WorkPresentedEvent(
        work_id="capture",
        call_id="call",
        kind=ActionKind.SCREENSHOT,
        title="Screenshot",
        phase=WorkPhase.COMPLETED,
        region=CaptureRegion(x=10, y=20, width=100, height=80),
        target_id="tab",
        document_id="document",
    )
    restored = adapter.validate_json(adapter.dump_json(event))
    EventRegistry(SCENE_EVENTS).validate(restored)
    assert restored == event
    assert restored.phase is WorkPhase.COMPLETED and isinstance(
        restored.region, CaptureRegion
    )


@pytest.mark.parametrize(
    "kind",
    events.BROWSER_EVENTS
    + events.ACTION_EVENTS
    + events.READINESS_EVENTS
    + events.NUDGE_EVENTS
    + events.SECRET_EVENTS
    + events.HANDOFF_EVENTS
    + events.ACTIVITY_EVENTS
    + events.INPUT_EVENTS
    + events.TAB_STRIP_EVENTS
    + SCENE_EVENTS
    + events.FILE_EVENTS
    + events.UPLOAD_EVENTS
    + (events.ObservationCapturedEvent,),
)
def test_each_tag_has_one_literal_enum_and_matching_default(kind):
    values = get_args(get_type_hints(kind)["type"])
    assert len(values) == 1
    assert isinstance(values[0], events.EventKind)
    assert (
        next(field.default for field in fields(kind) if field.name == "type")
        is values[0]
    )
