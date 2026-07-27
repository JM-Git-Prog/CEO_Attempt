"""UPBGE 0.50 Compile-Time Component Attachment.

Provides functions for attaching KX_PythonComponent instances to objects
and configuring physics at compile time using the API surface discovered
by the probe (see api_probe_050.py).

These functions accept ``bpy`` as a parameter — they do NOT import it at
module level — because they run inside UPBGE's embedded Python where bpy
is available, but the module must also be importable from the host process
for testing purposes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.upbge_runtime import PLAYER_COMPONENT_SOURCE, DOOR_COMPONENT_SOURCE_050

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Valid enum values (for validation)
# ---------------------------------------------------------------------------

VALID_PHYSICS_TYPES = frozenset({
    "CHARACTER",
    "STATIC",
    "DYNAMIC",
    "RIGID_BODY",
    "NO_COLLISION",
    "SENSOR",
})

VALID_COLLISION_SHAPES = frozenset({
    "CAPSULE",
    "BOX",
    "SPHERE",
    "CYLINDER",
    "CONE",
    "CONVEX_HULL",
    "TRIANGLE_MESH",
})


# ---------------------------------------------------------------------------
# _embed_component_source
# ---------------------------------------------------------------------------

def _embed_component_source(bpy: Any, module_name: str, source: str) -> str:
    """Embed component source as a Text datablock in the .blend file.

    Creates or replaces the Text datablock named ``module_name + ".py"``.

    Args:
        bpy: The Blender Python API module (passed in, not imported).
        module_name: Base name for the text datablock (e.g. "kiro_player_first_person").
        source: Full Python source code to embed.

    Returns:
        The text datablock name (e.g. "kiro_player_first_person.py").
    """
    text_name = module_name + ".py"
    existing = bpy.data.texts.get(text_name)
    if existing:
        bpy.data.texts.remove(existing)
    text = bpy.data.texts.new(text_name)
    text.write(source)
    return text_name


# ---------------------------------------------------------------------------
# _attach_component_050
# ---------------------------------------------------------------------------

def _attach_component_050(
    bpy: Any,
    obj: Any,
    component_class_name: str,
    text_datablock_name: str,
    args: dict[str, Any],
    api_report: UPBGEComponentAPI,
) -> bool:
    """Attach a KX_PythonComponent to an object using the discovered API.

    Tries the native component attachment path first (if discovered by the probe).
    Falls back to storing component metadata as custom ID properties on the object.

    Args:
        bpy: The Blender Python API module.
        obj: The Blender object to attach the component to.
        component_class_name: Name of the component class (e.g. "PlayerComponent").
        text_datablock_name: Name of the Text datablock containing the source.
        args: Dictionary of component arguments to pass at instantiation.
        api_report: The discovered API surface from the probe.

    Returns:
        True if native attachment succeeded, False if fallback was used.
    """
    # Derive the module name from the text datablock name (strip .py suffix)
    module_name = text_datablock_name
    if module_name.endswith(".py"):
        module_name = module_name[:-3]

    # --- Native path: use discovered component API ---
    if not api_report.fallback_required and api_report.component_api_path is not None:
        try:
            if api_report.component_api_path == "obj.game.components":
                # UPBGE 0.50 with obj.game.components API
                comp = obj.game.components.new(module_name, component_class_name)
                # Set args on the component if the API supports it
                if hasattr(comp, "properties"):
                    for key, value in args.items():
                        if key in comp.properties:
                            comp.properties[key] = value
                return True
            elif api_report.component_api_path == "bpy.types.Object.components":
                # Direct obj.components API
                comp = obj.components.new(module_name, component_class_name)
                if hasattr(comp, "properties"):
                    for key, value in args.items():
                        if key in comp.properties:
                            comp.properties[key] = value
                return True
        except (AttributeError, TypeError, RuntimeError):
            # Native path failed at runtime — fall through to fallback
            pass

    # --- Fallback path: store as custom ID properties ---
    obj["kiro_component_module"] = module_name
    obj["kiro_component_class"] = component_class_name
    obj["kiro_component_args"] = json.dumps(args)
    return False


# ---------------------------------------------------------------------------
# _configure_physics_050
# ---------------------------------------------------------------------------

def _configure_physics_050(
    bpy: Any,
    obj: Any,
    physics_type: str,
    collision_shape: str,
    mass: float,
    api_report: UPBGEComponentAPI,
) -> bool:
    """Configure physics on an object using the discovered API.

    Attempts to set physics type, collision bounds, and mass via the native
    RNA path discovered by the API probe. If the native physics API is
    unavailable or fails, stores the physics intent as custom ID properties
    for runtime bootstrap (graceful degradation).

    Args:
        bpy: The Blender Python API module (passed in, not imported).
        obj: The Blender object to configure physics on.
        physics_type: Physics type enum string (e.g. "CHARACTER", "STATIC",
            "DYNAMIC", "RIGID_BODY", "NO_COLLISION").
        collision_shape: Collision bounds shape (e.g. "CAPSULE", "BOX",
            "SPHERE", "CYLINDER", "CONE", "CONVEX_HULL", "TRIANGLE_MESH").
        mass: Object mass in kilograms (used for DYNAMIC/RIGID_BODY).
        api_report: The discovered API surface from the probe.

    Returns:
        True if physics was configured via the native RNA path.
        False if degraded (physics stored as custom properties only).
    """
    # --- Native path: use discovered physics RNA ---
    if api_report.has_game_physics and api_report.physics_api_path is not None:
        try:
            # Set physics type via obj.game.physics_type
            obj.game.physics_type = physics_type

            # Enable collision bounds and set shape
            obj.game.use_collision_bounds = True
            obj.game.collision_bounds_type = collision_shape

            # Set mass
            obj.game.mass = mass

            return True
        except AttributeError:
            # The API was reported as available by the probe, but the actual
            # object doesn't support it (e.g. the probe checked the type
            # definition but this specific object instance lacks the attribute).
            # Fall through to degradation path.
            pass

    # --- Degradation path: store intent as custom properties ---
    obj["kiro_physics_type"] = physics_type
    obj["kiro_collision_shape"] = collision_shape
    obj["kiro_mass"] = mass

    return False


# ---------------------------------------------------------------------------
# Bootstrap Component Source — used when native component API is unavailable
# ---------------------------------------------------------------------------

BOOTSTRAP_COMPONENT_SOURCE = r'''"""Bootstrap for component instantiation when native API is unavailable.

