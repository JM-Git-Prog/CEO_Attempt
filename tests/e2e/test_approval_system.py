"""Sanity tests for the approval queue and API routes."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.web.approvals import ApprovalItem, ApprovalQueue


@pytest.fixture
def tmp_queue(tmp_path):
    """Create a temporary approval queue for testing."""
    store = tmp_path / ".approval_queue.json"
    return ApprovalQueue(store)


class TestApprovalQueue:
    """Unit tests for the ApprovalQueue dataclass and queue logic."""

    def test_empty_queue(self, tmp_queue):
        assert tmp_queue.get_pending() == []
        assert tmp_queue.get_all() == []

    def test_add_item(self, tmp_queue):
        item = ApprovalItem(
            id="test001",
            type="threshold_change",
            title="Adjust SSIM threshold",
            description="Recommended SSIM threshold change from 0.85 to 0.90",
            context={"metric_key": "ssim_threshold", "old_value": 0.85, "new_value": 0.90},
        )
        tmp_queue.add(item)
        pending = tmp_queue.get_pending()
        assert len(pending) == 1
        assert pending[0].id == "test001"
        assert pending[0].status == "pending"

    def test_approve_item(self, tmp_queue):
        item = ApprovalItem(
            id="test002",
            type="vision_qa_verdict",
            title="Vision QA: PASS",
            description="Model says PASS with confidence 0.92",
            context={"pass": True, "confidence": 0.92},
        )
        tmp_queue.add(item)
        result = tmp_queue.verdict("test002", approved=True)
        assert result is not None
        assert result.status == "approved"
        assert result.verdict_at is not None
        assert tmp_queue.get_pending() == []

    def test_reject_item(self, tmp_queue):
        item = ApprovalItem(
            id="test003",
            type="new_test",
            title="New test: test_edge_case.py",
            description="Discovered edge case test",
            context={"filename": "test_edge_case.py"},
        )
        tmp_queue.add(item)
        result = tmp_queue.verdict("test003", approved=False)
        assert result is not None
        assert result.status == "rejected"
        assert tmp_queue.get_pending() == []

    def test_verdict_not_found(self, tmp_queue):
        result = tmp_queue.verdict("nonexistent", approved=True)
        assert result is None

    def test_persistence(self, tmp_path):
        store = tmp_path / ".approval_queue.json"
        queue1 = ApprovalQueue(store)
        queue1.add(ApprovalItem(
            id="persist01",
            type="baseline_update",
            title="Update baseline",
            description="New baseline for kitchen scene",
            context={"baseline_path": "baselines/kitchen.png"},
        ))
        # Create a new queue instance reading the same file
        queue2 = ApprovalQueue(store)
        assert len(queue2.get_pending()) == 1
        assert queue2.get_pending()[0].id == "persist01"

    def test_clear_completed(self, tmp_queue):
        # Add and approve an item
        item = ApprovalItem(
            id="clear01",
            type="checklist_update",
            title="Update checklist",
            description="Added geometry check",
            context={},
            # Set verdict_at to a very old date
            status="approved",
            verdict_at="2020-01-01T00:00:00+00:00",
        )
        tmp_queue.add(item)
        removed = tmp_queue.clear_completed()
        assert removed == 1
        assert tmp_queue.get_all() == []

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid approval type"):
            ApprovalItem(
                id="bad01",
                type="invalid_type",
                title="Bad",
                description="Should fail",
                context={},
            )


class TestApprovalBridge:
    """Test the improvement loop bridge functions."""

    def test_queue_threshold_change(self, tmp_path, monkeypatch):
        # Patch the default queue location
        store = tmp_path / ".approval_queue.json"
        monkeypatch.setattr(
            "src.web.approvals._DEFAULT_STORE", store
        )
        from tests.e2e.improvement.approval_bridge import queue_threshold_change

        item = queue_threshold_change(
            metric_key="ssim_floor",
            old_value=0.8,
            new_value=0.85,
            reason="Calibration corpus shows 0.85 is more stable",
        )
        assert item.type == "threshold_change"
        assert item.status == "pending"
        assert "ssim_floor" in item.title

    def test_queue_new_test(self, tmp_path, monkeypatch):
        store = tmp_path / ".approval_queue.json"
        monkeypatch.setattr(
            "src.web.approvals._DEFAULT_STORE", store
        )
        from tests.e2e.improvement.approval_bridge import queue_new_test

        item = queue_new_test(
            filename="test_lighting_edge.py",
            test_summary="Edge case for dim lighting conditions",
            discovered_from="failure_analyzer",
        )
        assert item.type == "new_test"
        assert "test_lighting_edge.py" in item.title


class TestApprovalRoutes:
    """Integration test for the FastAPI routes (requires httpx/test client)."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        """Create a test client with a temporary queue."""
        store = tmp_path / ".approval_queue.json"
        monkeypatch.setattr(
            "src.web.approvals._DEFAULT_STORE", store
        )
        # Import after monkeypatch so routes pick up the patched store
        from fastapi.testclient import TestClient
        from src.web.approval_routes import router
        from fastapi import FastAPI

        test_app = FastAPI()
        test_app.include_router(router)
        return TestClient(test_app)

    def test_get_empty_pending(self, client):
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_all_empty(self, client):
        resp = client.get("/api/approvals/all")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_full_approval_flow(self, client, tmp_path, monkeypatch):
        store = tmp_path / ".approval_queue.json"
        monkeypatch.setattr(
            "src.web.approvals._DEFAULT_STORE", store
        )
        # Add an item directly to the queue
        from src.web.approvals import ApprovalItem, get_default_queue
        queue = get_default_queue()
        queue.add(ApprovalItem(
            id="flow01",
            type="vision_qa_verdict",
            title="Vision check",
            description="Model says PASS",
            context={"pass": True},
        ))

        # Verify it shows up
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["id"] == "flow01"

        # Approve it
        resp = client.post("/api/approvals/flow01/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

        # Verify pending is now empty
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_reject_flow(self, client, tmp_path, monkeypatch):
        store = tmp_path / ".approval_queue.json"
        monkeypatch.setattr(
            "src.web.approvals._DEFAULT_STORE", store
        )
        from src.web.approvals import ApprovalItem, get_default_queue
        queue = get_default_queue()
        queue.add(ApprovalItem(
            id="rej01",
            type="threshold_change",
            title="Bad threshold",
            description="Not recommended",
            context={"metric_key": "bad"},
        ))

        resp = client.post("/api/approvals/rej01/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_404_on_missing_item(self, client):
        resp = client.post("/api/approvals/missing123/approve")
        assert resp.status_code == 404
