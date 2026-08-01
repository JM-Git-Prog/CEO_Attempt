"""
Tests for WorldContract canonical serialization, hashing, and verification.

Validates Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6
"""

import json
import uuid
from dataclasses import replace

import pytest

from src.unified_pipeline.world_contract import (
    AssetBinding,
    EventStatus,
    LightingConfig,
    LightingContractError,
    LightSource,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Relationship,
    Vec3,
    WorldContract,
    add_instance,
    add_relationship,
    bind_camera_hash,
    bind_plan_revision,
    compute_hash,
    finalize,
    make_final_event,
    make_provisional_event,
    serialize,
    set_lighting,
    verify_hash,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_instance(name: str = "table", object_id: str = "") -> ObjectInstance:
    """Create a test object instance."""
    return ObjectInstance(
        object_id=object_id or str(uuid.uuid4()),
        name=name,
        position=Vec3(1.0, 0.0, 2.0),
        rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
        scale=Vec3(1.0, 1.0, 1.0),
        asset_binding=AssetBinding(
            asset_id="abc123",
            mesh_path="meshes/table.glb",
            triangle_count=5000,
            vertex_count=2500,
            generator="hunyuan3d",
        ),
        physics_intent="dynamic",
        material_intent=MaterialIntent(
            base_color="#8B4513",
            metallic=0.0,
            roughness=0.8,
            normal_map_ref="",
            pass_level=1,
        ),
        semantic_label="furniture/table",
        is_architectural=False,
    )


def _make_contract() -> WorldContract:
    """Create a populated test contract."""
    obj_id = str(uuid.uuid4())
    instance = _make_instance("table", obj_id)
    light = LightSource(
        light_id="light-1",
        light_type="point",
        position=Vec3(2.0, 2.4, 2.0),
        color="#fff5e0",
        intensity=1.5,
        temperature=4000.0,
        cast_shadows=True,
    )
    lighting = LightingConfig(
        ambient_color="#1a1a2e",
        ambient_intensity=0.3,
        lights=(light,),
    )
    relationship = Relationship(
        source_id=obj_id,
        target_id="room-floor",
        relationship_type="support",
    )
    return WorldContract(
        plan_revision="rev-3",
        camera_hash="sha256:abcdef1234567890",
        room_shell_ref="shells/kitchen.glb",
        instances=(instance,),
        relationships=(relationship,),
        lighting=lighting,
        contract_id="test-contract-001",
        created_at="2026-07-30T12:00:00Z",
    )


# ---------------------------------------------------------------------------
# Test: Deterministic serialization (Req 19.2)
# ---------------------------------------------------------------------------

class TestSerialization:
    """Req 19.2: Deterministic serialization."""

    def test_serialize_produces_valid_json(self):
        contract = _make_contract()
        result = serialize(contract)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "plan_revision" in parsed

    def test_serialize_is_deterministic(self):
        """Serializing the same contract twice produces identical output."""
        contract = _make_contract()
        s1 = serialize(contract)
        s2 = serialize(contract)
        assert s1 == s2

    def test_serialize_uses_sorted_keys(self):
        """Keys are sorted alphabetically in the output."""
        contract = _make_contract()
        result = serialize(contract)
        # The top-level keys should appear in sorted order
        parsed = json.loads(result)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_serialize_uses_compact_separators(self):
        """No spaces in separators (compact format)."""
        contract = _make_contract()
        result = serialize(contract)
        # Compact format has no space after : or ,
        assert ": " not in result
        assert ", " not in result

    def test_round_trip(self):
        """to_dict → from_dict produces equivalent contract."""
        contract = _make_contract()
        data = contract.to_dict()
        reconstructed = WorldContract.from_dict(data)
        assert serialize(contract) == serialize(reconstructed)

    def test_incomplete_lighting_never_receives_consumer_defaults(self):
        """Req 22.5: omitted authoritative lighting fields fail closed."""
        for field_name in (
            "light_id", "light_type", "position", "color", "intensity",
            "temperature", "cast_shadows",
        ):
            payload = _make_contract().to_dict()
            del payload["lighting"]["lights"][0][field_name]
            with pytest.raises(LightingContractError, match="missing authoritative fields"):
                WorldContract.from_dict(payload)

        for field_name in ("ambient_color", "ambient_intensity", "lights"):
            payload = _make_contract().to_dict()
            del payload["lighting"][field_name]
            with pytest.raises(LightingContractError, match="missing authoritative fields"):
                WorldContract.from_dict(payload)


# ---------------------------------------------------------------------------
# Test: SHA-256 hashing (Req 19.2, 19.3)
# ---------------------------------------------------------------------------

class TestHashing:
    """Req 19.2, 19.3: SHA-256 hash computation."""

    def test_compute_hash_returns_hex_string(self):
        contract = _make_contract()
        h = compute_hash(contract)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex is 64 chars
        # All hex chars
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_is_stable(self):
        """Same contract always produces the same hash."""
        contract = _make_contract()
        h1 = compute_hash(contract)
        h2 = compute_hash(contract)
        assert h1 == h2

    def test_hash_changes_with_plan_revision(self):
        """Req 19.3: hash binds plan revision."""
        contract = _make_contract()
        h1 = compute_hash(contract)
        modified = bind_plan_revision(contract, "rev-4")
        h2 = compute_hash(modified)
        assert h1 != h2

    def test_hash_changes_with_camera_hash(self):
        """Req 19.3: hash binds camera."""
        contract = _make_contract()
        h1 = compute_hash(contract)
        modified = bind_camera_hash(contract, "sha256:different")
        h2 = compute_hash(modified)
        assert h1 != h2

    def test_hash_changes_with_instance_transform(self):
        """Req 19.3: hash binds transforms."""
        contract = _make_contract()
        h1 = compute_hash(contract)
        # Add a new instance with different position
        new_inst = _make_instance("chair", str(uuid.uuid4()))
        modified = add_instance(contract, new_inst)
        h2 = compute_hash(modified)
        assert h1 != h2

    def test_hash_changes_with_relationship(self):
        """Req 19.3: hash binds relationships."""
        contract = _make_contract()
        h1 = compute_hash(contract)
        rel = Relationship(
            source_id="obj-a",
            target_id="obj-b",
            relationship_type="containment",
        )
        modified = add_relationship(contract, rel)
        h2 = compute_hash(modified)
        assert h1 != h2

    def test_hash_changes_with_exact_lighting_values(self):
        """Req 19.3/22.5: positions, temperature, and shadow intent are hash-bound."""
        contract = _make_contract()
        source = contract.lighting.lights[0]
        changes = (
            replace(source, position=Vec3(2.125, 2.4, 2.0)),
            replace(source, color="#ffe8cc"),
            replace(source, intensity=1.625),
            replace(source, temperature=4100.0),
            replace(source, cast_shadows=False),
        )
        for changed_source in changes:
            changed = replace(
                contract,
                lighting=replace(contract.lighting, lights=(changed_source,)),
            )
            assert compute_hash(changed) != compute_hash(contract)


# ---------------------------------------------------------------------------
# Test: Hash verification (Req 19.4)
# ---------------------------------------------------------------------------

class TestVerification:
    """Req 19.4: No artifact claims final status without valid hash."""

    def test_verify_hash_passes_on_finalized_contract(self):
        contract = _make_contract()
        finalized = finalize(contract)
        assert verify_hash(finalized)

    def test_verify_hash_fails_on_empty_hash(self):
        contract = _make_contract()
        assert not verify_hash(contract)

    def test_verify_hash_fails_on_tampered_contract(self):
        """If the contract is modified after finalization, verification fails."""
        contract = _make_contract()
        finalized = finalize(contract)
        # Tamper by changing plan_revision but keeping old hash
        tampered_data = finalized.to_dict()
        tampered_data["plan_revision"] = "rev-999"
        # Keep the old hash
        tampered = WorldContract.from_dict(tampered_data)
        assert not verify_hash(tampered)

    def test_finalize_sets_hash(self):
        contract = _make_contract()
        assert contract.contract_hash == ""
        finalized = finalize(contract)
        assert finalized.contract_hash != ""
        assert len(finalized.contract_hash) == 64


# ---------------------------------------------------------------------------
# Test: Binding functions (Req 19.1)
# ---------------------------------------------------------------------------

class TestBindings:
    """Req 19.1: WorldContract binds Plan revision, CameraContract hash, etc."""

    def test_bind_plan_revision(self):
        contract = WorldContract()
        bound = bind_plan_revision(contract, "rev-5")
        assert bound.plan_revision == "rev-5"
        # Original unchanged (frozen)
        assert contract.plan_revision == ""

    def test_bind_camera_hash(self):
        contract = WorldContract()
        bound = bind_camera_hash(contract, "sha256:camera123")
        assert bound.camera_hash == "sha256:camera123"
        assert contract.camera_hash == ""

    def test_add_instance(self):
        contract = WorldContract()
        inst = _make_instance("sofa")
        result = add_instance(contract, inst)
        assert len(result.instances) == 1
        assert result.instances[0].name == "sofa"
        # Original unchanged
        assert len(contract.instances) == 0

    def test_add_relationship(self):
        contract = WorldContract()
        rel = Relationship(
            source_id="chair-1",
            target_id="table-1",
            relationship_type="adjacency",
        )
        result = add_relationship(contract, rel)
        assert len(result.relationships) == 1
        assert result.relationships[0].source_id == "chair-1"

    def test_set_lighting(self):
        contract = WorldContract()
        light = LightSource(
            light_id="main",
            light_type="directional",
            position=Vec3(0, 5, 0),
            intensity=2.0,
        )
        cfg = LightingConfig(lights=(light,))
        result = set_lighting(contract, cfg)
        assert len(result.lighting.lights) == 1
        assert result.lighting.lights[0].light_id == "main"


# ---------------------------------------------------------------------------
# Test: Event finality (Req 19.5, 19.6)
# ---------------------------------------------------------------------------

class TestEvents:
    """Req 19.5, 19.6: Final events have hash; provisional events marked."""

    def test_final_event_contains_hash_and_transforms(self):
        """Req 19.5: Every final event has solved transforms + exact hash."""
        contract = _make_contract()
        finalized = finalize(contract)
        obj_id = finalized.instances[0].object_id
        event = make_final_event(finalized, obj_id)
        assert event["status"] == "final"
        assert event["contract_hash"] == finalized.contract_hash
        assert "position" in event
        assert "rotation" in event
        assert "scale" in event

    def test_final_event_rejects_unfinalized_contract(self):
        """Cannot create final event without hash."""
        contract = _make_contract()
        obj_id = contract.instances[0].object_id
        try:
            make_final_event(contract, obj_id)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "un-finalized" in str(e)

    def test_final_event_rejects_unknown_object(self):
        """Cannot create final event for object not in contract."""
        contract = _make_contract()
        finalized = finalize(contract)
        try:
            make_final_event(finalized, "nonexistent-id")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e)

    def test_provisional_event_marked_provisional(self):
        """Req 19.6: Provisional events explicitly marked."""
        event = make_provisional_event(
            object_id="obj-1",
            position=Vec3(1.0, 0.0, 2.0),
        )
        assert event["status"] == "provisional"
        assert event["contract_hash"] is None

    def test_provisional_event_optional_transforms(self):
        """Provisional events may or may not have transforms."""
        event = make_provisional_event(object_id="obj-1")
        assert "position" not in event
        assert "rotation" not in event


