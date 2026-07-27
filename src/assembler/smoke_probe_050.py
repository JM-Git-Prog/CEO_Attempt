"""UPBGE 0.50 Smoke Validation Probe — script constant and host-side parser.

This module contains two distinct parts:

1. SMOKE_PROBE_SCRIPT_050: A string constant containing the headless validation script
   that runs INSIDE UPBGE 0.50 via ``--background --python smoke_probe.py -- <blend_path>``.
   It checks component attachment, text datablock presence, physics configuration,
   door components, and scene integrity. Prints a JSON report prefixed with
   ``SMOKE_RESULT=``.

2. parse_smoke_output(): Host-side function that extracts the JSON result from
   the probe's stdout. This code runs in the normal Python host process (NOT inside
   UPBGE) and must NOT import ``bpy``.
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Marker used by both the probe script (emitter) and the parser (consumer).
# ---------------------------------------------------------------------------
SMOKE_RESULT_MARKER = "SMOKE_RESULT="

# ---------------------------------------------------------------------------
# Probe script — executed inside UPBGE 0.50 headless mode.
# Stored as a string constant so the runner can write it to a temp file.
# Invoked via: upbge --background --python <script.py> -- <blend_path>
# This script imports bpy at runtime (available inside UPBGE embedded Python).
# ---------------------------------------------------------------------------
SMOKE_PROBE_SCRIPT_050 = r'''"""UPBGE 0.50 Smoke Validation Probe.

Executed headlessly inside UPBGE 0.50 to validate a runtime_candidate.blend:
1. player_component_attached — player object has component via native API or fallback
2. text_datablocks_present — all required .py Text datablocks exist
3. physics_configured — player has CHARACTER physics via RNA or stored intent property
4. door_components_attached — door objects have DoorComponent registered
5. scene_loads — .blend opens without bpy errors

Usage: upbge --background --python smoke_probe_050.py -- <blend_path>

