"""Focused unit tests for Task 9.2 REAL read-only surface binding.

**Validates: Requirements 24.1, 24.2, 24.3, 24.4, 24.5**
"""
from __future__ import annotations

import uuid

import pytest

from src.unified_pipeline.real_binder import (
    READ_ONLY_ANNOTATIONS,
    RealBinder,
    RealBindingError,
    ReadOnlyViolation,
    UnknownSurfaceError,
)


def _surface_uuid() -> str:
    return str(uuid.uuid4())


def test_static_text_binding_displays_on_uuid_surface_and_builds_overlay() -> None:
    surface_uuid = _surface_uuid()
    binder = RealBinder([surface_uuid])

    binding = binder.bind_static(
        surface_uuid,
        "Three unread messages",
        surface_binding="desk",
    )
    display = binder.display(surface_uuid)
    overlay = binder.to_overlay()

    assert binding.surface_uuid == surface_uuid
    assert display.text == "Three unread messages"
    assert display.content_type == "text/plain"
    assert display.read_only is True
    assert overlay.read_only is True
    assert overlay.tool_bindings[surface_uuid] == {
        "tool_type": "static_data",
        "surface_binding": "desk",
        "read_only": True,
        "mcp": {
            "server_name": "builtin.static",
            "tool_name": "read_static_data",
            "arguments": {},
            "annotations": READ_ONLY_ANNOTATIONS,
        },
    }


def test_static_json_display_is_deterministic_and_detached_from_input() -> None:
    surface_uuid = _surface_uuid()
    source = {"unread": 3, "subjects": ["Plan", "Canon"]}
    binder = RealBinder([surface_uuid])
    binder.bind_static(surface_uuid, source, surface_binding="terminal")
    source["unread"] = 99

    payload = binder.display(surface_uuid).to_dict()

    assert payload["text"] == '{"subjects":["Plan","Canon"],"unread":3}'
    assert payload["content_type"] == "application/json"
    assert payload["data"] == {"unread": 3, "subjects": ["Plan", "Canon"]}
    assert not ({"geometry", "materials", "lighting", "transform"} & payload.keys())


def test_mcp_binding_builds_standard_read_only_call_and_displays_result() -> None:
    surface_uuid = _surface_uuid()
    binder = RealBinder([surface_uuid])
    binder.bind_mcp(
        surface_uuid,
        tool_type="calendar",
        surface_binding="whiteboard",
        server_name="calendar-server",
        tool_name="list_events",
        arguments={"range": "today"},
    )

    request = binder.build_mcp_request(surface_uuid, request_id="surface-read-1")
    display = binder.display(surface_uuid, {"events": ["Design review"]})
    descriptor = binder.binding_for(surface_uuid).mcp.to_dict()

    assert request == {
        "jsonrpc": "2.0",
        "id": "surface-read-1",
        "method": "tools/call",
        "params": {"name": "list_events", "arguments": {"range": "today"}},
    }
    assert descriptor["annotations"] == READ_ONLY_ANNOTATIONS
    assert display.source == {
        "server_name": "calendar-server",
        "tool_name": "list_events",
    }
    assert display.text == '{"events":["Design review"]}'


def test_mcp_binding_requires_adapter_result_before_display() -> None:
    surface_uuid = _surface_uuid()
    binder = RealBinder([surface_uuid])
    binder.bind_mcp(
        surface_uuid,
        tool_type="documents",
        surface_binding="filing_cabinet",
        server_name="document-server",
        tool_name="list_documents",
    )

    with pytest.raises(RealBindingError, match="read result data"):
        binder.display(surface_uuid)


def test_non_read_only_mcp_annotations_are_rejected() -> None:
    surface_uuid = _surface_uuid()
    binder = RealBinder([surface_uuid])

    with pytest.raises(ReadOnlyViolation, match="readOnlyHint"):
        binder.bind_mcp(
            surface_uuid,
            tool_type="inbox",
            surface_binding="desk",
            server_name="mail-server",
            tool_name="send_message",
            annotations={"readOnlyHint": False},
        )

    with pytest.raises(ReadOnlyViolation, match="destructiveHint"):
        binder.bind_mcp(
            surface_uuid,
            tool_type="inbox",
            surface_binding="desk",
            server_name="mail-server",
            tool_name="delete_message",
            annotations={"readOnlyHint": True, "destructiveHint": True},
        )


def test_surface_assignment_requires_known_stable_uuid_and_is_unique() -> None:
    allowed_uuid = _surface_uuid()
    other_uuid = _surface_uuid()
    binder = RealBinder([allowed_uuid])

    with pytest.raises(UnknownSurfaceError, match="stable UUID"):
        binder.bind_static("desk", "hello")
    with pytest.raises(UnknownSurfaceError, match="not present"):
        binder.bind_static(other_uuid, "hello")

    binder.bind_static(allowed_uuid, None)
    assert binder.display(allowed_uuid).data is None
    with pytest.raises(RealBindingError, match="already has"):
        binder.bind_static(allowed_uuid, "replacement")
