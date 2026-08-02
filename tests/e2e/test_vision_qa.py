"""Vision QA E2E tests — AI vision model semantic validation of rendered scenes.

Uses the local qwen2.5vl:7b vision model as a semantic test oracle to verify
that rendered 3D world scenes match the conversation intent beyond pixel-level
metrics. The vision model evaluates the seven-category QA checklist (geometry,
count, camera, openings, finish, mood, scale) and returns a structured verdict.

This is an ADVISORY gate — failed checks are logged as warnings without
blocking the test suite. Auto-acceptance occurs only when:
  - pass == true AND confidence >= 0.8

Requirements: 20.1–20.5, 22.6, 23.3
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.framework.artifact_store import ArtifactStore
from tests.e2e.framework.config_loader import E2EConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the seven-category checklist (relative to project root)
_CHECKLIST_PATH = Path(__file__).resolve().parent / "config" / "vision_qa_checklist.json"

# Default confidence threshold for auto-acceptance (Req 20.3)
DEFAULT_CONFIDENCE_THRESHOLD = 0.8

# Vision model timeout (seconds) — generous to accommodate model loading
VISION_MODEL_TIMEOUT_S = 120


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_checklist(checklist_path: Path | None = None) -> dict[str, Any]:
    """Load the seven-category QA checklist from JSON.

    Args:
        checklist_path: Override path for testing. Defaults to the standard
                        config/vision_qa_checklist.json location.

    Returns:
        The parsed checklist dict.

    Raises:
        FileNotFoundError: If the checklist file doesn't exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    path = checklist_path or _CHECKLIST_PATH
    if not path.exists():
        raise FileNotFoundError(f"Vision QA checklist not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _build_vision_prompt(checklist: dict[str, Any]) -> str:
    """Build the structured prompt for the vision model from the checklist.

    Formats the categories into a clear evaluation prompt that requests
    the structured JSON verdict (pass, failed_checks, confidence).

    Args:
        checklist: The loaded checklist dict with categories and system_prompt.

    Returns:
        The formatted prompt string for the vision model.
    """
    categories = checklist.get("categories", [])
    system_prompt = checklist.get("system_prompt", "")
    verdict_schema = checklist.get("verdict_schema", {})

    category_lines = []
    for cat in categories:
        category_lines.append(
            f"- **{cat['name']}** ({cat['id']}): {cat['prompt']}"
        )

    prompt = (
        f"{system_prompt}\n\n"
        f"Evaluate this rendered 3D scene screenshot against the following "
        f"quality checklist categories:\n\n"
        f"{''.join(chr(10) + line for line in category_lines)}\n\n"
        f"Respond with a JSON object containing:\n"
        f"- \"pass\": {verdict_schema.get('pass', 'boolean')}\n"
        f"- \"failed_checks\": {verdict_schema.get('failed_checks', 'array of failed category IDs')}\n"
        f"- \"confidence\": {verdict_schema.get('confidence', 'float 0.0-1.0')}\n\n"
        f"JSON response:"
    )
    return prompt


def _parse_vision_verdict(raw_response: str) -> dict[str, Any] | None:
    """Parse the structured JSON verdict from the vision model response.

    Handles common formatting issues (markdown code blocks, leading text)
    and validates the required fields (pass, failed_checks, confidence).

    Args:
        raw_response: The raw text output from the vision model.

    Returns:
        A validated verdict dict with keys: pass, failed_checks, confidence.
        Returns None if parsing fails.
    """
    text = raw_response.strip()

    # Strip markdown code block wrappers if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Try to find JSON object in the response
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx == -1 or end_idx == -1:
        logger.warning("Vision model response contains no JSON object")
        return None

    json_str = text[start_idx : end_idx + 1]

    try:
        verdict = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse vision model JSON: %s", exc)
        return None

    # Validate required fields
    if "pass" not in verdict:
        logger.warning("Vision verdict missing 'pass' field")
        return None
    if "failed_checks" not in verdict:
        logger.warning("Vision verdict missing 'failed_checks' field")
        return None
    if "confidence" not in verdict:
        logger.warning("Vision verdict missing 'confidence' field")
        return None

    # Type coercion and validation
    verdict["pass"] = bool(verdict["pass"])

    if not isinstance(verdict["failed_checks"], list):
        verdict["failed_checks"] = []

    try:
        verdict["confidence"] = float(verdict["confidence"])
    except (ValueError, TypeError):
        logger.warning(
            "Vision verdict 'confidence' not numeric: %s", verdict["confidence"]
        )
        return None

    # Clamp confidence to [0.0, 1.0]
    verdict["confidence"] = max(0.0, min(1.0, verdict["confidence"]))

    return verdict


async def _call_vision_model(
    screenshot_b64: str,
    prompt: str,
    model_name: str,
    timeout_s: float = VISION_MODEL_TIMEOUT_S,
) -> str | None:
    """Call the qwen2.5vl:7b vision model via Ollama with a screenshot.

    Args:
        screenshot_b64: Base64-encoded PNG screenshot of the rendered scene.
        prompt: The evaluation prompt (built from checklist).
        model_name: The Ollama model identifier (e.g. "qwen2.5vl:7b").
        timeout_s: Maximum time to wait for a response.

    Returns:
        The model's raw text response, or None if unavailable/timeout.
    """
    import httpx

    ollama_url = "http://127.0.0.1:11434"

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [screenshot_b64],
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,  # Low temp for consistent structured output
            "num_predict": 512,  # Sufficient for JSON verdict
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                f"{ollama_url}/api/chat",
                json=payload,
            )
            if response.status_code != 200:
                logger.warning(
                    "Ollama returned HTTP %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return None

            data = response.json()
            message = data.get("message", {})
            return message.get("content", "")

    except httpx.TimeoutException:
        logger.warning(
            "Vision model timed out after %.0fs", timeout_s
        )
        return None
    except (httpx.HTTPError, OSError) as exc:
        logger.warning("Vision model unavailable: %s", exc)
        return None


def _evaluate_verdict(
    verdict: dict[str, Any],
    confidence_threshold: float,
) -> tuple[bool, str]:
    """Evaluate a vision verdict against acceptance criteria.

    Auto-accept when pass == true AND confidence >= threshold (Req 20.3).
    Log as advisory warning otherwise (Req 20.4).

    Args:
        verdict: The parsed verdict dict (pass, failed_checks, confidence).
        confidence_threshold: Minimum confidence for auto-acceptance.

    Returns:
        A tuple of (auto_accepted: bool, reason: str).
    """
    is_pass = verdict["pass"]
    confidence = verdict["confidence"]
    failed_checks = verdict["failed_checks"]

    if is_pass and confidence >= confidence_threshold:
        return True, (
            f"Vision QA PASSED — confidence {confidence:.2f} "
            f"(threshold {confidence_threshold})"
        )

    # Advisory failure — log but don't block
    reasons = []
    if not is_pass:
        reasons.append(
            f"pass=false, failed_checks={failed_checks}"
        )
    if confidence < confidence_threshold:
        reasons.append(
            f"confidence={confidence:.2f} < threshold={confidence_threshold}"
        )

    return False, (
        f"Vision QA advisory WARNING — {'; '.join(reasons)}"
    )


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vision_qa_config(e2e_config: E2EConfig) -> dict[str, Any]:
    """Provide vision QA configuration from e2e_config.yaml."""
    return {
        "model_name": e2e_config.vision_qa.model_name,
        "confidence_threshold": e2e_config.vision_qa.confidence_threshold,
        "checklist_path": e2e_config.vision_qa.checklist_path,
        "blocking": e2e_config.vision_qa.blocking,
    }


@pytest.fixture
def checklist() -> dict[str, Any]:
    """Load the seven-category QA checklist."""
    return _load_checklist()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.gpu
@pytest.mark.asyncio
async def test_vision_qa_semantic_validation(
    artifact_store: ArtifactStore,
    vision_qa_config: dict[str, Any],
    checklist: dict[str, Any],
    vram_lease,
) -> None:
    """E2E test: submit rendered World screenshot to qwen2.5vl:7b for semantic QA.

    Exercises the full vision QA path:
    1. Acquire VRAM lease for the vision model (Req 21.5)
    2. Capture/load the World screenshot
    3. Build the seven-category prompt from the checklist
    4. Submit to qwen2.5vl:7b via Ollama
    5. Parse the structured JSON verdict
    6. Auto-accept if pass==true AND confidence>=0.8 (Req 20.3)
    7. Log warnings (advisory, not blocking) otherwise (Req 20.4)
    8. Store verdict JSON alongside screenshot in artifacts (Req 23.3)

    Requirements: 20.1–20.5, 21.5, 22.6, 23.3
    """
    import base64
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    model_name = vision_qa_config["model_name"]
    confidence_threshold = vision_qa_config["confidence_threshold"]

    # Step 1: Acquire VRAM lease for VISION_QA (Req 21.5)
    try:
        from tests.e2e.conftest import _import_resource_arbiter
        ra = _import_resource_arbiter()
        ResourceKind = ra.ResourceKind
        lease_result = vram_lease.acquire(ResourceKind.VISION_QA)
    except Exception as exc:
        logger.warning(
            "VRAM lease acquisition failed — proceeding without lease: %s", exc
        )
        lease_result = None

    if lease_result is not None and not lease_result.acquired:
        # VRAM contention — skip gracefully (Req 20.5)
        _store_unavailable_verdict(artifact_store, "vram_contention_timeout")
        pytest.skip(
            "Vision QA skipped: VRAM contention timeout. "
            "Status: vision_qa_unavailable"
        )

    start_time = time.monotonic()

    # Step 2: Obtain the World screenshot
    # Try to find the most recent world screenshot in artifacts or capture one
    screenshot_b64 = await _obtain_world_screenshot(artifact_store)

    if screenshot_b64 is None:
        # No screenshot available — skip gracefully (Req 20.5)
        _store_unavailable_verdict(artifact_store, "no_screenshot_available")
        _release_vram_lease(vram_lease)
        pytest.skip(
            "Vision QA skipped: no World screenshot available for evaluation. "
            "Run the full pipeline first."
        )

    # Step 3: Build the prompt from the checklist (Req 20.1)
    prompt = _build_vision_prompt(checklist)

    # Step 4: Call the vision model (Req 20.1)
    raw_response = await _call_vision_model(
        screenshot_b64=screenshot_b64,
        prompt=prompt,
        model_name=model_name,
    )

    elapsed = time.monotonic() - start_time

    # Mark computation done for VRAM release timing (Req 21.3)
    if lease_result is not None and lease_result.acquired:
        vram_lease.mark_computation_done()

    if raw_response is None:
        # Vision model unavailable — skip gracefully (Req 20.5)
        _store_unavailable_verdict(artifact_store, "vision_qa_unavailable")
        _release_vram_lease(vram_lease)
        pytest.skip(
            "Vision QA skipped: qwen2.5vl:7b unavailable or timed out. "
            "Status: vision_qa_unavailable"
        )

    # Step 5: Parse the structured verdict (Req 20.2)
    verdict = _parse_vision_verdict(raw_response)

    if verdict is None:
        # Could not parse verdict — log warning, store raw response
        logger.warning(
            "Vision QA: could not parse structured verdict from model response"
        )
        _store_parse_failure(artifact_store, raw_response, elapsed)
        _release_vram_lease(vram_lease)
        # Advisory: don't fail the test for unparseable output
        return

    # Step 6 & 7: Evaluate verdict (Req 20.3, 20.4)
    auto_accepted, reason = _evaluate_verdict(verdict, confidence_threshold)

    if auto_accepted:
        logger.info(reason)
    else:
        # Advisory gate: log as warning, do NOT fail (Req 20.4)
        logger.warning(reason)

    # Step 8: Store verdict and screenshot in artifacts (Req 23.3)
    verdict_record = {
        "test": "test_vision_qa_semantic_validation",
        "model_name": model_name,
        "verdict": verdict,
        "auto_accepted": auto_accepted,
        "reason": reason,
        "elapsed_s": round(elapsed, 2),
        "confidence_threshold": confidence_threshold,
        "checklist_version": checklist.get("version", "unknown"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    artifact_store.store_artifact(
        "vision_qa",
        "vision_verdict.json",
        json.dumps(verdict_record, indent=2),
    )

    # Store the screenshot alongside the verdict
    if screenshot_b64:
        screenshot_bytes = base64.b64decode(screenshot_b64)
        artifact_store.store_artifact(
            "vision_qa",
            "world_screenshot.png",
            screenshot_bytes,
        )

    # Release VRAM lease (Req 21.3)
    _release_vram_lease(vram_lease)

    # Advisory assertion — warnings logged but test doesn't fail (Req 20.4)
    # The test passes regardless since vision QA is advisory (blocking=false)
    if not auto_accepted:
        logger.warning(
            "Vision QA advisory: %d failed checks — %s",
            len(verdict.get("failed_checks", [])),
            verdict.get("failed_checks", []),
        )


@pytest.mark.gpu
def test_vision_qa_checklist_structure(checklist: dict[str, Any]) -> None:
    """Validate that the vision QA checklist has the expected seven-category structure.

    Ensures the checklist file is well-formed with all required fields
    and exactly seven categories as specified in the design.

    Requirements: 20.1
    """
    # Validate top-level structure
    assert "categories" in checklist, "Checklist missing 'categories' field"
    assert "system_prompt" in checklist, "Checklist missing 'system_prompt' field"
    assert "verdict_schema" in checklist, "Checklist missing 'verdict_schema' field"

    categories = checklist["categories"]
    assert len(categories) == 7, (
        f"Expected 7 categories, got {len(categories)}"
    )

    # Validate expected category IDs
    expected_ids = {"geometry", "count", "camera", "openings", "finish", "mood", "scale"}
    actual_ids = {cat["id"] for cat in categories}
    assert actual_ids == expected_ids, (
        f"Category IDs mismatch.\n"
        f"Expected: {sorted(expected_ids)}\n"
        f"Actual: {sorted(actual_ids)}"
    )

    # Validate each category has required fields
    for cat in categories:
        assert "id" in cat, f"Category missing 'id' field: {cat}"
        assert "name" in cat, f"Category missing 'name' field: {cat}"
        assert "prompt" in cat, f"Category missing 'prompt' field: {cat}"
        assert "weight" in cat, f"Category missing 'weight' field: {cat}"
        assert isinstance(cat["weight"], (int, float)), (
            f"Category '{cat['id']}' weight must be numeric"
        )


@pytest.mark.gpu
def test_vision_verdict_auto_acceptance_logic() -> None:
    """Verify the auto-acceptance logic: pass==true AND confidence>=0.8.

    Tests the verdict evaluation function directly to confirm:
    - pass=true + confidence>=0.8 → auto-accepted
    - pass=true + confidence<0.8 → advisory warning
    - pass=false + any confidence → advisory warning

    Requirements: 20.3, 20.4
    """
    threshold = DEFAULT_CONFIDENCE_THRESHOLD

    # Case 1: pass=true, confidence=0.95 → auto-accept
    verdict_pass_high = {"pass": True, "failed_checks": [], "confidence": 0.95}
    accepted, reason = _evaluate_verdict(verdict_pass_high, threshold)
    assert accepted is True, f"Expected auto-accept, got: {reason}"

    # Case 2: pass=true, confidence=0.8 → auto-accept (boundary)
    verdict_pass_boundary = {"pass": True, "failed_checks": [], "confidence": 0.80}
    accepted, reason = _evaluate_verdict(verdict_pass_boundary, threshold)
    assert accepted is True, f"Expected auto-accept at boundary, got: {reason}"

    # Case 3: pass=true, confidence=0.79 → advisory warning
    verdict_pass_low = {"pass": True, "failed_checks": [], "confidence": 0.79}
    accepted, reason = _evaluate_verdict(verdict_pass_low, threshold)
    assert accepted is False, f"Expected advisory warning for low confidence, got: {reason}"

    # Case 4: pass=false, confidence=0.95 → advisory warning
    verdict_fail_high = {"pass": False, "failed_checks": ["geometry"], "confidence": 0.95}
    accepted, reason = _evaluate_verdict(verdict_fail_high, threshold)
    assert accepted is False, f"Expected advisory warning for failed check, got: {reason}"

    # Case 5: pass=false, confidence=0.5 → advisory warning
    verdict_fail_low = {"pass": False, "failed_checks": ["scale", "mood"], "confidence": 0.5}
    accepted, reason = _evaluate_verdict(verdict_fail_low, threshold)
    assert accepted is False, f"Expected advisory warning, got: {reason}"


@pytest.mark.gpu
def test_vision_verdict_parsing() -> None:
    """Verify structured JSON verdict parsing handles valid and edge cases.

    Tests _parse_vision_verdict with various response formats the model
    might produce (clean JSON, markdown-wrapped, trailing text).

    Requirements: 20.2
    """
    # Clean JSON
    clean = '{"pass": true, "failed_checks": [], "confidence": 0.92}'
    result = _parse_vision_verdict(clean)
    assert result is not None
    assert result["pass"] is True
    assert result["failed_checks"] == []
    assert result["confidence"] == 0.92

    # Markdown-wrapped JSON
    markdown = '```json\n{"pass": false, "failed_checks": ["geometry", "scale"], "confidence": 0.75}\n```'
    result = _parse_vision_verdict(markdown)
    assert result is not None
    assert result["pass"] is False
    assert result["failed_checks"] == ["geometry", "scale"]
    assert result["confidence"] == 0.75

    # JSON with leading text
    leading_text = 'Based on my analysis:\n{"pass": true, "failed_checks": [], "confidence": 0.88}'
    result = _parse_vision_verdict(leading_text)
    assert result is not None
    assert result["pass"] is True
    assert result["confidence"] == 0.88

    # Invalid — no JSON
    no_json = "I cannot evaluate this image because it is too dark."
    result = _parse_vision_verdict(no_json)
    assert result is None

    # Missing required field
    missing_field = '{"pass": true, "confidence": 0.9}'
    result = _parse_vision_verdict(missing_field)
    assert result is None

    # Confidence clamped to [0, 1]
    over_confidence = '{"pass": true, "failed_checks": [], "confidence": 1.5}'
    result = _parse_vision_verdict(over_confidence)
    assert result is not None
    assert result["confidence"] == 1.0

    negative_confidence = '{"pass": true, "failed_checks": [], "confidence": -0.3}'
    result = _parse_vision_verdict(negative_confidence)
    assert result is not None
    assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _obtain_world_screenshot(
    artifact_store: ArtifactStore,
) -> str | None:
    """Obtain a base64-encoded World screenshot for vision QA evaluation.

    Looks for an existing world screenshot in the artifact store's visual
    layer, or falls back to any available world render. Returns None if
    no screenshot is available.

    Args:
        artifact_store: The current run's artifact store.

    Returns:
        Base64-encoded PNG string, or None if unavailable.
    """
    import base64

    # Check for a world screenshot in the visual artifacts
    if artifact_store.run_dir is None:
        return None

    visual_dir = artifact_store.run_dir / "visual"
    if visual_dir.exists():
        # Look for world-related screenshots
        for pattern in ["world*.png", "world_*.png", "canon*.png"]:
            matches = list(visual_dir.glob(pattern))
            if matches:
                image_bytes = matches[0].read_bytes()
                return base64.b64encode(image_bytes).decode("utf-8")

    # Check for screenshot in gpu artifacts (from FLUX generation)
    gpu_dir = artifact_store.run_dir / "gpu"
    if gpu_dir.exists():
        matches = list(gpu_dir.glob("*.png"))
        if matches:
            image_bytes = matches[0].read_bytes()
            return base64.b64encode(image_bytes).decode("utf-8")

    # No screenshot available — return None for graceful skip (Req 20.5)
    return None


def _store_unavailable_verdict(
    artifact_store: ArtifactStore,
    status: str,
) -> None:
    """Store a vision_qa_unavailable status record in artifacts.

    Called when the vision model cannot be reached or VRAM is contended.

    Args:
        artifact_store: The current run's artifact store.
        status: The unavailability reason (e.g. "vision_qa_unavailable",
                "vram_contention_timeout", "no_screenshot_available").
    """
    record = {
        "test": "test_vision_qa_semantic_validation",
        "status": status,
        "verdict": None,
        "auto_accepted": False,
        "reason": f"Vision QA skipped: {status}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    artifact_store.store_artifact(
        "vision_qa",
        "vision_verdict.json",
        json.dumps(record, indent=2),
    )


def _store_parse_failure(
    artifact_store: ArtifactStore,
    raw_response: str,
    elapsed_s: float,
) -> None:
    """Store a record when the vision model response cannot be parsed.

    Args:
        artifact_store: The current run's artifact store.
        raw_response: The unparseable raw model output.
        elapsed_s: Time taken for the model call.
    """
    record = {
        "test": "test_vision_qa_semantic_validation",
        "status": "parse_failure",
        "verdict": None,
        "raw_response": raw_response[:2000],  # Truncate for safety
        "auto_accepted": False,
        "reason": "Could not parse structured JSON verdict from model response",
        "elapsed_s": round(elapsed_s, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    artifact_store.store_artifact(
        "vision_qa",
        "vision_verdict.json",
        json.dumps(record, indent=2),
    )


def _release_vram_lease(vram_lease) -> None:
    """Release the VRAM lease if it was acquired.

    Safe to call multiple times — the facade tracks release state.
    """
    try:
        vram_lease.release()
    except Exception as exc:
        logger.warning("Error releasing VRAM lease: %s", exc)
