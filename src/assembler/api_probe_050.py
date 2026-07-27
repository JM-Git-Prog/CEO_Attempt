"""UPBGE 0.50 API Discovery Probe — script constant and host-side parser.

This module contains two distinct parts:

1. API_PROBE_SCRIPT: A string constant containing the headless introspection script
   that runs INSIDE UPBGE 0.50 via ``--background --python``. It discovers the
   component attachment and physics configuration APIs and prints a JSON report
   prefixed with ``PROBE_RESULT=``.

2. UPBGEComponentAPI dataclass + parse_probe_output(): Host-side code that parses
   the probe's stdout output into a structured capability report. This code runs
   in the normal Python host process (NOT inside UPBGE) and must NOT import ``bpy``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Marker used by both the probe script (emitter) and the parser (consumer).
# ---------------------------------------------------------------------------
PROBE_RESULT_MARKER = "PROBE_RESULT="

# ---------------------------------------------------------------------------
# Probe script — executed inside UPBGE 0.50 headless mode.
# Stored as a string constant so the runner can write it to a temp file.
# This script imports bpy at runtime (available inside UPBGE embedded Python).
# ---------------------------------------------------------------------------
API_PROBE_SCRIPT = r'''"""UPBGE 0.50 API Discovery Probe.

Executed headlessly inside UPBGE 0.50 to discover:
1. Component attachment API (RNA path or operator)
2. Physics configuration API (replacement for obj.game.physics_type)
3. Available bpy.types.Object properties related to UPBGE

