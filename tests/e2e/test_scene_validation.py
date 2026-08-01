"""Scene validation tests — 3D object count, position, and lighting verification.

Compares the live Three.js scene (via QA Bridge) against the WorldContract
to verify that all objects are present at the correct positions and that
lighting matches the WorldContract specification.

Uses the @pytest.mark.layer("scene") marker for 60s budget enforcement.

Requirements: 8.1–8.4, 9.1–9.3
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from tests.e2e.framework.qa_bridge import QABridge


# Default position tolerance in world units (Euclidean distance)
DEFAULT_POSITION_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _euclidean_distance(
    expected: dict[str, float], actual: dict[str, float]
) -> float:
    """Compute Euclidean distance between two 3D positions."""
    dx = expected["x"] - actual["x"]
    dy = expected["y"] - actual["y"]
    dz = expected["z"] - actual["z"]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _format_position(pos: dict[str, float]) -> str:
    """Format a position dict as a readable string."""
    return f"({pos['x']:.4f}, {pos['y']:.4f}, {pos['z']:.4f})"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.layer("scene")
class TestSceneValidation:
    """Scene validation test suite — verifies WorldContract compliance.

    These tests compare the live Three.js scene (queried through the QA
    Bridge) against the WorldContract data to ensure the compiled scene
    matches the spatial authority document.

    Requirements: 8.1–8.4
    """

    @pytest.mark.asyncio
    async def test_object_count_matches_world_contract(
        self,
        qa_bridge: QABridge,
        world_contract_instances: list[dict[str, Any]],
    ) -> None:
        """Verify that scene object count matches WorldContract ObjectInstance count.

        Compares qa_bridge.get_object_count() against the number of
        ObjectInstance entries in the WorldContract. On mismatch, reports
        which objects are missing from the scene or unexpected.

        Requirements: 8.1, 8.3
        """
        # Get the actual object count from the live scene
        actual_count = await qa_bridge.get_object_count()
        expected_count = len(world_contract_instances)

        if actual_count != expected_count:
            # Gather scene graph to identify missing/unexpected objects
            scene_graph = await qa_bridge.get_scene_graph()
            scene_ids = {
                node.get("objectId", node.get("object_id", ""))
                for node in scene_graph
            }
            contract_ids = {
                inst.get("object_id", inst.get("objectId", ""))
                for inst in world_contract_instances
            }

            missing = contract_ids - scene_ids
            unexpected = scene_ids - contract_ids

            # Build descriptive failure message
            lines = [
                f"Object count mismatch: expected {expected_count} "
                f"(WorldContract), got {actual_count} (scene).",
            ]
            if missing:
                missing_names = []
                for inst in world_contract_instances:
                    inst_id = inst.get("object_id", inst.get("objectId", ""))
                    if inst_id in missing:
                        name = inst.get("name", inst_id)
                        missing_names.append(f"  - {name} (id: {inst_id})")
                lines.append(f"Missing objects ({len(missing)}):")
                lines.extend(missing_names)

            if unexpected:
                lines.append(f"Unexpected objects ({len(unexpected)}):")
                for obj_id in sorted(unexpected):
                    lines.append(f"  - id: {obj_id}")

            pytest.fail("\n".join(lines))

    @pytest.mark.asyncio
    async def test_object_positions_within_tolerance(
        self,
        qa_bridge: QABridge,
        world_contract_instances: list[dict[str, Any]],
        position_tolerance: float,
    ) -> None:
        """Verify each object position is within tolerance of WorldContract.

        For each ObjectInstance in the WorldContract, queries the scene
        position via qa_bridge.get_object_position(object_id) and compares
        against the expected position using Euclidean distance.

        On failure, reports the object name, expected position, actual
        position, and distance delta.

        Requirements: 8.2, 8.4
        """
        failures: list[str] = []

        for instance in world_contract_instances:
            object_id = instance.get("object_id", instance.get("objectId", ""))
            name = instance.get("name", object_id)

            # Extract expected position from contract
            pos_data = instance.get("position", {})
            expected_pos = {
                "x": float(pos_data.get("x", 0.0)),
                "y": float(pos_data.get("y", 0.0)),
                "z": float(pos_data.get("z", 0.0)),
            }

            # Query actual position from live scene
            actual_pos = await qa_bridge.get_object_position(object_id)

            if actual_pos is None:
                failures.append(
                    f"  Object '{name}' (id: {object_id}): "
                    f"not found in scene (expected at {_format_position(expected_pos)})"
                )
                continue

            distance = _euclidean_distance(expected_pos, actual_pos)

            if distance > position_tolerance:
                failures.append(
                    f"  Object '{name}' (id: {object_id}):\n"
                    f"    Expected: {_format_position(expected_pos)}\n"
                    f"    Actual:   {_format_position(actual_pos)}\n"
                    f"    Delta:    {distance:.6f} world units "
                    f"(tolerance: {position_tolerance})"
                )

        if failures:
            header = (
                f"Position tolerance exceeded for {len(failures)} object(s) "
                f"(tolerance: {position_tolerance} world units):\n"
            )
            pytest.fail(header + "\n".join(failures))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def position_tolerance(e2e_config) -> float:
    """Configurable position tolerance for object position validation.

    Default: 0.01 world units (Euclidean distance).
    Can be overridden in e2e_config.yaml if a scene_validation section is added.
    """
    # Use default tolerance; could be made configurable via config in the future
    return DEFAULT_POSITION_TOLERANCE


@pytest.fixture
def world_contract_instances() -> list[dict[str, Any]]:
    """Provide WorldContract ObjectInstance data for scene validation.

    This fixture should be overridden or parametrized by the integration
    layer to supply the actual WorldContract instances for the scene under
    test. Returns a list of dictionaries matching the ObjectInstance schema:

        [
            {
                "object_id": "uuid-string",
                "name": "door_01",
                "position": {"x": 1.0, "y": 0.0, "z": -2.5},
                ...
            },
            ...
        ]

    For now, returns an empty list — the actual integration will populate
    this from the WorldContract loaded during the test session.
    """
    pytest.skip(
        "world_contract_instances fixture not provided. "
        "This test requires a running scene with a loaded WorldContract. "
        "Override this fixture in conftest.py or provide it via a session fixture."
    )
    return []  # pragma: no cover


@pytest.fixture
def qa_bridge() -> QABridge:
    """Provide a QABridge instance connected to the running page.

    This fixture should be overridden by the integration layer to supply
    a QABridge connected to a Playwright page loaded with ?qa=1.

    For now, skips — the actual integration will provide a connected bridge.
    """
    pytest.skip(
        "qa_bridge fixture not provided. "
        "This test requires a Playwright page loaded with ?qa=1. "
        "Override this fixture in conftest.py or provide it via a session fixture."
    )
    return None  # type: ignore  # pragma: no cover


# ---------------------------------------------------------------------------
# Lighting validation — Requirements 9.1, 9.2, 9.3
# ---------------------------------------------------------------------------


@dataclass
class LightingMismatch:
    """A single lighting parameter mismatch between expected and actual.

    Attributes:
        light_index: Index of the light in the lights array.
        parameter: Which parameter failed (type, position.x, color.r, intensity, etc).
        expected: The expected value from the WorldContract.
        actual: The actual value from the scene.
        delta: Computed difference (float for numeric, descriptive string for type).
    """
    light_index: int
    parameter: str
    expected: Any
    actual: Any
    delta: float | str


def hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """Convert a #RRGGBB hex string to normalized (r, g, b) in 0.0-1.0 range.

    Args:
        hex_color: A hex color string like '#ffffff' or '#FF8800'.

    Returns:
        Tuple of (r, g, b) floats in 0.0-1.0 range.
    """
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return (r, g, b)


def validate_lighting_against_contract(
    actual_lights: list[dict[str, Any]],
    expected_lights: list[dict[str, Any]],
    position_tolerance: float = 0.01,
    color_tolerance: float = 0.02,
    intensity_tolerance_pct: float = 0.05,
) -> list[LightingMismatch]:
    """Compare actual scene lights against WorldContract lighting specification.

    Matches lights by index order (same order as defined in the contract).

    Args:
        actual_lights: Lights returned by qa_bridge.get_lighting().
            Each dict has: type (str), position ({x,y,z}), color (#RRGGBB), intensity (float).
        expected_lights: Lights from WorldContract.lighting.lights (serialized).
            Each dict has: light_type (str), position ({x,y,z}), color (#RRGGBB), intensity (float).
        position_tolerance: Max absolute difference for each x/y/z component (default 0.01).
        color_tolerance: Max absolute difference per RGB component in 0.0-1.0 range (default 0.02).
        intensity_tolerance_pct: Max relative difference for intensity as fraction (default 0.05 = 5%).

    Returns:
        List of LightingMismatch instances describing all failures.
        Empty list means all lights match within tolerances.
    """
    mismatches: list[LightingMismatch] = []

    # Small epsilon to handle floating-point comparison at exact boundaries.
    # Without this, 1.01 - 1.0 = 0.010000000000000009 would fail the 0.01 tolerance.
    _FP_EPSILON = 1e-9

    for i, (expected, actual) in enumerate(zip(expected_lights, actual_lights)):
        # --- Type comparison (exact match) ---
        expected_type = expected.get("light_type", expected.get("type", ""))
        actual_type = actual.get("type", "")
        if expected_type != actual_type:
            mismatches.append(LightingMismatch(
                light_index=i,
                parameter="type",
                expected=expected_type,
                actual=actual_type,
                delta=f"type mismatch: '{expected_type}' != '{actual_type}'",
            ))

        # --- Position comparison (tolerance 0.01 per component) ---
        expected_pos = expected.get("position", {})
        actual_pos = actual.get("position", {})
        for axis in ("x", "y", "z"):
            exp_val = float(expected_pos.get(axis, 0.0))
            act_val = float(actual_pos.get(axis, 0.0))
            delta = abs(act_val - exp_val)
            if delta > position_tolerance + _FP_EPSILON:
                mismatches.append(LightingMismatch(
                    light_index=i,
                    parameter=f"position.{axis}",
                    expected=exp_val,
                    actual=act_val,
                    delta=delta,
                ))

        # --- Color comparison (tolerance 0.02 per RGB component) ---
        expected_color_hex = expected.get("color", "#000000")
        actual_color_hex = actual.get("color", "#000000")
        expected_rgb = hex_to_rgb(expected_color_hex)
        actual_rgb = hex_to_rgb(actual_color_hex)
        for channel_idx, channel_name in enumerate(("r", "g", "b")):
            exp_val = expected_rgb[channel_idx]
            act_val = actual_rgb[channel_idx]
            delta = abs(act_val - exp_val)
            if delta > color_tolerance + _FP_EPSILON:
                mismatches.append(LightingMismatch(
                    light_index=i,
                    parameter=f"color.{channel_name}",
                    expected=exp_val,
                    actual=act_val,
                    delta=delta,
                ))

        # --- Intensity comparison (5% relative tolerance) ---
        expected_intensity = float(expected.get("intensity", 1.0))
        actual_intensity = float(actual.get("intensity", 1.0))
        if expected_intensity == 0.0:
            # For zero intensity, use absolute comparison
            delta_val = abs(actual_intensity)
            if delta_val > 0.0:
                mismatches.append(LightingMismatch(
                    light_index=i,
                    parameter="intensity",
                    expected=expected_intensity,
                    actual=actual_intensity,
                    delta=delta_val,
                ))
        else:
            relative_delta = abs(actual_intensity - expected_intensity) / abs(expected_intensity)
            if relative_delta > intensity_tolerance_pct + _FP_EPSILON:
                mismatches.append(LightingMismatch(
                    light_index=i,
                    parameter="intensity",
                    expected=expected_intensity,
                    actual=actual_intensity,
                    delta=relative_delta,
                ))

    return mismatches


def format_lighting_mismatches(mismatches: list[LightingMismatch]) -> str:
    """Format lighting mismatches into a human-readable failure report.

    Reports the specific parameter, expected value, actual value, and computed
    delta for each mismatch as required by Requirement 9.3.

    Args:
        mismatches: List of LightingMismatch from validate_lighting_against_contract.

    Returns:
        Formatted multi-line string describing each mismatch.
    """
    lines = [f"Lighting validation failed with {len(mismatches)} mismatch(es):"]
    for m in mismatches:
        if isinstance(m.delta, float):
            delta_str = f"{m.delta:.6f}"
        else:
            delta_str = str(m.delta)
        lines.append(
            f"  Light[{m.light_index}] {m.parameter}: "
            f"expected={m.expected}, actual={m.actual}, delta={delta_str}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lighting validation test
# ---------------------------------------------------------------------------


@pytest.mark.layer("scene")
@pytest.mark.asyncio
async def test_lighting_matches_world_contract(
    qa_bridge: QABridge,
    world_contract_lighting: list[dict[str, Any]],
) -> None:
    """Validate that scene lighting matches the WorldContract specification.

    Compares each light's type, position, color, and intensity against
    the WorldContract lighting definition with tolerances:
    - Position: 0.01 per x/y/z component
    - Color: 0.02 per RGB component (normalized 0.0-1.0)
    - Intensity: 5% relative tolerance

    Reports specific parameter, expected value, actual value, and delta on failure.

    Requirements: 9.1, 9.2, 9.3
    """
    # Get actual lighting from the live scene
    actual_lights = await qa_bridge.get_lighting()

    # Get expected lighting from the WorldContract
    expected_lights = world_contract_lighting

    # Validate light count
    assert len(actual_lights) == len(expected_lights), (
        f"Light count mismatch: WorldContract defines {len(expected_lights)} light(s), "
        f"but scene contains {len(actual_lights)} light(s). "
        f"Expected light types: {[l.get('light_type', l.get('type', '?')) for l in expected_lights]}. "
        f"Actual light types: {[l.get('type', '?') for l in actual_lights]}."
    )

    # Validate each light's parameters within tolerances
    mismatches = validate_lighting_against_contract(
        actual_lights=actual_lights,
        expected_lights=expected_lights,
        position_tolerance=0.01,
        color_tolerance=0.02,
        intensity_tolerance_pct=0.05,
    )

    if mismatches:
        report = format_lighting_mismatches(mismatches)
        pytest.fail(report)


# ---------------------------------------------------------------------------
# Lighting fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def world_contract_lighting() -> list[dict[str, Any]]:
    """Provide WorldContract lighting data for lighting validation.

    This fixture should be overridden or parametrized by the integration
    layer to supply the actual WorldContract lighting config for the scene
    under test. Returns a list of light dictionaries matching the
    LightSource schema:

        [
            {
                "light_type": "point",
                "position": {"x": 2.0, "y": 3.5, "z": -1.0},
                "color": "#ff8800",
                "intensity": 1.5,
            },
            ...
        ]

    For now, skips — the actual integration will populate this from the
    WorldContract loaded during the test session.
    """
    pytest.skip(
        "world_contract_lighting fixture not provided. "
        "This test requires a running scene with a loaded WorldContract. "
        "Override this fixture in conftest.py or provide it via a session fixture."
    )
    return []  # pragma: no cover
