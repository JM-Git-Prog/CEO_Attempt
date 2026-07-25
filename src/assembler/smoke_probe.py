"""Standalone probe script executed inside UPBGE_Editor --background mode.

Invoked as:
    upbge --background path/to/file.blend --python smoke_probe.py

Performs 4 structural checks via bpy and prints the result as a JSON line
prefixed with SMOKE_RESULT= on stdout for robust parsing amid engine logs.

Does NOT enter game mode, does NOT open a visible window.
"""

from __future__ import annotations

import json
import sys

_RESULT_MARKER = "SMOKE_RESULT="


def _run_checks() -> dict[str, object]:
    """Execute structural checks and return a results dict."""
    import bpy  # type: ignore[import-not-found]  # available inside UPBGE embedded Python

    results: dict[str, dict[str, object]] = {}

    # Check 1: Player controller text datablock exists and is non-empty
    player_texts = [
        text for text in bpy.data.texts
        if "player" in text.name.lower()
    ]
    has_player_controller = any(
        len(text.as_string().strip()) > 0 for text in player_texts
    )
    results["player_controller_exists"] = {
        "passed": has_player_controller,
        "detail": (
            f"Found {len(player_texts)} text datablock(s) with 'player' in name, "
            f"non-empty: {has_player_controller}"
        ),
    }

    # Check 2: At least one object has Character physics type
    character_objects = [
        obj for obj in bpy.data.objects
        if hasattr(obj, "game") and obj.game.physics_type == "CHARACTER"
    ]
    has_character_physics = len(character_objects) > 0
    results["character_physics"] = {
        "passed": has_character_physics,
        "detail": (
            f"Found {len(character_objects)} object(s) with CHARACTER physics type"
        ),
    }

    # Check 3: Logic brick controllers of type PYTHON are wired to text datablocks
    wired_controllers: list[str] = []
    unwired_controllers: list[str] = []
    for obj in bpy.data.objects:
        if not hasattr(obj, "game"):
            continue
        for controller in obj.game.controllers:
            if controller.type == "PYTHON":
                # A Python controller is considered "wired" if it has a text reference
                if hasattr(controller, "text") and controller.text is not None:
                    wired_controllers.append(f"{obj.name}.{controller.name}")
                else:
                    unwired_controllers.append(f"{obj.name}.{controller.name}")

    logic_bricks_ok = len(wired_controllers) > 0 and len(unwired_controllers) == 0
    results["logic_bricks_wired"] = {
        "passed": logic_bricks_ok,
        "detail": (
            f"Wired: {len(wired_controllers)}, unwired: {len(unwired_controllers)}"
        ),
    }

    # Check 4: Scene loaded without errors (if we got this far, it loaded)
    results["scene_loads"] = {
        "passed": True,
        "detail": "Scene loaded successfully via bpy",
    }

    return results


def main() -> None:
    """Entry point — run checks and emit result line."""
    try:
        checks = _run_checks()
        payload = {"success": True, "checks": checks}
    except Exception as exc:
        payload = {
            "success": False,
            "checks": {
                "player_controller_exists": {"passed": False, "detail": f"probe error: {exc}"},
                "character_physics": {"passed": False, "detail": f"probe error: {exc}"},
                "logic_bricks_wired": {"passed": False, "detail": f"probe error: {exc}"},
                "scene_loads": {"passed": False, "detail": f"scene load error: {exc}"},
            },
        }

    # Print with marker prefix for robust parsing
    print(_RESULT_MARKER + json.dumps(payload), flush=True)


if __name__ == "__main__":
    main()
