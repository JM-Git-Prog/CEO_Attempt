"""Cross-component integration tests for Task 9.4: toggle + REAL mode.

Validates that ModeToggle, RealBinder, and GameDesigner cooperate correctly:
- Mode persistence survives reload (Req 25.5)
- Toggle preserves visuals — only behavior overlays swap (Req 25.2)
- REAL binding displays data on surfaces through the toggle system (Req 24.4)

**Validates: Requirements 25.2, 25.5, 24.4**
"""
from __future__ import annotations

import json
import uuid

import pytest

from src.unified_pipeline.game_designer import design_game
from src.unified_pipeline.mode_toggle import ModeToggle, ModeActivation, RewardDestination
from src.unified_pipeline.modes import Mode, RealOverlay
from src.unified_pipeline.models import Brief, GameOverlay
from src.unified_pipeline.real_binder import RealBinder


# ── Helpers ────────────────────────────────────────────────────────────────────


def _uuid() -> str:
    return str(uuid.uuid4())


def _kitchenette_brief() -> Brief:
    return Brief(room_purpose="a small warm kitchenette for coffee")


def _make_room_surfaces() -> tuple[str, str, str]:
    """Return three stable surface UUIDs for desk, whiteboard, terminal."""
    return _uuid(), _uuid(), _uuid()


def _build_real_overlay_with_bindings(
    desk_uuid: str, whiteboard_uuid: str
) -> tuple[RealBinder, RealOverlay]:
    """Create a RealBinder with two active bindings and return its overlay."""
    binder = RealBinder([desk_uuid, whiteboard_uuid])
    binder.bind_static(desk_uuid, "3 unread messages", surface_binding="desk")
    binder.bind_mcp(
        whiteboard_uuid,
        tool_type="calendar",
        surface_binding="whiteboard",
        server_name="calendar-server",
        tool_name="list_events",
        arguments={"range": "today"},
    )
    return binder, binder.to_overlay()


# ── Test: Mode persistence survives reload (Req 25.5) ─────────────────────────


class TestModePersistenceAcrossReload:
    """Verify mode state persists to disk and is correctly restored."""

    def test_toggle_to_game_persists_and_reloads_correctly(self, tmp_path) -> None:
        """After toggling to GAME and reloading, the mode stays GAME."""
        config = tmp_path / "modes.json"
        desk_uuid, wb_uuid, _ = _make_room_surfaces()
        _, real_overlay = _build_real_overlay_with_bindings(desk_uuid, wb_uuid)
        game_overlay = design_game(_kitchenette_brief())

        # Session 1: register room, toggle to GAME
        toggle1 = ModeToggle(config)
        toggle1.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)
        activation = toggle1.toggle("kitchen")
        assert activation.mode is Mode.GAME

        # Session 2: reload from persisted config
        toggle2 = ModeToggle(config)
        toggle2.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)
        state = toggle2.get_state("kitchen")
        assert state.current_mode is Mode.GAME
        assert state.persisted is True

    def test_multiple_rooms_persist_independently(self, tmp_path) -> None:
        """Each room remembers its own mode across reload."""
        config = tmp_path / "modes.json"
        desk_uuid, wb_uuid, _ = _make_room_surfaces()
        _, real_overlay = _build_real_overlay_with_bindings(desk_uuid, wb_uuid)
        game_overlay = design_game(_kitchenette_brief())

        # Session 1: set different modes per room
        toggle1 = ModeToggle(config)
        toggle1.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)
        toggle1.register_room("office", game_overlay=game_overlay, real_overlay=real_overlay)
        toggle1.set_mode("kitchen", Mode.GAME)
        toggle1.set_mode("office", Mode.REAL)

        # Session 2: verify independence
        toggle2 = ModeToggle(config)
        assert toggle2.get_state("kitchen").current_mode is Mode.GAME
        assert toggle2.get_state("office").current_mode is Mode.REAL

    def test_repeated_toggles_persist_final_state(self, tmp_path) -> None:
        """Only the final mode value persists, not intermediate states."""
        config = tmp_path / "modes.json"
        game_overlay = design_game(_kitchenette_brief())
        real_overlay = RealOverlay()

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)

        # Toggle three times: REAL → GAME → REAL → GAME
        toggle.toggle("kitchen")  # → GAME
        toggle.toggle("kitchen")  # → REAL
        toggle.toggle("kitchen")  # → GAME

        # Reload and verify final state
        toggle2 = ModeToggle(config)
        assert toggle2.get_state("kitchen").current_mode is Mode.GAME


