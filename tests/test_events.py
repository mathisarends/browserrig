from dataclasses import fields
from typing import get_args, get_type_hints

import pytest
from harnessed.events import EventRegistry

from browserrig import events


def test_enum_tags_and_registry_roundtrip():
    registry = EventRegistry(
        events.BROWSER_EVENTS
        + events.ACTION_EVENTS
        + events.READINESS_EVENTS
        + events.NUDGE_EVENTS
        + events.RECORDING_EVENTS
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
        before=events.PageState(url="https://example.org/", document_id="document", scroll_y=100),
    )
    restored = registry.decode(registry.encode(event))
    assert restored == event
    assert isinstance(restored.before, events.PageState)


@pytest.mark.parametrize(
    "kind",
    events.BROWSER_EVENTS
    + events.ACTION_EVENTS
    + events.READINESS_EVENTS
    + events.NUDGE_EVENTS
    + events.RECORDING_EVENTS
    + events.ACTIVITY_EVENTS
    + events.INPUT_EVENTS
    + events.FILE_EVENTS
    + events.UPLOAD_EVENTS
    + (events.ObservationCapturedEvent,),
)
def test_each_tag_has_one_literal_enum_and_matching_default(kind):
    values = get_args(get_type_hints(kind)["type"])
    assert len(values) == 1
    assert isinstance(values[0], events.EventKind)
    assert next(field.default for field in fields(kind) if field.name == "type") is values[0]
