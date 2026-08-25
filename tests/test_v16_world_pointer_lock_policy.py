"""Route-scoped capability-policy regressions for the generated world viewer.

**Validates: Requirements 2.5, 3.1**
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.web.unified_routes import create_unified_router


@pytest.fixture
def world_client(tmp_path):
    session_id = "pointer-lock-policy"
    compiled = tmp_path / session_id / "compiled" / "browser"
    compiled.mkdir(parents=True)
    (compiled / "index.html").write_text("<!doctype html><title>Browser v8</title>", encoding="utf-8")
    (compiled / "viewer.js").write_text("export const interfaceVersion = 8;", encoding="utf-8")

    app = FastAPI()

    @app.get("/unrelated")
    async def unrelated():
        return {"status": "ok"}

    app.include_router(create_unified_router(lambda: tmp_path))
    with TestClient(app) as client:
        yield client, session_id


def _assert_restrictive_pointer_lock_policy(response) -> None:
    assert response.status_code == 200
    policy = response.headers["permissions-policy"]
    directives = [item.strip() for item in policy.split(",")]
    assert directives.count("pointer-lock=(self)") == 1
    for feature in (
        "accelerometer",
        "camera",
        "geolocation",
        "gyroscope",
        "magnetometer",
        "microphone",
        "payment",
        "usb",
    ):
        assert f"{feature}=()" in directives
    assert response.headers["cache-control"] == "no-store"


def test_world_document_permits_self_pointer_lock_and_denies_unrelated_features(world_client) -> None:
    client, session_id = world_client

    response = client.get(f"/api/session/{session_id}/world")

    _assert_restrictive_pointer_lock_policy(response)
    assert "Browser v8" in response.text

    retained = client.get(f"/api/session/{session_id}/world?v=7")
    _assert_restrictive_pointer_lock_policy(retained)
    assert retained.content == response.content


def test_world_static_javascript_receives_same_route_scoped_policy(world_client) -> None:
    client, session_id = world_client

    response = client.get(f"/api/session/{session_id}/world/viewer.js?v=8")

    _assert_restrictive_pointer_lock_policy(response)
    assert response.headers["content-type"].startswith("application/javascript")
    assert "interfaceVersion = 8" in response.text


def test_pointer_lock_policy_does_not_leak_to_unrelated_routes(world_client) -> None:
    client, _ = world_client

    response = client.get("/unrelated")

    assert response.status_code == 200
    assert "permissions-policy" not in response.headers
