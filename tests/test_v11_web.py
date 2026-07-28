from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.models import WorldSession
from src.web import app as web
from src.workflow_provenance import profile_for


class StubBuilder:
    root = None

    def __init__(self, session_id=None, interface_version=11):
        profile = profile_for(interface_version)
        self.session = WorldSession(
            session_id=session_id or uuid4().hex[:8],
            interface_version=interface_version,
            workflow_profile_id=profile["id"],
            workflow_profile=profile,
        )
        self.output_dir = self.root / self.session.session_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self):
        return None


@pytest.fixture
def client(tmp_path, monkeypatch):
    StubBuilder.root = tmp_path
    web.sessions.clear()
    monkeypatch.setattr(web, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(web, "WorldBuilder", StubBuilder)
    monkeypatch.setattr(
        web, "append_event",
        lambda root, payload: {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "app_version": str(payload.get("app_version", 11)),
        },
    )
    with TestClient(web.app) as test_client:
        yield test_client
    web.sessions.clear()


def test_v13_is_default_and_invalid_versions_are_rejected(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "window.APP_VERSION=13" in page.text
    assert "In-browser 3D" in page.text
    assert 'href="/?v=12"' in page.text and 'href="/?v=13"' in page.text

    for value in ("nope", "3.0", "02", "2", "14"):
        response = client.get("/", params={"v": value})
        assert response.status_code == 400
        assert "interface version" in response.text

    legacy = client.get("/", params={"v": "10"})
    assert legacy.status_code == 200
    assert "window.APP_VERSION=10" in legacy.text
    assert "Declared Godot fallback" not in legacy.text

    v11 = client.get("/", params={"v": "11"})
    assert v11.status_code == 200
    assert "window.APP_VERSION=11" in v11.text


def test_api_header_defaults_to_v13_and_never_coerces(client):
    created = client.post("/api/session")
    assert created.status_code == 200
    assert created.json()["interface_version"] == 13

    for value in ("future", "3.0", "02", "2", "14"):
        response = client.get(
            "/api/session/missing/status", headers={"X-App-Version": value}
        )
        assert response.status_code == 400
        assert "interface version" in response.json()["error"]


def _runtime_builder(tmp_path):
    builder = StubBuilder(session_id="runtime11", interface_version=11)
    artifact = builder.output_dir / "scene.glb"
    artifact.write_bytes(b"recorded glb")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    terminal = builder.output_dir / "compiler_terminal.json"
    terminal.write_text(json.dumps({
        "compiler": {
            "product": "UPBGE", "product_version": "0.36",
            "compiler_version": "upbge-compiler-plan/v1", "runtime_capable": True,
        },
        "diagnostics": [{"stage": "capability_probe", "code": "not_found",
                         "severity": "warning", "message": "fallback selected"}],
    }), encoding="utf-8")
    builder.session.compiler_manifests = [str(terminal)]
    builder.session.compiler_result = {
        "target": "godot", "status": "fallback_success",
        "capability": {"compatible": False, "reason_code": "not_found"},
        "primary_failure": {"reason_code": "not_found"},
        "terminal_manifest": str(terminal),
        "artifacts": [{
            "path": str(artifact), "bytes": artifact.stat().st_size,
            "sha256": digest, "media_type": "model/gltf-binary", "target_role": "glb",
        }],
    }
    builder.session.export_results = {
        "godot": {"status": "success", "artifacts": [], "manifests": []}
    }
    builder.session.parity_report = {"passed": True, "artifact_accepted": True}
    builder.session.runtime_smoke_report = None
    builder.session.qa_evidence = [{"decision": "human_required"}]
    return builder, artifact, digest


def test_v11_status_snapshot_and_safe_recorded_artifact_download(client, tmp_path):
    builder, artifact, digest = _runtime_builder(tmp_path)
    web.sessions[builder.session.session_id] = builder

    for endpoint in (
        "/api/session/runtime11/status", "/api/session/runtime11/snapshot",
    ):
        response = client.get(endpoint, headers={"X-App-Version": "11"})
        assert response.status_code == 200
        payload = response.json()
        compiler = payload["runtime_details"]["compiler"]
        assert compiler["target"] == "godot"
        assert compiler["status"] == "fallback_success"
        assert compiler["execution"] == "declared_fallback"
        assert compiler["capability"]["reason_code"] == "not_found"
        assert compiler["versions"]["product"] == "UPBGE"
        assert compiler["failures"]
        assert payload["parity_report"]["passed"] is True
        assert payload["runtime_smoke_report"] is None
        assert payload["qa_evidence"][0]["decision"] == "human_required"
        assert payload["export_results"]["godot"]["status"] == "success"

    record = client.get("/api/session/runtime11/status").json()["artifact_downloads"][0]
    assert record["sha256"] == digest and record["integrity"] == "verified"
    downloaded = client.get(record["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.content == artifact.read_bytes()
    assert downloaded.headers["x-artifact-sha256"] == digest

    assert client.get("/api/session/runtime11/artifact/not-recorded").status_code == 404
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    builder.session.compiler_result["artifacts"].append({
        "path": str(outside), "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
        "media_type": "text/plain", "target_role": "outside",
    })
    records = client.get("/api/session/runtime11/status").json()["artifact_downloads"]
    assert all(item["filename"] != "outside.txt" for item in records)


def test_v11_history_routes_are_registered():
    paths = {route.path for route in web.app.routes}
    assert "/api/v11/sessions" in paths
    assert "/api/v11/session/{session_id}/stages" in paths
    assert "/api/v11/session/{session_id}/stage/{stage}" in paths
    assert "/api/v11/session/{session_id}/stage/{stage}/artifact" in paths
    assert "/api/v11/session/{session_id}/telemetry" in paths


def test_v11_human_qa_route_is_explicit_and_version_scoped(client, tmp_path):
    builder, _artifact, _digest = _runtime_builder(tmp_path)
    builder.adjudicate_v11_qa = lambda reviewer, verdict, rationale: SimpleNamespace(
        model_dump=lambda mode="json": {
            "decision": "human_approved", "reviewer": reviewer,
            "verdict": verdict, "rationale": rationale,
        }
    )
    builder.session.state = web.PipelineState.READY
    web.sessions[builder.session.session_id] = builder

    response = client.post(
        "/api/session/runtime11/qa",
        json={"reviewer_id": "release-owner", "verdict": "approved", "rationale": "inspected"},
        headers={"X-App-Version": "11"},
    )

    assert response.status_code == 200
    assert response.json()["evidence"]["decision"] == "human_approved"
    assert "/api/session/{session_id}/qa" in {route.path for route in web.app.routes}

    retained = StubBuilder(session_id="retained10", interface_version=10)
    web.sessions[retained.session.session_id] = retained
    rejected = client.post(
        "/api/session/retained10/qa",
        json={"reviewer_id": "user", "verdict": "approved", "rationale": "no"},
        headers={"X-App-Version": "10"},
    )
    assert rejected.status_code == 400


def test_retained_v3_through_v10_pages_and_profiles_remain_available(client):
    retained_ids = {
        3: "v3-legacy@f982288",
        4: "v4-reference-full@5069761",
        5: "v5-reference-partial@964da06",
        6: "v6-reference-full-r1",
        7: "v7-reference-full-r1",
        8: "v8-reference-full-r1",
        9: "v9-camera-locked-photoreal-r3",
        10: "v10-bounded-review-r1",
    }
    for version, profile_id in retained_ids.items():
        page = client.get("/", params={"v": str(version)})
        assert page.status_code == 200
        assert f"window.APP_VERSION={version}" in page.text
        assert 'href="/?v=11"' in page.text
        assert "ui-v11-runtime" not in page.text
        assert profile_for(version)["id"] == profile_id
        assert "world" not in profile_for(version)["stages"]


def test_profile_documents_are_defensive_copies_and_v11_is_isolated():
    retained_v10 = profile_for(10)
    candidate_v11 = profile_for(11)

    candidate_v11["stages"]["world"]["primary_adapter"] = "tampered"
    retained_v10["stages"]["canon"]["camera_contract"] = "tampered"

    assert profile_for(11)["stages"]["world"]["primary_adapter"] == "upbge"
    assert profile_for(11)["stages"]["world"]["fallback_adapter"] == "godot"
    assert profile_for(10)["stages"]["canon"]["camera_contract"] == "v10-camera-1"
    assert "world" not in profile_for(9)["stages"]
    assert "world" not in profile_for(10)["stages"]


@pytest.mark.parametrize(
    ("target", "status", "execution"),
    [
        ("upbge", "native_success", "native"),
        ("godot", "fallback_success", "declared_fallback"),
        ("upbge", "partial_export", "partial"),
        ("godot", "partial_export", "partial"),
        ("upbge", "failure", "failed"),
    ],
)
def test_v11_runtime_payload_distinguishes_every_compiler_outcome(
    tmp_path, target, status, execution
):
    StubBuilder.root = tmp_path
    builder = StubBuilder(session_id=f"status-{status}-{target}", interface_version=11)
    builder.session.compiler_result = {"target": target, "status": status}

    compiler = web._v11_runtime_payload(builder)["runtime_details"]["compiler"]

    assert compiler["target"] == target
    assert compiler["status"] == status
    assert compiler["execution"] == execution
    assert compiler["primary_target"] == "upbge"
    assert compiler["declared_fallback"] == "godot"
