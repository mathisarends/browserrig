from dataclasses import fields
from typing import get_args, get_type_hints

import pytest
from harnessed.events import EventRegistry
from pydantic import TypeAdapter

from browserrig import events
from browserrig.choreography import (
    SCENE_EVENTS,
    CaptureRegion,
    ElementScrolledEvent,
    PageScrolledEvent,
    WorkPhase,
    WorkPresentedEvent,
)
from browserrig.core import ActionKind, ViewportSize


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


@pytest.mark.parametrize(
    "kind, extra", [(PageScrolledEvent, {}), (ElementScrolledEvent, {"ref": "ref"})]
)
def test_scroll_receipt_roundtrips_with_public_tab_id_and_measured_deltas(kind, extra):
    adapter = TypeAdapter(kind)
    event = kind(
        tab_id="tab",
        document_id="document",
        action_id="action",
        delta_x=-12.5,
        delta_y=220,
        **extra,
    )
    payload = adapter.dump_json(event)
    restored = adapter.validate_json(payload)
    EventRegistry(SCENE_EVENTS).validate(restored)
    assert restored == event
    assert isinstance(restored, events.TabEvent)
    assert not isinstance(restored, events.BrowserEvent)
    assert set(adapter.dump_python(event)) == {
        "browser_id",
        "tab_id",
        "document_id",
        "action_id",
        "at",
        "type",
        "delta_x",
        "delta_y",
        *extra,
    }


def test_canvas_work_contract_roundtrips_with_typed_geometry_and_phase():
    adapter = TypeAdapter(WorkPresentedEvent)
    event = WorkPresentedEvent(
        work_id="capture",
        call_id="call",
        kind=ActionKind.SCREENSHOT,
        title="Screenshot",
        phase=WorkPhase.COMPLETED,
        region=CaptureRegion(x=10, y=20, width=100, height=80),
        viewport=ViewportSize(width=1280, height=800),
        target_id="tab",
        document_id="document",
    )
    restored = adapter.validate_json(adapter.dump_json(event))
    EventRegistry(SCENE_EVENTS).validate(restored)
    assert restored == event
    assert restored.phase is WorkPhase.COMPLETED and isinstance(
        restored.region, CaptureRegion
    )
    assert isinstance(restored.viewport, ViewportSize)


def test_coordinate_receipt_roundtrips_with_its_source_viewport():
    adapter = TypeAdapter(events.CursorMovedEvent)
    event = events.CursorMovedEvent(
        from_position=(10, 20),
        to_position=(300, 200),
        control_point_1=(80, -15),
        control_point_2=(250, 260),
        duration=0.4,
        viewport=ViewportSize(width=1280, height=720),
        target_id="tab",
        document_id="document",
    )
    restored = adapter.validate_json(adapter.dump_json(event))
    EventRegistry(events.INPUT_EVENTS).validate(restored)
    assert restored == event
    assert isinstance(restored, events.PositionedEvent)
    assert isinstance(restored.viewport, ViewportSize)


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