Output: JSON report on stdout with SMOKE_RESULT= prefix marker.
Must NOT enter game mode, launch blenderplayer, or open visible window.
Must complete within 30 seconds.
"""

import bpy
import json
import sys

SMOKE_RESULT_MARKER = "SMOKE_RESULT="


def _get_blend_path():
    """Extract blend file path from command-line arguments after '--'."""
    argv = sys.argv
    if "--" in argv:
        args_after = argv[argv.index("--") + 1:]
        if args_after:
            return args_after[0]
    return None


def check_scene_loads(blend_path):
    """Check 5: .blend opens without bpy errors."""
    try:
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        if len(bpy.data.objects) == 0:
            return {"passed": False, "detail": "Scene has no objects"}
        return {"passed": True, "detail": f"Scene loaded with {len(bpy.data.objects)} objects"}
    except Exception as e:
        return {"passed": False, "detail": f"Scene load error: {e}"}


def _find_player_object():
    """Find the player object by name or fallback property."""
    for obj in bpy.data.objects:
        if obj.name == "KiroPlayer":
            return obj
        if obj.get("kiro_component_class") == "PlayerComponent":
            return obj
    # Broader search by name pattern
    for obj in bpy.data.objects:
        if "player" in obj.name.lower():
            return obj
    return None


def check_player_component_attached():
    """Check 1: Player object has component via native API or fallback properties."""
    player = _find_player_object()
    if player is None:
        return {"passed": False, "detail": "No player object found"}

    # Native path: check via obj.game.components
    if hasattr(player, "game") and hasattr(player.game, "components"):
        try:
            for comp in player.game.components:
                if "Player" in comp.name or "player" in getattr(comp, "module", ""):
                    return {"passed": True, "detail": f"Native component on {player.name}"}
        except (AttributeError, TypeError):
            pass

    # Fallback path: check stored ID properties
    if player.get("kiro_component_class") == "PlayerComponent":
        module = player.get("kiro_component_module", "unknown")
        return {"passed": True, "detail": f"Fallback component on {player.name}: {module}.PlayerComponent"}

    return {"passed": False, "detail": f"Player object '{player.name}' has no component (native or fallback)"}


def check_text_datablocks_present():
    """Check 2: Required .py Text datablocks exist in bpy.data.texts."""
    required = ["kiro_player_first_person.py", "kiro_interaction_door.py"]
    missing = [name for name in required if bpy.data.texts.get(name) is None]
    if missing:
        return {"passed": False, "detail": f"Missing: {', '.join(missing)}"}
    return {"passed": True, "detail": f"All {len(required)} required text datablocks present"}


def check_physics_configured():
    """Check 3: Player has CHARACTER physics via RNA or stored intent property."""
    player = _find_player_object()
    if player is None:
        return {"passed": False, "detail": "No player object found"}

    # Native RNA path
    if hasattr(player, "game") and hasattr(player.game, "physics_type"):
        try:
            if player.game.physics_type == "CHARACTER":
                return {"passed": True, "detail": f"Native CHARACTER physics on {player.name}"}
        except (AttributeError, TypeError):
            pass

    # Fallback: stored intent property
    if player.get("kiro_physics_type") == "CHARACTER":
        return {"passed": True, "detail": f"Fallback CHARACTER physics on {player.name} (runtime bootstrap required)"}

    return {"passed": False, "detail": f"Player '{player.name}' has no CHARACTER physics configured"}


def check_door_components_attached():
    """Check 4: Door objects have DoorComponent registered."""
    doors_found = 0
    doors_with_component = 0
    doors_missing = []

    for obj in bpy.data.objects:
        if obj.get("kiro_open_angle_deg") is not None:
            doors_found += 1
            has_component = False

            # Native path
            if hasattr(obj, "game") and hasattr(obj.game, "components"):
                try:
                    for comp in obj.game.components:
                        if "Door" in comp.name:
                            has_component = True
                            break
                except (AttributeError, TypeError):
                    pass

            # Fallback path
            if not has_component and obj.get("kiro_component_class") == "DoorComponent":
                has_component = True

            if has_component:
                doors_with_component += 1
            else:
                doors_missing.append(obj.name)

    if doors_found == 0:
        return {"passed": True, "detail": "No doors in scene (vacuously true)"}
    if doors_with_component == doors_found:
        return {"passed": True, "detail": f"All {doors_found} doors have DoorComponent"}
    return {
        "passed": False,
        "detail": f"{doors_with_component}/{doors_found} doors have components; missing: {', '.join(doors_missing)}"
    }


def main():
    blend_path = _get_blend_path()
    if blend_path is None:
        result = {
            "schema_version": "smoke-probe-050/v1",
            "checks": {
                "scene_loads": {"passed": False, "detail": "No blend path provided via -- argument"},
                "player_component_attached": {"passed": False, "detail": "Skipped (no blend loaded)"},
                "text_datablocks_present": {"passed": False, "detail": "Skipped (no blend loaded)"},
                "physics_configured": {"passed": False, "detail": "Skipped (no blend loaded)"},
                "door_components_attached": {"passed": False, "detail": "Skipped (no blend loaded)"},
            },
            "all_passed": False,
        }
        print(SMOKE_RESULT_MARKER + json.dumps(result, sort_keys=True), flush=True)
        sys.exit(1)

    # Run checks in order; scene_loads must succeed before others make sense
    checks = {}
    checks["scene_loads"] = check_scene_loads(blend_path)

    if checks["scene_loads"]["passed"]:
        checks["player_component_attached"] = check_player_component_attached()
        checks["text_datablocks_present"] = check_text_datablocks_present()
        checks["physics_configured"] = check_physics_configured()
        checks["door_components_attached"] = check_door_components_attached()
    else:
        checks["player_component_attached"] = {"passed": False, "detail": "Skipped (scene failed to load)"}
        checks["text_datablocks_present"] = {"passed": False, "detail": "Skipped (scene failed to load)"}
        checks["physics_configured"] = {"passed": False, "detail": "Skipped (scene failed to load)"}
        checks["door_components_attached"] = {"passed": False, "detail": "Skipped (scene failed to load)"}

    all_passed = all(c["passed"] for c in checks.values())

    result = {
        "schema_version": "smoke-probe-050/v1",
        "checks": checks,
        "all_passed": all_passed,
    }
    print(SMOKE_RESULT_MARKER + json.dumps(result, sort_keys=True), flush=True)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Host-side parser (importable without bpy)
# ---------------------------------------------------------------------------

def parse_smoke_output(stdout: str) -> dict:
    """Extract the JSON result from smoke probe stdout.

    Searches for the SMOKE_RESULT= marker line, extracts and parses the JSON
    payload after the marker.

    Args:
        stdout: The full stdout text from the probe subprocess.

    Returns:
        The parsed JSON dict with keys: schema_version, checks, all_passed.

    Raises:
        ValueError: with 'smoke_parse_error' prefix when:
            - The SMOKE_RESULT= marker is not found in stdout
            - The JSON after the marker is malformed
    """
    marker_line: str | None = None
    for line in stdout.splitlines():
        if SMOKE_RESULT_MARKER in line:
            idx = line.index(SMOKE_RESULT_MARKER)
            marker_line = line[idx + len(SMOKE_RESULT_MARKER):]
            break

    if marker_line is None:
        raise ValueError(
            "smoke_parse_error: SMOKE_RESULT= marker not found in probe output"
        )

    try:
        data: dict[str, Any] = json.loads(marker_line)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"smoke_parse_error: invalid JSON after SMOKE_RESULT= marker: {exc}"
        ) from exc

    return data
