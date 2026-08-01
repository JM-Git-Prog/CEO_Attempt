"""
Property-based tests for Wave 0 unified pipeline models.

Tests JSON round-trip serialization, CameraContract immutability,
and WorldContract hash stability using Hypothesis.

**Validates: Requirements 29.1, 29.2, 29.3, 29.4**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, assume
from hypothesis import strategies as st

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.world_contract import (
    WorldContract,
    ObjectInstance,
    Relationship,
    LightingConfig,
    LightSource,
    Vec3,
    Quaternion,
    MaterialIntent,
    AssetBinding,
    compute_hash,
    serialize,
    finalize,
    verify_hash,
)
from src.unified_pipeline.models import (
    Brief,
    Atmosphere,
    Era,
    Palette,
    ManifestObject,
    GameConcept,
    RealCapability,
)
from src.unified_pipeline.modes import (
    GameOverlay,
    RealOverlay,
    ModeState,
    Mode,
)


# ---------------------------------------------------------------------------
# Hypothesis strategies for generating random model instances
# ---------------------------------------------------------------------------

def _finite_floats(min_value: float = -1e6, max_value: float = 1e6):
    """Strategy for finite, non-NaN floats within a sensible range."""
    return st.floats(
        min_value=min_value,
        max_value=max_value,
        allow_nan=False,
        allow_infinity=False,
    )


def _positive_floats(min_value: float = 0.001, max_value: float = 1e4):
    """Strategy for positive finite floats."""
    return st.floats(
        min_value=min_value,
        max_value=max_value,
        allow_nan=False,
        allow_infinity=False,
    )


@st.composite
def camera_contracts(draw):
    """Generate random CameraContract instances."""
    position = (
        draw(_finite_floats(-100, 100)),
        draw(_finite_floats(-100, 100)),
        draw(_finite_floats(-100, 100)),
    )
    target = (
        draw(_finite_floats(-100, 100)),
        draw(_finite_floats(-100, 100)),
        draw(_finite_floats(-100, 100)),
    )
    up = (
        draw(_finite_floats(-1, 1)),
        draw(_finite_floats(-1, 1)),
        draw(_finite_floats(-1, 1)),
    )
    vfov = draw(_positive_floats(10.0, 170.0))
    aspect = draw(_positive_floats(0.1, 10.0))
    near = draw(_positive_floats(0.001, 1.0))
    far = draw(_positive_floats(10.0, 10000.0))
    raster_width = draw(st.integers(min_value=64, max_value=8192))
    raster_height = draw(st.integers(min_value=64, max_value=8192))

    return CameraContract(
        position=position,
        target=target,
        up=up,
        vfov=vfov,
        aspect=aspect,
        near=near,
        far=far,
        raster_width=raster_width,
        raster_height=raster_height,
    )


@st.composite
def vec3s(draw):
    """Generate random Vec3 instances."""
    return Vec3(
        x=draw(_finite_floats()),
        y=draw(_finite_floats()),
        z=draw(_finite_floats()),
    )


@st.composite
def quaternions(draw):
    """Generate random Quaternion instances."""
    return Quaternion(
        x=draw(_finite_floats(-1, 1)),
        y=draw(_finite_floats(-1, 1)),
        z=draw(_finite_floats(-1, 1)),
        w=draw(_finite_floats(-1, 1)),
    )


@st.composite
def material_intents(draw):
    """Generate random MaterialIntent instances."""
    return MaterialIntent(
        base_color=draw(st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)),
        metallic=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        roughness=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        normal_map_ref=draw(st.text(alphabet=st.characters(whitelist_categories=("L", "N")), max_size=20)),
        pass_level=draw(st.integers(min_value=1, max_value=2)),
    )


@st.composite
def asset_bindings(draw):
    """Generate random AssetBinding instances."""
    return AssetBinding(
        asset_id=draw(st.text(alphabet="0123456789abcdef", min_size=8, max_size=64)),
        mesh_path=draw(st.text(alphabet=st.characters(whitelist_categories=("L", "N", "P")), max_size=50)),
        triangle_count=draw(st.integers(min_value=0, max_value=1000000)),
        vertex_count=draw(st.integers(min_value=0, max_value=500000)),
        generator=draw(st.sampled_from(["hunyuan3d", "trellis2", "placeholder", ""])),
    )


@st.composite
def object_instances(draw):
    """Generate random ObjectInstance instances (world_contract.py version)."""
    return ObjectInstance(
        object_id=draw(st.uuids().map(str)),
        name=draw(st.text(alphabet=st.characters(whitelist_categories=("L", "N", "Z")), min_size=1, max_size=30)),
        position=draw(vec3s()),
        rotation=draw(quaternions()),
        scale=draw(vec3s()),
        asset_binding=draw(asset_bindings()),
        physics_intent=draw(st.sampled_from(["static", "dynamic", "kinematic", "trigger"])),
        material_intent=draw(material_intents()),
        semantic_label=draw(st.text(alphabet=st.characters(whitelist_categories=("L",)), max_size=20)),
        is_architectural=draw(st.booleans()),
    )


@st.composite
def relationships(draw):
    """Generate random Relationship instances."""
    return Relationship(
        source_id=draw(st.uuids().map(str)),
        target_id=draw(st.uuids().map(str)),
        relationship_type=draw(st.sampled_from(["parent_child", "containment", "adjacency", "support"])),
        metadata=draw(st.text(max_size=50)),
    )


@st.composite
def light_sources(draw):
    """Generate random LightSource instances."""
    return LightSource(
        light_id=draw(st.uuids().map(str)),
        light_type=draw(st.sampled_from(["point", "directional", "spot", "area"])),
        position=draw(vec3s()),
        color=draw(st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)),
        intensity=draw(_positive_floats(0.01, 100.0)),
        temperature=draw(_positive_floats(1000.0, 12000.0)),
        cast_shadows=draw(st.booleans()),
    )


@st.composite
def lighting_configs(draw):
    """Generate random LightingConfig instances."""
    lights = draw(st.lists(light_sources(), min_size=0, max_size=5))
    return LightingConfig(
        ambient_color=draw(st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)),
        ambient_intensity=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        lights=tuple(lights),
    )


@st.composite
def world_contracts(draw):
    """Generate random WorldContract instances."""
    instances = draw(st.lists(object_instances(), min_size=0, max_size=5))
    rels = draw(st.lists(relationships(), min_size=0, max_size=3))
    return WorldContract(
        plan_revision=draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)),
        camera_hash=draw(st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)),
        room_shell_ref=draw(st.text(alphabet=st.characters(whitelist_categories=("L", "N", "P")), max_size=40)),
        instances=tuple(instances),
        relationships=tuple(rels),
        lighting=draw(lighting_configs()),
        contract_id=draw(st.uuids().map(str)),
        created_at=draw(st.text(alphabet="0123456789-T:Z", max_size=25)),
    )


# --- Strategies for Brief sub-models ---

@st.composite
def atmospheres(draw):
    """Generate random Atmosphere instances."""
    return Atmosphere(
        mood=draw(st.text(max_size=30)),
        lighting_direction=draw(st.sampled_from(["warm", "cool", "neutral", "dramatic", ""])),
        time_of_day=draw(st.sampled_from(["morning", "afternoon", "evening", "night", ""])),
    )


@st.composite
def eras(draw):
    """Generate random Era instances."""
    exclusions = draw(st.lists(st.text(max_size=20), max_size=4))
    return Era(
        period=draw(st.text(min_size=1, max_size=20)),
        style_exclusions=tuple(exclusions),
    )


@st.composite
def palettes(draw):
    """Generate random Palette instances."""
    finishes = draw(st.lists(st.text(max_size=15), max_size=4))
    return Palette(
        primary=draw(st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)),
        accent=draw(st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)),
        material_finishes=tuple(finishes),
    )


@st.composite
def manifest_objects(draw):
    """Generate random ManifestObject instances."""
    return ManifestObject(
        id=draw(st.uuids().map(str)),
        name=draw(st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=20)),
        role=draw(st.sampled_from(["furniture", "appliance", "decor", "fixture", "architectural"])),
        count=draw(st.integers(min_value=1, max_value=5)),
        material_hint=draw(st.text(max_size=15)),
        is_architectural=draw(st.booleans()),
    )


@st.composite
def game_concepts(draw):
    """Generate random GameConcept instances."""
    return GameConcept(
        theme=draw(st.text(max_size=30)),
        mechanics=draw(st.text(max_size=50)),
        scoring=draw(st.text(max_size=30)),
        win_condition=draw(st.text(max_size=50)),
    )


@st.composite
def real_capabilities(draw):
    """Generate random RealCapability instances."""
    return RealCapability(
        tool_type=draw(st.sampled_from(["inbox", "calendar", "shell", "documents", "inference", ""])),
        surface_binding=draw(st.text(max_size=20)),
        read_only_v1=True,
    )


@st.composite
def briefs(draw):
    """Generate random Brief instances matching actual models.py interface."""
    objects = draw(st.lists(manifest_objects(), min_size=1, max_size=6))
    caps = draw(st.lists(real_capabilities(), max_size=3))
    return Brief(
        room_purpose=draw(st.text(min_size=1, max_size=50)),
        atmosphere=draw(atmospheres()),
        era=draw(eras()),
        palette=draw(palettes()),
        object_manifest=tuple(objects),
        game_concept=draw(game_concepts()),
        real_capabilities=tuple(caps),
        success_criteria=draw(st.text(max_size=100)),
        provenance=draw(st.dictionaries(
            keys=st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=10),
            values=st.text(max_size=30),
            max_size=3,
        )),
    )


# --- Strategies for modes ---

@st.composite
def game_overlays(draw):
    """Generate random GameOverlay instances matching actual modes.py interface."""
    bindings = draw(st.dictionaries(
        keys=st.uuids().map(str),
        values=st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=20),
        min_size=0,
        max_size=5,
    ))
    scoring = draw(st.dictionaries(
        keys=st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=10),
        values=st.integers(min_value=0, max_value=100),
        max_size=3,
    ))
    return GameOverlay(
        rules=draw(st.text(max_size=100)),
        scoring=scoring,
        win_condition=draw(st.text(max_size=50)),
        object_role_bindings=bindings,
    )


@st.composite
def real_overlays(draw):
    """Generate random RealOverlay instances matching actual modes.py interface."""
    bindings = draw(st.dictionaries(
        keys=st.uuids().map(str),
        values=st.fixed_dictionaries({
            "tool_type": st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=15),
            "surface_binding": st.text(max_size=20),
            "read_only": st.just(True),
        }),
        min_size=0,
        max_size=5,
    ))
    return RealOverlay(
        tool_bindings=bindings,
        read_only=True,
    )


# ---------------------------------------------------------------------------
# Property Tests: CameraContract JSON round-trip
# **Validates: Requirement 29.2**
# ---------------------------------------------------------------------------

class TestCameraContractRoundTrip:
    """CameraContract serializes and deserializes losslessly."""

    @given(contract=camera_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_json_roundtrip(self, contract: CameraContract):
        """to_dict() → from_dict() produces an equivalent CameraContract.

        **Validates: Requirements 29.2, 29.3**
        """
        serialized = contract.to_dict()
        restored = CameraContract.from_dict(serialized)

        assert restored.position == contract.position
        assert restored.target == contract.target
        assert restored.up == contract.up
        assert restored.vfov == contract.vfov
        assert restored.aspect == contract.aspect
        assert restored.near == contract.near
        assert restored.far == contract.far
        assert restored.raster_width == contract.raster_width
        assert restored.raster_height == contract.raster_height

    @given(contract=camera_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_hash_preserved_after_roundtrip(self, contract: CameraContract):
        """Hash is identical after round-tripping through dict.

        **Validates: Requirements 29.2**
        """
        original_hash = contract.compute_hash()
        restored = CameraContract.from_dict(contract.to_dict())
        assert restored.compute_hash() == original_hash


# ---------------------------------------------------------------------------
# Property Tests: CameraContract immutability
# **Validates: Requirement 6.3**
# ---------------------------------------------------------------------------

class TestCameraContractImmutability:
    """CameraContract is immutable — mutation raises AttributeError."""

    @given(contract=camera_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_setattr_raises(self, contract: CameraContract):
        """Any attempt to set an attribute raises AttributeError (or subclass).

        **Validates: Requirements 29.1, 6.3**

        Note: Python 3.13 frozen dataclasses raise FrozenInstanceError
        (a subclass of AttributeError) from generated __setattr__.
        """
        with pytest.raises((AttributeError, TypeError)):
            contract.position = (0.0, 0.0, 0.0)  # type: ignore[misc]

    @given(contract=camera_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_delattr_raises(self, contract: CameraContract):
        """Any attempt to delete an attribute raises AttributeError (or subclass).

        **Validates: Requirements 29.1, 6.3**
        """
        with pytest.raises((AttributeError, TypeError)):
            del contract.position  # type: ignore[misc]

    def test_specific_mutation_fields(self):
        """Verify multiple fields cannot be mutated.

        **Validates: Requirements 29.1, 6.3**
        """
        cam = CameraContract(position=(1.0, 2.0, 3.0), target=(0.0, 0.0, 0.0))
        fields_to_try = ["position", "target", "up", "vfov", "aspect", "near", "far"]
        for field_name in fields_to_try:
            with pytest.raises((AttributeError, TypeError)):
                setattr(cam, field_name, "anything")


# ---------------------------------------------------------------------------
# Property Tests: WorldContract JSON round-trip
# **Validates: Requirements 29.2, 29.3**
# ---------------------------------------------------------------------------

class TestWorldContractRoundTrip:
    """WorldContract serializes and deserializes losslessly."""

    @given(contract=world_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_json_roundtrip(self, contract: WorldContract):
        """to_dict() → from_dict() produces an equivalent WorldContract.

        **Validates: Requirements 29.2, 29.3**
        """
        serialized = contract.to_dict()
        restored = WorldContract.from_dict(serialized)

        assert restored.plan_revision == contract.plan_revision
        assert restored.camera_hash == contract.camera_hash
        assert restored.room_shell_ref == contract.room_shell_ref
        assert restored.contract_id == contract.contract_id
        assert restored.created_at == contract.created_at
        assert restored.contract_hash == contract.contract_hash

        # Instance-level round-trip
        assert len(restored.instances) == len(contract.instances)
        for orig, rest in zip(contract.instances, restored.instances):
            assert rest.object_id == orig.object_id
            assert rest.name == orig.name
            assert rest.position.x == orig.position.x
            assert rest.position.y == orig.position.y
            assert rest.position.z == orig.position.z
            assert rest.physics_intent == orig.physics_intent
            assert rest.is_architectural == orig.is_architectural

        # Relationship round-trip
        assert len(restored.relationships) == len(contract.relationships)
        for orig, rest in zip(contract.relationships, restored.relationships):
            assert rest.source_id == orig.source_id
            assert rest.target_id == orig.target_id
            assert rest.relationship_type == orig.relationship_type

        # Lighting round-trip
        assert restored.lighting.ambient_color == contract.lighting.ambient_color
        assert restored.lighting.ambient_intensity == contract.lighting.ambient_intensity
        assert len(restored.lighting.lights) == len(contract.lighting.lights)


# ---------------------------------------------------------------------------
# Property Tests: WorldContract hash stability
# **Validates: Requirements 19.2, 29.2**
# ---------------------------------------------------------------------------

class TestWorldContractHashStability:
    """WorldContract hash is deterministic — same data always produces same hash."""

    @given(contract=world_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_hash_stable_across_calls(self, contract: WorldContract):
        """compute_hash() called twice on the same contract yields the same result.

        **Validates: Requirements 19.2, 29.2**
        """
        hash1 = compute_hash(contract)
        hash2 = compute_hash(contract)
        assert hash1 == hash2

    @given(contract=world_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_serialize_twice_same_hash(self, contract: WorldContract):
        """Serializing the same contract twice produces the same canonical JSON.

        **Validates: Requirements 19.2, 29.2**
        """
        json1 = serialize(contract)
        json2 = serialize(contract)
        assert json1 == json2

    @given(contract=world_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_hash_stable_after_roundtrip(self, contract: WorldContract):
        """Hash computed before and after dict round-trip is identical.

        **Validates: Requirements 19.2, 29.2**
        """
        hash_before = compute_hash(contract)
        restored = WorldContract.from_dict(contract.to_dict())
        hash_after = compute_hash(restored)
        assert hash_before == hash_after

    @given(contract=world_contracts())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_finalize_produces_verifiable_hash(self, contract: WorldContract):
        """finalize() sets a hash that passes verification.

        **Validates: Requirements 19.2, 19.4**
        """
        finalized = finalize(contract)
        assert finalized.contract_hash != ""
        assert verify_hash(finalized) is True


# ---------------------------------------------------------------------------
# Property Tests: WorldContract hash changes on modification
# **Validates: Requirement 29.2**
# ---------------------------------------------------------------------------

class TestWorldContractHashSensitivity:
    """WorldContract hash changes when data changes."""

    @given(contract=world_contracts(), new_revision=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20
    ))
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_different_plan_revision_different_hash(
        self, contract: WorldContract, new_revision: str
    ):
        """Changing plan_revision changes the hash.

        **Validates: Requirements 19.3, 29.2**
        """
        assume(new_revision != contract.plan_revision)

        original_hash = compute_hash(contract)
        modified = WorldContract.from_dict(
            {**contract.to_dict(), "plan_revision": new_revision}
        )
        modified_hash = compute_hash(modified)
        assert original_hash != modified_hash


# ---------------------------------------------------------------------------
# Property Tests: Brief JSON round-trip
# **Validates: Requirements 29.3, 29.4**
# ---------------------------------------------------------------------------

class TestBriefRoundTrip:
    """Brief serializes and deserializes losslessly."""

    @given(brief=briefs())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_json_roundtrip(self, brief: Brief):
        """to_dict() → from_dict() produces an equivalent Brief.

        **Validates: Requirements 29.3, 29.4**
        """
        serialized = brief.to_dict()
        restored = Brief.from_dict(serialized)

        assert restored.room_purpose == brief.room_purpose
        assert restored.atmosphere.mood == brief.atmosphere.mood
        assert restored.atmosphere.lighting_direction == brief.atmosphere.lighting_direction
        assert restored.atmosphere.time_of_day == brief.atmosphere.time_of_day
        assert restored.era.period == brief.era.period
        assert restored.era.style_exclusions == brief.era.style_exclusions
        assert restored.palette.primary == brief.palette.primary
        assert restored.palette.accent == brief.palette.accent
        assert restored.palette.material_finishes == brief.palette.material_finishes
        assert len(restored.object_manifest) == len(brief.object_manifest)
        for orig, rest in zip(brief.object_manifest, restored.object_manifest):
            assert rest.id == orig.id
            assert rest.name == orig.name
            assert rest.role == orig.role
            assert rest.count == orig.count
            assert rest.is_architectural == orig.is_architectural
        assert restored.game_concept.theme == brief.game_concept.theme
        assert restored.game_concept.win_condition == brief.game_concept.win_condition
        assert restored.success_criteria == brief.success_criteria
        assert restored.provenance == brief.provenance


# ---------------------------------------------------------------------------
# Property Tests: GameOverlay JSON round-trip
# **Validates: Requirements 29.3, 29.4**
# ---------------------------------------------------------------------------

class TestGameOverlayRoundTrip:
    """GameOverlay serializes and deserializes losslessly."""

    @given(overlay=game_overlays())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_json_roundtrip(self, overlay: GameOverlay):
        """to_dict() → from_dict() produces an equivalent GameOverlay.

        **Validates: Requirements 29.3, 29.4**
        """
        serialized = overlay.to_dict()
        restored = GameOverlay.from_dict(serialized)

        assert restored.rules == overlay.rules
        assert restored.scoring == overlay.scoring
        assert restored.win_condition == overlay.win_condition
        assert restored.object_role_bindings == overlay.object_role_bindings


# ---------------------------------------------------------------------------
# Property Tests: RealOverlay JSON round-trip
# **Validates: Requirements 29.3, 29.4**
# ---------------------------------------------------------------------------

class TestRealOverlayRoundTrip:
    """RealOverlay serializes and deserializes losslessly."""

    @given(overlay=real_overlays())
    @settings(max_examples=15, suppress_health_check=[HealthCheck.data_too_large])
    def test_json_roundtrip(self, overlay: RealOverlay):
        """to_dict() → from_dict() produces an equivalent RealOverlay.

        **Validates: Requirements 29.3, 29.4**
        """
        serialized = overlay.to_dict()
        restored = RealOverlay.from_dict(serialized)

        assert restored.tool_bindings == overlay.tool_bindings
        assert restored.read_only == overlay.read_only
