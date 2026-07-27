"""Property-based tests for interaction binding to component attachment (Property 11).

**Validates: Requirements 5.2, 5.3**

Property 11: Interaction Binding to Component Attachment
- For any set of interaction bindings in a RuntimePlan, the compiler SHALL
  produce exactly one component attachment per binding with matching `args` values.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

from hypothesis import given, settings, strategies as st

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.component_attach_050 import _configure_runtime_050


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Door parameters strategy: realistic door interaction parameters
door_params_strategy = st.fixed_dictionaries({
    "open_angle_deg": st.floats(
        min_value=-180.0, max_value=180.0,
        allow_nan=False, allow_infinity=False,
    ).filter(lambda x: abs(x) > 0.1),
    "speed_deg_s": st.floats(
        min_value=1.0, max_value=720.0,
        allow_nan=False, allow_infinity=False,
    ),
    "initially_open": st.booleans(),
})

# Generate a valid subject_id string
subject_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1, max_size=20,
)

# Single door interaction binding dict (as consumed by _configure_runtime_050)
door_binding_strategy = st.builds(
    lambda subject_id, params: {
        "kind": "door",
        "subject_id": subject_id,
        "parameters": params,
    },
    subject_id=subject_id_strategy,
    params=door_params_strategy,
)

# A list of door interaction bindings with unique subject_ids
door_bindings_strategy = st.lists(
    door_binding_strategy, min_size=1, max_size=8
).map(
    # Deduplicate subject_ids — keep the last binding for each id
    lambda bindings: list({b["subject_id"]: b for b in bindings}.values())
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fallback_api_report() -> UPBGEComponentAPI:
    """Create a UPBGEComponentAPI that forces the fallback path (no native API)."""
    return UPBGEComponentAPI(
        has_game_attr=False,
        has_components_attr=False,
        component_api_path=None,
        component_add_method=None,
        has_logic_ops=False,
        physics_api_path=None,
        has_game_physics=False,
        blender_version=(5, 0, 1),
        upbge_detected=True,
        fallback_required=True,
    )


class _MockTexts:
    """Dict-like mock for bpy.data.texts that supports get/new/remove."""

    def __init__(self):
        self._store: dict[str, MagicMock] = {}

    def get(self, name, default=None):
        return self._store.get(name, default)

    def new(self, name):
        text = MagicMock()
        text.name = name
        self._store[name] = text
        return text

    def remove(self, text):
        self._store.pop(text.name, None)


def _make_mock_bpy():
    """Create a mock bpy module with texts and ops."""
    mock_bpy = MagicMock()
    mock_bpy.data.texts = _MockTexts()
    mock_bpy.data.filepath = ""
    mock_bpy.ops.wm.save_as_mainfile = MagicMock()
    mock_bpy.ops.mesh.primitive_cube_add = MagicMock()
    mock_bpy.context.active_object = MagicMock(name="KiroPlayer")
    mock_bpy.context.active_object.name = "KiroPlayer"
    return mock_bpy


class _MockBlenderObject(MagicMock):
    """Mock Blender object that stores ID properties in a backing dict."""

    def __init__(self, name: str = "Object", **kwargs):
        super().__init__(**kwargs)
        self._props: dict = {}
        self.name = name

    def __setitem__(self, key, value):
        self._props[key] = value

    def __getitem__(self, key):
        return self._props[key]

    def get(self, key, default=None):
        return self._props.get(key, default)

    def __contains__(self, key):
        return key in self._props


def _make_mock_object(name: str) -> _MockBlenderObject:
    """Create a mock Blender object that stores ID properties in a dict."""
    return _MockBlenderObject(name=name)


# ---------------------------------------------------------------------------
# Property 11: Interaction Binding to Component Attachment
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(door_bindings=door_bindings_strategy)
def test_property_11_one_attachment_per_door_binding(
    door_bindings: list[dict],
):
    """Property 11: For any set of door interaction bindings, the compiler SHALL
    produce exactly one component attachment per binding with matching args.

    **Validates: Requirements 5.2, 5.3**

    Strategy:
    - Generate random sets of door interaction bindings (unique subject_ids)
    - Create mock objects for each subject_id
    - Patch _attach_component_050 to record calls
    - Call _configure_runtime_050 with the plan
    - Verify exactly one _attach_component_050 call per door binding
    - Verify the args match (open_angle_deg, speed_deg_s, initially_open)
    """
    mock_bpy = _make_mock_bpy()

    # Build object_by_id with a mock for each subject + a player
    object_by_id: dict[str, MagicMock] = {}
    for binding in door_bindings:
        sid = binding["subject_id"]
        object_by_id[sid] = _make_mock_object(sid)

    # Add a player object so _configure_runtime_050 doesn't try to create one
    player_obj = _make_mock_object("player")
    object_by_id["player"] = player_obj

    camera_obj = _make_mock_object("Camera")
    api_report = _make_fallback_api_report()

    plan = {
        "interactions": door_bindings,
        "player_args": {},
    }

    with patch(
        "src.assembler.component_attach_050._attach_component_050"
    ) as mock_attach:
        mock_attach.return_value = False  # fallback used

        _configure_runtime_050(mock_bpy, plan, object_by_id, camera_obj, api_report)

        # Collect all door attachment calls (exclude player attachment)
        door_calls = [
            c for c in mock_attach.call_args_list
            if c[0][2] == "DoorComponent"  # component_class_name is 3rd positional arg
        ]

        # Property: exactly one attachment per door binding
        assert len(door_calls) == len(door_bindings), (
            f"Expected {len(door_bindings)} DoorComponent attachments, "
            f"got {len(door_calls)}. Bindings: {[b['subject_id'] for b in door_bindings]}"
        )

        # Property: each attachment args match the binding parameters
        # Build a mapping from subject_id to expected args
        expected_args_by_subject = {}
        for binding in door_bindings:
            sid = binding["subject_id"]
            params = binding.get("parameters", {})
            # _extract_door_args applies defaults then merges params
            expected = {
                "open_angle_deg": params.get("open_angle_deg", 90.0),
                "speed_deg_s": params.get("speed_deg_s", 120.0),
                "initially_open": params.get("initially_open", False),
            }
            expected_args_by_subject[sid] = expected

        # Verify each door call has the correct args
        attached_subjects = set()
        for c in door_calls:
            # _attach_component_050(bpy, obj, class_name, text_name, args, api_report)
            call_obj = c[0][1]      # obj
            call_args = c[0][4]     # args dict

            # Find the subject_id for this object
            subject_id = None
            for sid, mock_obj in object_by_id.items():
                if mock_obj is call_obj:
                    subject_id = sid
                    break

            assert subject_id is not None, (
                f"Could not find subject_id for attached object {call_obj}"
            )
            assert subject_id not in attached_subjects, (
                f"Duplicate attachment for subject_id={subject_id}"
            )
            attached_subjects.add(subject_id)

            expected = expected_args_by_subject[subject_id]
            assert call_args["open_angle_deg"] == expected["open_angle_deg"], (
                f"Mismatch open_angle_deg for {subject_id}: "
                f"expected {expected['open_angle_deg']}, got {call_args['open_angle_deg']}"
            )
            assert call_args["speed_deg_s"] == expected["speed_deg_s"], (
                f"Mismatch speed_deg_s for {subject_id}: "
                f"expected {expected['speed_deg_s']}, got {call_args['speed_deg_s']}"
            )
            assert call_args["initially_open"] == expected["initially_open"], (
                f"Mismatch initially_open for {subject_id}: "
                f"expected {expected['initially_open']}, got {call_args['initially_open']}"
            )


@settings(max_examples=200, deadline=None)
@given(
    num_non_door=st.integers(min_value=0, max_value=5),
    door_bindings=door_bindings_strategy,
)
def test_property_11_non_door_bindings_produce_no_door_attachment(
    num_non_door: int,
    door_bindings: list[dict],
):
    """Property 11: Non-door bindings SHALL NOT produce DoorComponent attachments.

    **Validates: Requirements 5.2, 5.3**

    Mixed interaction types (door + non-door) should produce exactly one
    DoorComponent attachment per door binding and zero for non-door bindings.
    """
    mock_bpy = _make_mock_bpy()

    # Create non-door bindings (kind != "door")
    non_door_bindings = [
        {"kind": "grab", "subject_id": f"grab_obj_{i}", "parameters": {}}
        for i in range(num_non_door)
    ]

    all_bindings = door_bindings + non_door_bindings

    # Build object_by_id
    object_by_id: dict[str, MagicMock] = {}
    for binding in all_bindings:
        sid = binding["subject_id"]
        object_by_id[sid] = _make_mock_object(sid)

    player_obj = _make_mock_object("player")
    object_by_id["player"] = player_obj

    camera_obj = _make_mock_object("Camera")
    api_report = _make_fallback_api_report()

    plan = {
        "interactions": all_bindings,
        "player_args": {},
    }

    with patch(
        "src.assembler.component_attach_050._attach_component_050"
    ) as mock_attach:
        mock_attach.return_value = False

        _configure_runtime_050(mock_bpy, plan, object_by_id, camera_obj, api_report)

        door_calls = [
            c for c in mock_attach.call_args_list
            if c[0][2] == "DoorComponent"
        ]

        # Only door bindings should produce DoorComponent attachments
        assert len(door_calls) == len(door_bindings), (
            f"Expected {len(door_bindings)} DoorComponent attachments "
            f"(with {num_non_door} non-door bindings present), got {len(door_calls)}"
        )