Reads kiro_component_* properties from objects and instantiates the
referenced KX_PythonComponent subclasses manually.
"""
import bge
import importlib
import json


def bootstrap():
    scene = bge.logic.getCurrentScene()
    for obj in scene.objects:
        module_name = obj.get("kiro_component_module")
        class_name = obj.get("kiro_component_class")
        if not module_name or not class_name:
            continue
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            args_json = obj.get("kiro_component_args", "{}")
            args = json.loads(args_json) if isinstance(args_json, str) else {}
            # Instantiate via UPBGE's runtime component API
            component = cls(obj)
            component.start(args)
            obj.components.append(component)
        except Exception as e:
            print(f"[kiro bootstrap] Failed to attach {class_name} to {obj.name}: {e}")


if __name__ == "__main__":
    bootstrap()
'''


# ---------------------------------------------------------------------------
# _configure_runtime_050
# ---------------------------------------------------------------------------

def _configure_runtime_050(
    bpy: Any,
    plan: dict,
    object_by_id: dict[str, Any],
    camera_obj: Any,
    api_report: UPBGEComponentAPI,
) -> Any:
    """UPBGE 0.50 component-based runtime configuration.

    Orchestrates the full compile-time setup of a walkable runtime:
    1. Embeds component source as Text datablocks
    2. Creates/finds the player mesh object with CHARACTER physics + CAPSULE
    3. Attaches PlayerComponent with configured args
    4. Parents camera to the player
    5. For each door binding: attaches DoorComponent with configured args
    6. If bootstrap fallback required: embeds kiro_component_bootstrap.py
    7. Saves runtime_candidate.blend on success
    8. On component failure: saves scene-only .blend (graceful degradation)

    Args:
        bpy: The Blender Python API module (passed in, not imported).
        plan: Runtime plan dict with 'interactions' and 'player_args' keys.
        object_by_id: Mapping of stable object IDs to bpy object references.
        camera_obj: The camera object to parent to the player.
        api_report: The discovered API surface from the probe.

    Returns:
        The player object.

    Raises:
        ValueError: On unrecoverable failures (e.g. no player can be created).
    """
    # --- Step 1: Embed component sources as Text datablocks ---
    player_text = _embed_component_source(
        bpy, "kiro_player_first_person", PLAYER_COMPONENT_SOURCE
    )
    door_text = _embed_component_source(
        bpy, "kiro_interaction_door", DOOR_COMPONENT_SOURCE_050
    )

    # --- Step 2: Embed bootstrap if fallback required ---
    if api_report.fallback_required:
        bootstrap_text = _embed_component_source(
            bpy, "kiro_component_bootstrap", BOOTSTRAP_COMPONENT_SOURCE
        )
        # Register bootstrap as a startup script for the game engine
        startup_text = bpy.data.texts.get("kiro_component_bootstrap.py")
        if startup_text is not None:
            startup_text.use_module = True

    # --- Step 3: Create or find player object ---
    player_obj = _find_or_create_player(bpy, object_by_id)

    # --- Step 4: Configure player physics (CHARACTER + CAPSULE) ---
    physics_ok = _configure_physics_050(
        bpy, player_obj, "CHARACTER", "CAPSULE", 80.0, api_report
    )
    if not physics_ok:
        player_obj["kiro_degradation_physics"] = (
            "CHARACTER physics stored as properties only — "
            "runtime bootstrap required"
        )

    # --- Step 5: Attach PlayerComponent to player ---
    player_args = _extract_player_args(plan)
    native = _attach_component_050(
        bpy, player_obj, "PlayerComponent", player_text, player_args, api_report
    )
    if not native:
        player_obj["kiro_degradation_component"] = (
            "PlayerComponent stored as ID properties — "
            "runtime bootstrap required"
        )

    # --- Step 6: Parent camera to player ---
    camera_obj.parent = player_obj

    # --- Step 7: Attach DoorComponents to door objects ---
    for interaction in plan.get("interactions", []):
        if interaction.get("kind") != "door":
            continue
        subject_id = interaction.get("subject_id")
        if not subject_id:
            continue
        door_obj = object_by_id.get(subject_id)
        if door_obj is None:
            logger.warning(
                "Door subject %r not found in object_by_id — skipping", subject_id
            )
            continue
        # Extract door parameters
        door_args = _extract_door_args(interaction)
        _attach_component_050(
            bpy, door_obj, "DoorComponent", door_text, door_args, api_report
        )
        # Configure door physics: STATIC + BOX, mass 0
        _configure_physics_050(bpy, door_obj, "STATIC", "BOX", 0.0, api_report)

    # --- Step 8: Save runtime_candidate.blend ---
    output_path = _resolve_output_path(bpy)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    except Exception as exc:
        # Graceful degradation: save scene-only .blend without game logic
        logger.error(
            "Failed to save runtime_candidate.blend: %s — "
            "attempting scene-only fallback save",
            exc,
        )
        player_obj["kiro_degradation_save"] = (
            f"Full save failed: {exc}. Scene-only fallback."
        )
        fallback_path = output_path.parent / "scene_only_fallback.blend"
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(fallback_path))
        except Exception as fallback_exc:
            raise ValueError(
                f"Unrecoverable save failure: primary={exc}, fallback={fallback_exc}"
            ) from fallback_exc

    return player_obj


# ---------------------------------------------------------------------------
# Helper functions for _configure_runtime_050
# ---------------------------------------------------------------------------

def _find_or_create_player(bpy: Any, object_by_id: dict[str, Any]) -> Any:
    """Find the player object in object_by_id or create a simple cube.

    Looks for an object with a 'player' key or creates a new cube mesh
    named 'KiroPlayer'.

    Returns:
        The player Blender object.
    """
    # Check for an existing player object by common conventions
    for key in ("player", "Player", "kiro_player"):
        if key in object_by_id:
            return object_by_id[key]

    # No player found — create a simple cube mesh
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 1.0))
    player_obj = bpy.context.active_object
    player_obj.name = "KiroPlayer"
    player_obj.scale = (0.4, 0.4, 0.9)  # Approximate capsule proportions
    return player_obj


def _extract_player_args(plan: dict) -> dict[str, Any]:
    """Extract player component args from the plan dict.

    Falls back to sensible defaults if plan doesn't contain player_args.
    """
    defaults = {
        "move_speed": 4.0,
        "look_speed": 0.0025,
        "gravity": 9.81,
        "max_grab_distance": 3.0,
        "grab_hold_distance": 1.5,
    }
    player_args = plan.get("player_args", {})
    if isinstance(player_args, dict):
        return {**defaults, **player_args}
    return defaults


def _extract_door_args(interaction: dict) -> dict[str, Any]:
    """Extract door component args from an interaction dict.

    Handles both list-of-tuples and dict formats for parameters.
    """
    defaults = {
        "open_angle_deg": 90.0,
        "speed_deg_s": 120.0,
        "initially_open": False,
    }
    params = interaction.get("parameters", [])
    if isinstance(params, dict):
        return {**defaults, **params}
    if isinstance(params, (list, tuple)):
        # Handle list of (key, value) tuples
        param_dict = {}
        for item in params:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                param_dict[item[0]] = item[1]
        return {**defaults, **param_dict}
    return defaults


def _resolve_output_path(bpy: Any) -> Path:
    """Determine the output path for runtime_candidate.blend.

    Uses the current .blend directory if available, otherwise falls back
    to the current working directory.
    """
    current_blend = bpy.data.filepath
    if current_blend:
        return Path(current_blend).parent / "runtime_candidate.blend"
    return Path.cwd() / "runtime_candidate.blend"
