"""Tests for event finality, transport preservation, and durable replay.

**Validates: Requirements 19.5, 19.6, 27.2**
"""

from __future__ import annotations

import json

import pytest

from src.unified_pipeline.event_system import (
    EventDisposition,
    EventFinality,
    EventOrigin,
    EventRejected,
    EventSystem,
    MismatchPolicy,
    ReplayCursorError,
)
from src.unified_pipeline.world_contract import (
    AssetBinding,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Vec3,
    WorldContract,
    bind_plan_revision,
    finalize,
)


def _contract(revision: str = "rev-1") -> WorldContract:
    instance = ObjectInstance(
        object_id="table-id",
        name="table",
        position=Vec3(1.0, 0.0, 2.0),
        rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
        scale=Vec3(1.2, 0.8, 1.2),
        asset_binding=AssetBinding(
            asset_id="a" * 64,
            mesh_path="meshes/table.glb",
            triangle_count=500,
            vertex_count=300,
            generator="hunyuan3d",
        ),
        material_intent=MaterialIntent(base_color="#884422", roughness=0.7),
    )
    return finalize(WorldContract(
        plan_revision=revision,
        camera_hash="b" * 64,
        room_shell_ref="shell.glb",
        instances=(instance,),
        contract_id="contract-id",
        created_at="2026-08-01T00:00:00Z",
    ))


def _authorize(system: EventSystem, contract: WorldContract):
    registered = system.register_contract(contract)
    finalized = system.authorize_finality(
        plan_revision=contract.plan_revision,
        contract_hash=contract.contract_hash,
        structural_gates_passed=True,
        parity_gate_passed=True,
    )
    return registered, finalized


def test_precontract_final_claim_is_downgraded_and_explicit():
    system = EventSystem("session-1")

    decision = system.emit(
        "object.ready",
        {"object_id": "table-id"},
        finality="final",
        plan_revision="rev-1",
        contract_hash="a" * 64,
    )

    assert decision.disposition is EventDisposition.DOWNGRADED
    assert decision.event.finality is EventFinality.PROVISIONAL
    assert decision.event.payload["requested_finality"] == "final"
    assert "no verified WorldContract" in decision.event.diagnostic