# ── Test: Toggle preserves visuals (Req 25.2) ─────────────────────────────────


class TestTogglePreservesVisuals:
    """The toggle must never emit or change any visual property."""

    def test_activation_dict_contains_no_visual_keys(self, tmp_path) -> None:
        """ModeActivation output has behavior keys only, no visual state."""
        config = tmp_path / "modes.json"
        desk_uuid = _uuid()
        binder = RealBinder([desk_uuid])
        binder.bind_static(desk_uuid, "hello", surface_binding="desk")
        real_overlay = binder.to_overlay()
        game_overlay = design_game(_kitchenette_brief())

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)

        # Enter in REAL mode
        real_activation = toggle.enter_room("kitchen")
        real_dict = real_activation.to_dict()

        # Toggle to GAME
        game_activation = toggle.toggle("kitchen")
        game_dict = game_activation.to_dict()

        # Neither activation exposes visual keys
        visual_keys = {"geometry", "materials", "lighting", "transforms", "meshes", "textures"}
        assert not (visual_keys & set(real_dict.keys()))
        assert not (visual_keys & set(game_dict.keys()))

    def test_same_room_different_modes_share_no_visual_mutation(self, tmp_path) -> None:
        """Switching modes only changes behavior_overlay and reward_destination."""
        config = tmp_path / "modes.json"
        desk_uuid = _uuid()
        binder = RealBinder([desk_uuid])
        binder.bind_static(desk_uuid, {"inbox": 5}, surface_binding="desk")
        real_overlay = binder.to_overlay()
        game_overlay = design_game(_kitchenette_brief())

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)

        real_act = toggle.enter_room("kitchen")
        game_act = toggle.toggle("kitchen")

        # room_id is invariant
        assert real_act.room_id == game_act.room_id == "kitchen"
        # Only the overlay type and reward channel differ
        assert real_act.mode is Mode.REAL
        assert game_act.mode is Mode.GAME
        assert real_act.reward_destination is RewardDestination.REAL_BUDGET_AND_LAND
        assert game_act.reward_destination is RewardDestination.GAME_CONTENT_ONLY

    def test_game_overlay_from_designer_has_no_visual_fields(self, tmp_path) -> None:
        """GameDesigner stub output contains only behavior data, never visuals."""
        overlay = design_game(_kitchenette_brief())
        overlay_dict = overlay.to_dict()

        visual_keys = {"geometry", "materials", "lighting", "transforms", "meshes", "textures"}
        assert not (visual_keys & set(overlay_dict.keys()))
        # It does contain behavior-only fields
        assert "theme" in overlay_dict
        assert "mechanics" in overlay_dict
        assert overlay.rules == ""  # stubbed — no executable logic


# ── Test: REAL binding displays data (Req 24.4) ───────────────────────────────