# ---------------------------------------------------------------------------
# Test: Instance list completeness (Req 19.1)
# ---------------------------------------------------------------------------

class TestInstanceList:
    """Req 19.1: All object instances with full metadata."""

    def test_instance_has_all_fields(self):
        inst = _make_instance("coffee_maker")
        d = inst.to_dict()
        assert "object_id" in d
        assert "position" in d
        assert "rotation" in d
        assert "scale" in d
        assert "asset_binding" in d
        assert "physics_intent" in d
        assert "material_intent" in d
        assert "semantic_label" in d

    def test_asset_binding_fields(self):
        inst = _make_instance("coffee_maker")
        ab = inst.asset_binding.to_dict()
        assert "asset_id" in ab
        assert "mesh_path" in ab
        assert "triangle_count" in ab
        assert "vertex_count" in ab
        assert "generator" in ab

    def test_material_intent_fields(self):
        inst = _make_instance("coffee_maker")
        mi = inst.material_intent.to_dict()
        assert "base_color" in mi
        assert "metallic" in mi
        assert "roughness" in mi
        assert "pass_level" in mi


# ---------------------------------------------------------------------------
# Test: Relationship graph (Req 19.1)
# ---------------------------------------------------------------------------

class TestRelationshipGraph:
    """Req 19.1: Relationship graph."""

    def test_relationship_types(self):
        for rel_type in ["parent_child", "containment", "adjacency", "support"]:
            rel = Relationship(
                source_id="a",
                target_id="b",
                relationship_type=rel_type,
            )
            assert rel.relationship_type == rel_type

    def test_relationship_round_trip(self):
        rel = Relationship(
            source_id="chair-1",
            target_id="table-1",
            relationship_type="adjacency",
            metadata='{"distance": 0.5}',
        )
        d = rel.to_dict()
        reconstructed = Relationship.from_dict(d)
        assert reconstructed.source_id == "chair-1"
        assert reconstructed.target_id == "table-1"
        assert reconstructed.metadata == '{"distance": 0.5}'