def test_contract_precedes_final_object_with_exact_solved_binding():
    contract = _contract()
    system = EventSystem("session-2")
    registered, finalized = _authorize(system, contract)

    decision = system.publish_object("table-id")

    event = decision.event
    assert registered.sequence < finalized.sequence < event.sequence
    assert registered.finality is EventFinality.PROVISIONAL
    assert finalized.finality is EventFinality.FINAL
    assert event.finality is EventFinality.FINAL
    assert event.plan_revision == contract.plan_revision
    assert event.contract_hash == contract.contract_hash
    assert event.payload["position"] == {"x": 1.0, "y": 0.0, "z": 2.0}
    assert event.payload["rotation"] == {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    assert event.payload["scale"] == {"x": 1.2, "y": 0.8, "z": 1.2}
    assert event.payload["asset_binding"]["mesh_path"] == "meshes/table.glb"
    assert event.payload["material_intent"]["roughness"] == 0.7


def test_gate_failure_keeps_events_provisional():
    contract = _contract()
    system = EventSystem("session-gates")
    system.register_contract(contract)
    blocked = system.authorize_finality(
        plan_revision=contract.plan_revision,
        contract_hash=contract.contract_hash,
        structural_gates_passed=True,
        parity_gate_passed=False,
    )

    decision = system.publish_object("table-id")

    assert blocked.event_type == "publication.blocked"
    assert blocked.finality is EventFinality.PROVISIONAL
    assert decision.disposition is EventDisposition.DOWNGRADED
    assert "not been authorized" in decision.reason


def test_stale_revision_downgrades_or_rejects_by_policy():
    old_contract = _contract("rev-1")
    new_contract = finalize(bind_plan_revision(old_contract, "rev-2"))
    system = EventSystem("session-3")
    _authorize(system, old_contract)
    system.register_contract(new_contract)
    system.authorize_finality(
        plan_revision=new_contract.plan_revision,
        contract_hash=new_contract.contract_hash,
        structural_gates_passed=True,
        parity_gate_passed=True,
    )
    stale = {
        "event_id": "sidecar-7",
        "event_type": "mesh.ready",
        "status": "final",
        "object_id": "table-id",
        "plan_revision": old_contract.plan_revision,
        "contract_hash": old_contract.contract_hash,
    }

    downgraded = system.ingest_sidecar(stale)

    assert downgraded.disposition is EventDisposition.DOWNGRADED
    assert downgraded.event.finality is EventFinality.PROVISIONAL
    assert "stale plan revision" in downgraded.reason
    with pytest.raises(EventRejected, match="stale plan revision"):
        system.ingest_compiler(
            {**stale, "event_id": "compiler-8"},
            mismatch_policy=MismatchPolicy.REJECT,
        )


def test_mismatched_transform_cannot_claim_final():
    contract = _contract()
    system = EventSystem("session-transform")
    _authorize(system, contract)

    decision = system.ingest_websocket({
        "event_id": "ws-1",
        "event_type": "object.ready",
        "status": "final",
        "object_id": "table-id",
        "position": {"x": 99.0, "y": 0.0, "z": 2.0},
        "plan_revision": contract.plan_revision,
        "contract_hash": contract.contract_hash,
    })

    assert decision.disposition is EventDisposition.DOWNGRADED
    assert "position does not match" in decision.reason


def test_sidecar_and_compiler_events_use_same_finality_and_deduplicate():
    contract = _contract()
    system = EventSystem("session-producers")
    _authorize(system, contract)
    envelope = {
        "event_id": "producer-1",
        "event_type": "compiler.completed",
        "status": "final",
        "plan_revision": contract.plan_revision,
        "contract_hash": contract.contract_hash,
        "payload": {"target": "godot"},
    }

    compiler = system.ingest_compiler(envelope)
    duplicate = system.ingest_compiler(envelope)
    sidecar = system.ingest_sidecar({**envelope, "event_id": "sidecar-1"})

    assert compiler.event.finality is EventFinality.FINAL
    assert compiler.event.origin is EventOrigin.COMPILER
    assert duplicate.disposition is EventDisposition.DUPLICATE
    assert duplicate.event.event_id == compiler.event.event_id
    assert sidecar.event.finality is EventFinality.FINAL
    assert sidecar.event.origin is EventOrigin.SIDECAR


def test_sse_websocket_and_reconnect_replay_preserve_finality(tmp_path):
    journal = tmp_path / "events.jsonl"
    contract = _contract()
    system = EventSystem("session-4", journal)
    registered, _ = _authorize(system, contract)
    final_event = system.publish_object("table-id").event

    sse = system.replay_sse(registered.event_id)
    websocket = system.replay_websocket(registered.event_id)
    sse_payloads = [
        json.loads(next(line[6:] for line in record.splitlines() if line.startswith("data: ")))
        for record in sse
    ]

    assert [item["finality"] for item in sse_payloads] == ["final", "final"]
    assert [item["finality"] for item in websocket] == ["final", "final"]
    assert websocket[-1]["event_id"] == final_event.event_id

    reconnected = EventSystem("session-4", journal)
    replayed = reconnected.replay(registered.event_id)
    assert [event.to_dict() for event in replayed] == [
        event.to_dict() for event in system.replay(registered.event_id)
    ]
    assert reconnected.finality_authorized
    assert reconnected.publish_object("table-id").event.finality is EventFinality.FINAL


def test_superseding_contract_preserves_history_but_blocks_old_new_events():
    first = _contract("rev-1")
    second = finalize(bind_plan_revision(first, "rev-2"))
    system = EventSystem("session-5")
    _authorize(system, first)
    historical = system.publish_object("table-id").event
    system.register_contract(second)

    stale = system.emit(
        "object.published",
        {"object_id": "table-id"},
        finality="final",
        plan_revision=first.plan_revision,
        contract_hash=first.contract_hash,
    )

    assert historical.finality is EventFinality.FINAL
    assert system.replay()[historical.sequence - 1].finality is EventFinality.FINAL
    assert stale.event.finality is EventFinality.PROVISIONAL


def test_progress_shape_and_unknown_cursor_validation():
    system = EventSystem("session-progress")

    progress = system.emit_progress(
        stage="mesh_generation",
        objects_complete=2,
        objects_total=5,
        elapsed_seconds=12.5,
        eta_seconds=20.0,
    ).event

    assert progress.finality is EventFinality.PROVISIONAL
    assert progress.payload == {
        "current_stage": "mesh_generation",
        "objects_complete": 2,
        "objects_total": 5,
        "elapsed_seconds": 12.5,
        "eta_seconds": 20.0,
    }
    with pytest.raises(ReplayCursorError):
        system.replay("missing-cursor")
