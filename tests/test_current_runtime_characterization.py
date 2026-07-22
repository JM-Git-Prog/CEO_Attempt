from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.assembler import blender_runner
from src.assembler.godot_project import assemble_godot_project
from src.camera_contract import camera_contract_for_plan
from src.floor_plan.models import FloorPlan
from src.models import SceneGraph, WorldSession
from src.workflow_provenance import (
    artifact_metadata,
    profile_for,
    snapshot_session,
    write_generation_manifest,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "current_runtime_characterization.json"
PROJECT_ROOT = Path(__file__).parents[1]


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_plan_and_camera_contract_match_characterization_fixture():
    fixture = load_fixture()
    plan = FloorPlan.model_validate(fixture["plan"])

    assert plan.model_dump(mode="json") == fixture["plan"]
    contract = camera_contract_for_plan(plan)
    expected = fixture["camera_contract"]
    assert contract.contract_id == expected["contract_id"]
    assert contract.schema_version == expected["schema_version"]
    assert contract.coordinate_system == expected["coordinate_system"]
    assert contract.projection == expected["projection"]
    assert contract.aspect_ratio == expected["aspect_ratio"]
    assert contract.image_width == expected["image_width"]
    assert contract.image_height == expected["image_height"]
    assert contract.near_plane == expected["near_plane"]
    assert contract.far_plane == expected["far_plane"]
    assert [entry["id"] for entry in contract.reference_landmarks] == expected["landmark_ids"]


def test_scene_graph_round_trip_matches_characterization_fixture():
    fixture = load_fixture()
    graph = SceneGraph.model_validate(fixture["scene_graph"])

    assert graph.model_dump(mode="json") == fixture["scene_graph"]
    assert SceneGraph.model_validate_json(graph.model_dump_json()) == graph


def test_godot_assembler_matches_characterization_fixture(tmp_path: Path):
    fixture = load_fixture()
    graph = SceneGraph.model_validate(fixture["scene_graph"])

    project_dir = assemble_godot_project(graph, tmp_path, {})
    expected = fixture["godot_assembler"]
    assert sorted(path.name for path in project_dir.iterdir() if path.is_file()) == expected["generated_files"]

    main_scene = (project_dir / "main.tscn").read_text(encoding="utf-8")
    for snippet in expected["main_scene_snippets"]:
        assert snippet in main_scene
    player_scene = (project_dir / "player.tscn").read_text(encoding="utf-8")
    for snippet in expected["player_scene_snippets"]:
        assert snippet in player_scene
    assert "window_east" not in main_scene


def test_blender_runner_and_prototype_match_characterization_fixture(
    tmp_path: Path, monkeypatch,
):
    fixture = load_fixture()
    expected = fixture["blender_prototype"]
    session_dir = tmp_path / "output" / "fixture-session"
    session_dir.mkdir(parents=True)
    (session_dir / "session.json").write_text(
        json.dumps({"floor_plan": fixture["plan"]}), encoding="utf-8"
    )
    for name in ("scene.blend", "blockout_blender.png", "scene.glb"):
        (session_dir / name).write_bytes(b"characterization")

    invocation: dict = {}

    def fake_run(command, **kwargs):
        invocation.update({"command": command, **kwargs})
        return SimpleNamespace(returncode=0, stdout="assembled", stderr="")

    monkeypatch.setattr(blender_runner, "find_blender", lambda: "C:/Blender/blender.exe")
    monkeypatch.setattr(blender_runner.subprocess, "run", fake_run)
    result = blender_runner.assemble_blender_scene(
        session_dir, render_blockout=False, export_gltf=False
    )

    assert result["success"] is True
    assert invocation["command"][0] == "C:/Blender/blender.exe"
    assert invocation["command"][1:3] == expected["runner_command_tail"][:2]
    assert Path(invocation["command"][4]) == Path(blender_runner.SCRIPT_PATH)
    assert invocation["command"][5] == "--"
    assert Path(invocation["command"][6]) == session_dir
    assert not any(option in invocation["command"] for option in expected["runner_options_not_forwarded"])
    assert result["blend_path"] == str(session_dir / "scene.blend")
    assert result["blockout_path"] == str(session_dir / "blockout_blender.png")
    assert result["gltf_path"] == str(session_dir / "scene.glb")


def test_blender_prototype_source_markers_are_characterized():
    expected = load_fixture()["blender_prototype"]
    source = (PROJECT_ROOT / "src" / "assembler" / "blender_scene.py").read_text(
        encoding="utf-8"
    )

    for marker in expected["source_markers"]:
        assert marker in source


def test_provenance_snapshot_artifact_and_manifest_behavior(tmp_path: Path):
    fixture = load_fixture()
    expected = fixture["provenance"]
    profile = profile_for(9)
    session = WorldSession(
        session_id="characterization-session",
        interface_version=9,
        workflow_profile_id=profile["id"],
        workflow_profile=profile,
    )
    artifact = tmp_path / "evidence.txt"
    artifact.write_bytes(expected["artifact_content"].encode("utf-8"))

    metadata = artifact_metadata(artifact)
    assert metadata == {
        "path": str(artifact),
        "exists": True,
        "bytes": expected["artifact_bytes"],
        "sha256": expected["artifact_sha256"],
    }

    snapshot_path = snapshot_session(session, tmp_path)
    assert snapshot_path.relative_to(tmp_path).as_posix() == expected["snapshot_pattern"]
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == expected["schema_version"]
    assert snapshot["session_id"] == session.session_id
    assert snapshot["interface_version"] == 9
    assert snapshot["workflow_profile"] == profile
    assert snapshot["sequence"] == 1
    assert snapshot["artifacts"] == [metadata]

    payload = {"status": "prepared", "input_hash": expected["artifact_sha256"]}
    first = write_generation_manifest(tmp_path, 1, "prepared", payload)
    first_bytes = first.read_bytes()
    second = write_generation_manifest(tmp_path, 1, "prepared", payload)
    assert first.relative_to(tmp_path).as_posix() == expected["manifest_pattern"]
    assert second.relative_to(tmp_path).as_posix() == expected["collision_manifest_pattern"]
    assert first.read_bytes() == first_bytes
    assert json.loads(first_bytes) == {
        "schema_version": expected["schema_version"],
        "attempt": 1,
        "mode": "prepared",
        **payload,
    }
