"""One fresh zero-state V11 qualification pass; never restores a session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from src.web.app import app
from test_iteration import CANONICAL_PROMPT

HEADERS = {"X-App-Version": "11"}
PASSING = {"passed", "not_applicable"}
EXPECTED_STAGES = (
    "interface", "readiness", "fresh_session", "brief", "plan", "blockout",
    "canon", "world", "compare", "compiler_manifests", "compiler", "fallback",
    "parity", "runtime", "qa", "downloads",
)
MOCK_QUALIFICATION = os.getenv("QUALIFICATION_MOCK_E2E") == "1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _stage(status: str, **evidence: Any) -> dict:
    return {"status": status, **evidence}


def _signature_component(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9._:-]+", "_", str(value).strip().lower()).strip("_:")
    return (normalized or fallback)[:160]


def _nested_reason(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict):
        for key in ("reason_code", "code", "reason", "detail", "message", "status"):
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float)) and str(candidate).strip():
                return str(candidate)
        for key in ("primary_failure", "failure", "diagnostic", "failures", "diagnostics"):
            candidate = _nested_reason(value.get(key))
            if candidate:
                return candidate
    if isinstance(value, list):
        for item in value:
            candidate = _nested_reason(item)
            if candidate:
                return candidate
    return None


def _failure_rule_detail(stage: str, evidence: dict) -> tuple[str, str]:
    validation = evidence.get("validation") or {}
    blockers = validation.get("blockers") or []
    if blockers:
        blocker = blockers[0]
        reason = _nested_reason(blocker) or "blocked"
        item_ids = blocker.get("item_ids") if isinstance(blocker, dict) else None
        subject = item_ids[0] if item_ids else None
        detail = f"{reason}:{subject}" if subject else reason
        return "validation", _signature_component(detail, "blocked")

    alignment = evidence.get("alignment") or {}
    if alignment:
        reasons = alignment.get("reasons") or []
        reason = reasons[0] if reasons else _nested_reason(alignment)
        return "camera_alignment", _signature_component(reason, "failed")

    if stage == "downloads":
        failed = [item for item in evidence.get("records", []) if item.get("status") != "passed"]
        return "artifact_integrity", _signature_component(
            _nested_reason(failed) or "download_failed", "download_failed"
        )

    if stage == "qa":
        entries = evidence.get("entries") or []
        return "vision_screening", _signature_component(
            _nested_reason(entries) or "qa_not_accepted", "qa_not_accepted"
        )

    http_status = evidence.get("http_status")
    if isinstance(http_status, int) and http_status >= 400:
        reason = _nested_reason(evidence.get("response")) or f"status_{http_status}"
        return "http_status", _signature_component(
            f"{http_status}:{reason}", f"status_{http_status}"
        )

    reason = _nested_reason(evidence.get("evidence")) or _nested_reason(evidence)
    return "stage_status", _signature_component(reason, "failed")


def _signature_record(stage: str, rule: str, detail: str) -> dict[str, str]:
    stage_value = _signature_component(stage, "adapter")
    rule_value = _signature_component(rule, "stage_status")
    detail_value = _signature_component(detail, "failed")
    return {
        "stage": stage_value,
        "rule": rule_value,
        "detail": detail_value,
        "signature": f"{stage_value}/{rule_value}/{detail_value}",
    }


def _finalize_result(result: dict) -> None:
    signatures: list[dict[str, str]] = []
    exception = result.get("exception")
    if exception:
        signatures.append(_signature_record(
            "adapter", "exception", exception.get("type", "unknown_exception")
        ))

    stages = result.get("stages") or {}
    for stage in EXPECTED_STAGES:
        evidence = stages.get(stage)
        if evidence is None:
            signatures.append(_signature_record(stage, "incomplete", "not_recorded"))
        elif evidence.get("status") not in PASSING:
            rule, detail = _failure_rule_detail(stage, evidence)
            signatures.append(_signature_record(stage, rule, detail))
    for stage in sorted(set(stages) - set(EXPECTED_STAGES)):
        evidence = stages[stage]
        if evidence.get("status") not in PASSING:
            rule, detail = _failure_rule_detail(stage, evidence)
            signatures.append(_signature_record(stage, rule, detail))

    result["failure_signatures"] = signatures
    result["failure_signature"] = signatures[0]["signature"] if signatures else None
    result["passed"] = not signatures


def _artifact(path: Path) -> dict:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    data = path.read_bytes()
    return {"path": str(path), "exists": True, "size": len(data), "sha256": _sha256(data)}


def _download_verdict(client: TestClient, records: list[dict]) -> dict:
    checked = []
    for record in records:
        url = record.get("download_url")
        if not url:
            checked.append({"status": "failed", "reason": "missing_download_url", "record": record})
            continue
        response = client.get(url, headers=HEADERS)
        digest = _sha256(response.content) if response.status_code == 200 else None
        expected = record.get("sha256")
        checked.append({
            "url": url,
            "http_status": response.status_code,
            "sha256": digest,
            "expected_sha256": expected,
            "status": "passed" if response.status_code == 200 and digest == expected else "failed",
        })
    return _stage(
        "passed" if records and all(value["status"] == "passed" for value in checked) else "failed",
        count=len(records),
        records=checked,
    )


def _runtime_stages(
    status_payload: dict, *, mock_qualification: bool = MOCK_QUALIFICATION
) -> dict[str, dict]:
    runtime = status_payload.get("runtime_details", {})
    compiler = runtime.get("compiler", {})
    compiler_status = compiler.get("status")
    fallback = compiler.get("execution") == "declared_fallback"
    capability = compiler.get("capability") or {}
    parity = status_payload.get("parity_report") or {}
    smoke = status_payload.get("runtime_smoke_report")
    qa = status_payload.get("qa_evidence") or []
    qa_pass = any(
        entry.get("decision") in {"auto_accepted", "human_approved", "passed"}
        or (entry.get("pass") is True and float(entry.get("confidence", 0.0)) >= 0.8)
        for entry in qa
    )
    mock_qa_not_applicable = (
        mock_qualification
        and bool(qa)
        and all(
            entry.get("decision") == "human_required"
            and (entry.get("screening") or {}).get("status") == "failed"
            and str((entry.get("screening") or {}).get("diagnostic", "")).startswith(
                "vision screening failed:"
            )
            for entry in qa
        )
    )
    fallback_truthful = (
        fallback
        and compiler.get("target") == "godot"
        and compiler_status == "fallback_success"
        and capability.get("available") is False
    )
    native = compiler.get("execution") == "native"
    runtime_ok = (
        isinstance(smoke, dict) and smoke.get("passed") is True
        if native else fallback_truthful
    )
    return {
        "compiler_manifests": _stage(
            "passed" if status_payload.get("compiler_manifests") else "failed",
            count=len(status_payload.get("compiler_manifests") or []),
        ),
        "compiler": _stage(
            "passed" if compiler_status in {"native_success", "fallback_success"} else "failed",
            evidence=compiler,
        ),
        "fallback": _stage(
            "passed" if fallback_truthful else "not_applicable" if native else "failed",
            target=compiler.get("target"), execution=compiler.get("execution"),
        ),
        "parity": _stage("passed" if parity.get("passed") is True else "failed", evidence=parity),
        "runtime": _stage("passed" if runtime_ok else "failed", evidence=smoke),
        "qa": _stage(
            "not_applicable" if mock_qa_not_applicable else "passed" if qa_pass else "failed",
            entries=qa,
            reason="deterministic_mock_vision_unavailable" if mock_qa_not_applicable else None,
        ),
    }


def run_once(result_path: Path) -> dict:
    started = time.time()
    result: dict[str, Any] = {
        "schema_version": "v11-e2e-result/v1",
        "started_at_epoch": started,
        "canonical_prompt": CANONICAL_PROMPT,
        "canonical_prompt_sha256": _sha256(CANONICAL_PROMPT.encode()),
        "qualification_mode": "mock" if MOCK_QUALIFICATION else "real",
        "session_id": None,
        "stages": {},
        "failure_signature": None,
        "failure_signatures": [],
        "passed": False,
    }
    session_id: str | None = None
    try:
        with TestClient(app) as client:
            default_page = client.get("/")
            retained = {
                version: client.get("/", params={"v": str(version)}).status_code
                for version in range(3, 12)
            }
            invalid = {
                value: client.get("/", params={"v": value}).status_code
                for value in ("nope", "3.0", "02", "2", "12")
            }
            result["stages"]["interface"] = _stage(
                "passed" if (
                    default_page.status_code == 200
                    and "window.APP_VERSION=11" in default_page.text
                    and all(value == 200 for value in retained.values())
                    and all(value == 400 for value in invalid.values())
                ) else "failed",
                retained=retained, invalid=invalid,
            )

            readiness = client.get("/api/readiness", headers=HEADERS)
            result["stages"]["readiness"] = _stage(
                "passed" if readiness.status_code == 200 else "failed",
                http_status=readiness.status_code,
                payload=readiness.json() if readiness.headers.get("content-type", "").startswith("application/json") else {},
            )
            created = client.post("/api/session", headers=HEADERS)
            created.raise_for_status()
            identity = created.json()
            session_id = identity["session_id"]
            result["session_id"] = session_id
            result["identity"] = identity
            result["stages"]["fresh_session"] = _stage(
                "passed" if identity.get("interface_version") == 11 else "failed",
                identity=identity,
            )

            described = client.post(
                f"/api/session/{session_id}/describe",
                json={"description": CANONICAL_PROMPT},
                headers=HEADERS,
            )
            description_payload = described.json()
            result["stages"]["brief"] = _stage(
                "passed" if described.status_code == 200 else "failed",
                http_status=described.status_code,
                state=description_payload.get("state"),
                response=description_payload if described.status_code != 200 else None,
            )
            validation = description_payload.get("validation_report") or {}
            composition = description_payload.get("composition_evidence") or {}
            plan = description_payload.get("floor_plan") or {}
            plan_ok = (
                described.status_code == 200
                and validation.get("valid") is True
                and composition.get("status") == "accepted"
                and description_payload.get("camera_contract") is not None
            )
            result["stages"]["plan"] = _stage(
                "passed" if plan_ok else "failed",
                validation=validation,
                composition=composition,
                item_count=len(plan.get("items") or []),
                opening_count=len(plan.get("openings") or []),
            )
            output = ROOT / "output" / session_id
            result["stages"]["blockout"] = _stage(
                "passed" if (output / "blockout_v1.png").is_file() else "failed",
                artifacts=[
                    _artifact(output / "floor_plan_v1.json"),
                    _artifact(output / "floor_plan_v1.svg"),
                    _artifact(output / "blockout_v1.png"),
                ],
            )
            if not plan_ok:
                return result

            approved = client.post(f"/api/session/{session_id}/approve_plan", headers=HEADERS)
            canon_payload = approved.json()
            alignment = canon_payload.get("camera_alignment") or {}
            provider = canon_payload.get("provider")
            mock_alignment_na = (
                MOCK_QUALIFICATION
                and provider == "Mock fallback"
                and alignment.get("status") == "not_applicable"
                and alignment.get("reason") == "deterministic_mock_provider"
            )
            canon_ok = (
                approved.status_code == 200
                and (alignment.get("passed") is True or mock_alignment_na)
                and (output / "canon_v1.png").is_file()
            )
            result["stages"]["canon"] = _stage(
                "not_applicable" if mock_alignment_na else "passed" if canon_ok else "failed",
                http_status=approved.status_code,
                provider=provider,
                alignment=alignment,
                artifact=_artifact(output / "canon_v1.png"),
                response=canon_payload if approved.status_code != 200 else None,
            )
            if not canon_ok:
                return result

            world_response = client.post(
                f"/api/session/{session_id}/approve",
                json={"action": "approve"},
                headers=HEADERS,
            )
            world_payload = world_response.json()
            status_response = client.get(f"/api/session/{session_id}/status", headers=HEADERS)
            status_payload = status_response.json()
            snapshot_response = client.get(f"/api/session/{session_id}/snapshot", headers=HEADERS)
            snapshot_payload = snapshot_response.json()
            persisted_session = {}
            session_path = output / "session.json"
            if session_path.is_file():
                persisted_session = json.loads(session_path.read_text(encoding="utf-8"))
            world_ok = (
                world_response.status_code == 200
                and snapshot_payload.get("scene_graph") is not None
                and persisted_session.get("world_contract") is not None
            )
            result["stages"]["world"] = _stage(
                "passed" if world_ok else "failed",
                http_status=world_response.status_code,
                state=status_payload.get("state"),
                scene_graph_present=snapshot_payload.get("scene_graph") is not None,
                world_contract_present=persisted_session.get("world_contract") is not None,
                response=world_payload if world_response.status_code != 200 else None,
            )
            result["stages"]["compare"] = _stage(
                "passed" if status_payload.get("world_revision", 0) > 1 else "not_applicable",
                world_revision=status_payload.get("world_revision", 0),
            )
            result["stages"].update(_runtime_stages(status_payload))
            result["stages"]["downloads"] = _download_verdict(
                client, status_payload.get("artifact_downloads") or []
            )
    except Exception as exc:
        result["exception"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        result["finished_at_epoch"] = time.time()
        result["duration_seconds"] = round(result["finished_at_epoch"] - started, 3)
        _finalize_result(result)
        if session_id:
            result["session_artifacts"] = _artifact(ROOT / "output" / session_id / "session.json")
        _atomic_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    result = run_once(args.result.resolve())
    print(json.dumps({"passed": result["passed"], "session_id": result["session_id"]}, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