Output: JSON report on stdout with PROBE_RESULT= prefix marker.
"""

import bpy
import json
import sys

PROBE_RESULT_MARKER = "PROBE_RESULT="


def _discover_component_api():
    """Check for component attachment mechanisms."""
    result = {
        "has_game_attr": hasattr(bpy.types.Object, "game"),
        "has_components_attr": False,
        "has_upbge_attr": False,
        "component_api_path": None,
        "component_add_method": None,
        "available_upbge_properties": [],
    }

    # Check all RNA properties for UPBGE-related names
    for prop in bpy.types.Object.bl_rna.properties:
        name = prop.identifier.lower()
        if any(kw in name for kw in ("game", "component", "upbge", "logic")):
            result["available_upbge_properties"].append(prop.identifier)

    # Check for direct component collection
    if hasattr(bpy.types.Object, "components"):
        result["has_components_attr"] = True
        result["component_api_path"] = "bpy.types.Object.components"

    if hasattr(bpy.types.Object, "upbge"):
        result["has_upbge_attr"] = True

    # Check game sub-property for components
    if result["has_game_attr"]:
        game_type = getattr(bpy.types, "GameObjectSettings", None)
        if game_type:
            if hasattr(game_type, "components"):
                result["component_api_path"] = "obj.game.components"
                result["component_add_method"] = "obj.game.components.new()"

    # Check for operators
    result["has_logic_ops"] = hasattr(bpy.ops, "logic")
    if result["has_logic_ops"]:
        logic_ops = [op for op in dir(bpy.ops.logic) if "component" in op.lower()]
        result["component_operators"] = logic_ops

    return result


def _discover_physics_api():
    """Check for physics configuration mechanisms."""
    result = {
        "has_game_physics": False,
        "physics_api_path": None,
        "physics_type_enum": [],
        "collision_bounds_enum": [],
    }

    if hasattr(bpy.types.Object, "game"):
        game_type = getattr(bpy.types, "GameObjectSettings", None)
        if game_type and hasattr(game_type, "physics_type"):
            result["has_game_physics"] = True
            result["physics_api_path"] = "obj.game.physics_type"

    # Check for alternative paths
    for prop in bpy.types.Object.bl_rna.properties:
        if "physics" in prop.identifier.lower():
            result.setdefault("alternative_physics_props", []).append(prop.identifier)

    return result


def main():
    report = {
        "schema_version": "upbge-api-probe/v1",
        "blender_version": list(bpy.app.version),
        "blender_version_string": bpy.app.version_string,
        "upbge_detected": "upbge" in bpy.app.version_string.lower()
                          or hasattr(bpy.types, "GameObjectSettings"),
        "component_api": _discover_component_api(),
        "physics_api": _discover_physics_api(),
    }
    print(PROBE_RESULT_MARKER + json.dumps(report, sort_keys=True), flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Host-side dataclass and parser (importable without bpy)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UPBGEComponentAPI:
    """Discovered UPBGE 0.50 API surface for component attachment."""

    has_game_attr: bool
    has_components_attr: bool
    component_api_path: str | None        # e.g., "obj.game.components" or "obj.components"
    component_add_method: str | None      # e.g., "obj.game.components.new()"
    has_logic_ops: bool
    physics_api_path: str | None          # e.g., "obj.game.physics_type"
    has_game_physics: bool
    blender_version: tuple[int, int, int]
    upbge_detected: bool
    fallback_required: bool               # True if no native component API found


def parse_probe_output(stdout: str) -> UPBGEComponentAPI:
    """Parse probe script stdout into a structured API report.

    Searches for the PROBE_RESULT= marker line, extracts and parses the JSON.
    Raises ValueError with 'probe_parse_error' reason code on malformed output.
    """
    # Search for the marker in (potentially noisy) stdout
    marker_line: str | None = None
    for line in stdout.splitlines():
        if PROBE_RESULT_MARKER in line:
            # Extract everything after the marker on this line
            idx = line.index(PROBE_RESULT_MARKER)
            marker_line = line[idx + len(PROBE_RESULT_MARKER):]
            break

    if marker_line is None:
        raise ValueError(
            "probe_parse_error: PROBE_RESULT= marker not found in probe output"
        )

    # Parse JSON payload
    try:
        data: dict[str, Any] = json.loads(marker_line)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"probe_parse_error: invalid JSON after PROBE_RESULT= marker: {exc}"
        ) from exc

    # Extract fields with safe access
    try:
        component_api: dict[str, Any] = data.get("component_api", {})
        physics_api: dict[str, Any] = data.get("physics_api", {})

        # Parse blender_version as a 3-int tuple
        raw_version = data.get("blender_version", [0, 0, 0])
        if not isinstance(raw_version, list) or len(raw_version) < 3:
            blender_version = (0, 0, 0)
        else:
            blender_version = (
                int(raw_version[0]),
                int(raw_version[1]),
                int(raw_version[2]),
            )

        has_game_attr = bool(component_api.get("has_game_attr", False))
        has_components_attr = bool(component_api.get("has_components_attr", False))
        component_api_path: str | None = component_api.get("component_api_path")
        component_add_method: str | None = component_api.get("component_add_method")
        has_logic_ops = bool(component_api.get("has_logic_ops", False))

        physics_api_path: str | None = physics_api.get("physics_api_path")
        has_game_physics = bool(physics_api.get("has_game_physics", False))

        upbge_detected = bool(data.get("upbge_detected", False))

        # fallback_required is True when no native component attachment mechanism found
        fallback_required = component_api_path is None

    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError(
            f"probe_parse_error: failed to extract fields from probe JSON: {exc}"
        ) from exc

    return UPBGEComponentAPI(
        has_game_attr=has_game_attr,
        has_components_attr=has_components_attr,
        component_api_path=component_api_path,
        component_add_method=component_add_method,
        has_logic_ops=has_logic_ops,
        physics_api_path=physics_api_path,
        has_game_physics=has_game_physics,
        blender_version=blender_version,
        upbge_detected=upbge_detected,
        fallback_required=fallback_required,
    )


def run_api_probe(upbge_path: str, timeout_s: float = 15.0) -> UPBGEComponentAPI:
    """Run the API probe inside UPBGE 0.50 and return the structured report.

    Args:
        upbge_path: Absolute path to the UPBGE executable (blender.exe)
        timeout_s: Maximum seconds to wait for probe completion (default 15.0)

    Returns:
        UPBGEComponentAPI with discovered API surface

    Raises:
        ValueError: with reason codes:
            - 'probe_timeout': probe took longer than timeout_s
            - 'probe_parse_error': output couldn't be parsed
            - 'version_mismatch': unexpected blender version detected
    """
    # Write the probe script to a temporary file
    temp_script_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="kiro-api-probe-",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(API_PROBE_SCRIPT)
            temp_script_path = tmp.name

        # Minimal environment to avoid interference (matches BoundedUPBGERuntimeSmokeRunner)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        }

        # Invoke UPBGE headlessly with the probe script
        command = [upbge_path, "--background", "--python", temp_script_path]

        try:
            completed = subprocess.run(
                command,
                env=environment,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("probe_timeout")
        except OSError as exc:
            raise ValueError(f"probe_parse_error: failed to execute UPBGE: {exc}") from exc

        # Parse stdout regardless of exit code (probe may print before crashing)
        stdout = completed.stdout.decode("utf-8", errors="replace")

        # parse_probe_output raises ValueError with 'probe_parse_error' on failure
        result = parse_probe_output(stdout)

        # Verify UPBGE was actually detected — if not, it's a version mismatch
        if not result.upbge_detected:
            raise ValueError("version_mismatch")

        return result

    finally:
        # Clean up the temporary script file
        if temp_script_path is not None:
            try:
                os.unlink(temp_script_path)
            except OSError:
                pass