class TestRealBindingDisplaysData:
    """REAL mode surfaces display data without altering world visuals."""

    def test_real_mode_activation_exposes_tool_bindings_overlay(self, tmp_path) -> None:
        """When in REAL mode, the active overlay contains tool bindings."""
        config = tmp_path / "modes.json"
        desk_uuid = _uuid()
        binder = RealBinder([desk_uuid])
        binder.bind_static(desk_uuid, "Meeting at 3pm", surface_binding="desk")
        real_overlay = binder.to_overlay()
        game_overlay = design_game(_kitchenette_brief())

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)

        activation = toggle.enter_room("kitchen")
        assert activation.mode is Mode.REAL
        # The overlay is the RealOverlay with tool bindings
        assert isinstance(activation.overlay, RealOverlay)
        assert desk_uuid in activation.overlay.tool_bindings
        assert activation.overlay.tool_bindings[desk_uuid]["read_only"] is True

    def test_static_data_displays_through_binder_while_in_real_mode(self, tmp_path) -> None:
        """The full path: bind → toggle activates REAL → display reads data."""
        config = tmp_path / "modes.json"
        desk_uuid = _uuid()
        whiteboard_uuid = _uuid()

        binder, real_overlay = _build_real_overlay_with_bindings(desk_uuid, whiteboard_uuid)
        game_overlay = design_game(_kitchenette_brief())

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)

        # Enter room in REAL mode
        activation = toggle.enter_room("kitchen")
        assert activation.mode is Mode.REAL

        # Display static data on the desk surface
        display = binder.display(desk_uuid)
        assert display.text == "3 unread messages"
        assert display.content_type == "text/plain"
        assert display.read_only is True
        assert display.surface_uuid == desk_uuid

    def test_mcp_binding_builds_request_in_real_mode(self, tmp_path) -> None:
        """MCP-bound surfaces generate proper JSON-RPC read requests."""
        config = tmp_path / "modes.json"
        desk_uuid = _uuid()
        whiteboard_uuid = _uuid()

        binder, real_overlay = _build_real_overlay_with_bindings(desk_uuid, whiteboard_uuid)
        game_overlay = design_game(_kitchenette_brief())

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)
        toggle.enter_room("kitchen")  # activate REAL mode

        # Build the MCP request for whiteboard calendar binding
        request = binder.build_mcp_request(whiteboard_uuid)
        assert request["method"] == "tools/call"
        assert request["params"]["name"] == "list_events"
        assert request["params"]["arguments"] == {"range": "today"}

    def test_real_data_display_does_not_contain_visual_mutations(self, tmp_path) -> None:
        """SurfaceDisplay carries only text/data payload, never geometry or materials."""
        config = tmp_path / "modes.json"
        desk_uuid = _uuid()

        binder = RealBinder([desk_uuid])
        binder.bind_static(desk_uuid, {"tasks": ["review", "deploy"]}, surface_binding="desk")
        real_overlay = binder.to_overlay()
        game_overlay = design_game(_kitchenette_brief())

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)
        toggle.enter_room("kitchen")

        display_dict = binder.display(desk_uuid).to_dict()
        visual_keys = {"geometry", "materials", "lighting", "transforms", "meshes", "textures"}
        assert not (visual_keys & set(display_dict.keys()))
        assert display_dict["data"] == {"tasks": ["review", "deploy"]}
        assert display_dict["read_only"] is True

    def test_switching_to_game_hides_real_bindings_in_overlay(self, tmp_path) -> None:
        """After toggling to GAME, the active overlay is GameOverlay not RealOverlay."""
        config = tmp_path / "modes.json"
        desk_uuid = _uuid()

        binder = RealBinder([desk_uuid])
        binder.bind_static(desk_uuid, "data", surface_binding="desk")
        real_overlay = binder.to_overlay()
        game_overlay = design_game(_kitchenette_brief())

        toggle = ModeToggle(config)
        toggle.register_room("kitchen", game_overlay=game_overlay, real_overlay=real_overlay)
        toggle.enter_room("kitchen")

        # Toggle to GAME — overlay should now be the GameOverlay
        game_activation = toggle.toggle("kitchen")
        assert isinstance(game_activation.overlay, GameOverlay)
        assert game_activation.mode is Mode.GAME
        # GameOverlay does not expose tool_bindings
        assert not hasattr(game_activation.overlay, "tool_bindings")

        # Toggle back — REAL overlay is restored with bindings intact
        real_activation = toggle.toggle("kitchen")
        assert isinstance(real_activation.overlay, RealOverlay)
        assert desk_uuid in real_activation.overlay.tool_bindings
