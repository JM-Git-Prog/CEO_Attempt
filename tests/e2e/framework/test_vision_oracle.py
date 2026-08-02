"""Unit tests for the VisionOracle module.

Tests cover:
- Checklist loading from JSON
- Verdict parsing (valid, malformed, edge cases)
- Auto-accept logic
- Unavailability handling
- Prompt construction

Requirements: 20.1–20.5, 21.5
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.e2e.framework.vision_oracle import (
    ChecklistCategory,
    VisionChecklist,
    VisionOracle,
    VisionOracleUnavailable,
    VisionVerdict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_checklist() -> VisionChecklist:
    """A minimal test checklist."""
    return VisionChecklist(
        categories=[
            ChecklistCategory(id="geometry", name="Geometry", prompt="Check geometry"),
            ChecklistCategory(id="count", name="Count", prompt="Check count"),
            ChecklistCategory(id="camera", name="Camera", prompt="Check camera"),
            ChecklistCategory(id="openings", name="Openings", prompt="Check openings"),
            ChecklistCategory(id="finish", name="Finish", prompt="Check finish"),
            ChecklistCategory(id="mood", name="Mood", prompt="Check mood"),
            ChecklistCategory(id="scale", name="Scale", prompt="Check scale"),
        ],
        system_prompt="You are a QA inspector.",
        version="1.0.0",
    )


@pytest.fixture
def oracle(sample_checklist: VisionChecklist) -> VisionOracle:
    """A VisionOracle instance with a pre-loaded checklist."""
    return VisionOracle(
        checklist=sample_checklist,
        model_name="qwen2.5vl:7b",
        confidence_threshold=0.8,
    )


# ---------------------------------------------------------------------------
# VisionVerdict tests
# ---------------------------------------------------------------------------


class TestVisionVerdict:
    """Test VisionVerdict creation and serialization."""

    def test_to_dict_pass(self):
        verdict = VisionVerdict(
            pass_=True,
            failed_checks=[],
            confidence=0.95,
            status="completed",
            raw_response='{"pass": true}',
        )
        d = verdict.to_dict()
        assert d["pass"] is True
        assert d["failed_checks"] == []
        assert d["confidence"] == 0.95
        assert d["status"] == "completed"

    def test_to_dict_fail(self):
        verdict = VisionVerdict(
            pass_=False,
            failed_checks=["geometry", "scale"],
            confidence=0.7,
            status="completed",
            raw_response='{"pass": false}',
        )
        d = verdict.to_dict()
        assert d["pass"] is False
        assert d["failed_checks"] == ["geometry", "scale"]
        assert d["confidence"] == 0.7

    def test_unavailable_factory(self):
        verdict = VisionVerdict.unavailable("model timeout")
        assert verdict.status == "vision_qa_unavailable"
        assert verdict.pass_ is False
        assert verdict.confidence == 0.0
        assert "model timeout" in verdict.raw_response

    def test_parse_error_factory(self):
        verdict = VisionVerdict.parse_error("garbage response")
        assert verdict.status == "parse_error"
        assert verdict.pass_ is False
        assert verdict.confidence == 0.0
        assert "garbage response" in verdict.raw_response


# ---------------------------------------------------------------------------
# Checklist loading tests
# ---------------------------------------------------------------------------


class TestVisionChecklist:
    """Test VisionChecklist loading from JSON."""

    def test_load_from_json(self, tmp_path: Path):
        checklist_data = {
            "version": "1.0.0",
            "description": "Test checklist",
            "categories": [
                {"id": "geometry", "name": "Geometry", "prompt": "Check it", "weight": 1.0},
                {"id": "count", "name": "Count", "prompt": "Count it", "weight": 0.8},
            ],
            "system_prompt": "Be strict.",
            "verdict_schema": {},
        }
        path = tmp_path / "checklist.json"
        path.write_text(json.dumps(checklist_data), encoding="utf-8")

        checklist = VisionChecklist.from_json(path)
        assert len(checklist.categories) == 2
        assert checklist.categories[0].id == "geometry"
        assert checklist.categories[1].weight == 0.8
        assert checklist.system_prompt == "Be strict."
        assert checklist.version == "1.0.0"

    def test_load_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            VisionChecklist.from_json(tmp_path / "nonexistent.json")

    def test_load_invalid_json(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            VisionChecklist.from_json(path)


# ---------------------------------------------------------------------------
# Verdict parsing tests
# ---------------------------------------------------------------------------


class TestVerdictParsing:
    """Test the _parse_verdict method handles various response formats."""

    def test_valid_pass_verdict(self, oracle: VisionOracle):
        raw = '{"pass": true, "failed_checks": [], "confidence": 0.92}'
        verdict = oracle._parse_verdict(raw)
        assert verdict.pass_ is True
        assert verdict.failed_checks == []
        assert verdict.confidence == 0.92
        assert verdict.status == "completed"

    def test_valid_fail_verdict(self, oracle: VisionOracle):
        raw = '{"pass": false, "failed_checks": ["geometry", "scale"], "confidence": 0.85}'
        verdict = oracle._parse_verdict(raw)
        assert verdict.pass_ is False
        assert verdict.failed_checks == ["geometry", "scale"]
        assert verdict.confidence == 0.85

    def test_json_in_markdown_fence(self, oracle: VisionOracle):
        raw = '```json\n{"pass": true, "failed_checks": [], "confidence": 0.9}\n```'
        verdict = oracle._parse_verdict(raw)
        assert verdict.pass_ is True
        assert verdict.confidence == 0.9

    def test_json_embedded_in_text(self, oracle: VisionOracle):
        raw = 'Here is the result: {"pass": false, "failed_checks": ["mood"], "confidence": 0.75} end.'
        verdict = oracle._parse_verdict(raw)
        assert verdict.pass_ is False
        assert verdict.failed_checks == ["mood"]

    def test_invalid_category_filtered(self, oracle: VisionOracle):
        raw = '{"pass": false, "failed_checks": ["geometry", "invalid_cat", "scale"], "confidence": 0.8}'
        verdict = oracle._parse_verdict(raw)
        assert "geometry" in verdict.failed_checks
        assert "scale" in verdict.failed_checks
        assert "invalid_cat" not in verdict.failed_checks

    def test_confidence_clamped_high(self, oracle: VisionOracle):
        raw = '{"pass": true, "failed_checks": [], "confidence": 1.5}'
        verdict = oracle._parse_verdict(raw)
        assert verdict.confidence == 1.0

    def test_confidence_clamped_low(self, oracle: VisionOracle):
        raw = '{"pass": true, "failed_checks": [], "confidence": -0.5}'
        verdict = oracle._parse_verdict(raw)
        assert verdict.confidence == 0.0

    def test_pass_true_with_failed_checks_becomes_false(self, oracle: VisionOracle):
        """If pass=True but failed_checks is non-empty, resolve to pass=False."""
        raw = '{"pass": true, "failed_checks": ["geometry"], "confidence": 0.9}'
        verdict = oracle._parse_verdict(raw)
        assert verdict.pass_ is False
        assert verdict.failed_checks == ["geometry"]

    def test_non_json_returns_parse_error(self, oracle: VisionOracle):
        raw = "I cannot evaluate this image properly."
        verdict = oracle._parse_verdict(raw)
        assert verdict.status == "parse_error"

    def test_empty_response_returns_parse_error(self, oracle: VisionOracle):
        verdict = oracle._parse_verdict("")
        assert verdict.status == "parse_error"

    def test_pass_coerced_from_string(self, oracle: VisionOracle):
        raw = '{"pass": "true", "failed_checks": [], "confidence": 0.9}'
        verdict = oracle._parse_verdict(raw)
        assert verdict.pass_ is True

    def test_missing_confidence_defaults_zero(self, oracle: VisionOracle):
        raw = '{"pass": true, "failed_checks": []}'
        verdict = oracle._parse_verdict(raw)
        assert verdict.confidence == 0.0


# ---------------------------------------------------------------------------
# Auto-accept logic tests
# ---------------------------------------------------------------------------


class TestAutoAccept:
    """Test auto-accept decision logic (Requirement 20.3)."""

    def test_auto_accept_pass_high_confidence(self, oracle: VisionOracle):
        verdict = VisionVerdict(
            pass_=True, failed_checks=[], confidence=0.9, status="completed"
        )
        assert oracle.is_auto_accept(verdict) is True

    def test_auto_accept_at_threshold(self, oracle: VisionOracle):
        verdict = VisionVerdict(
            pass_=True, failed_checks=[], confidence=0.8, status="completed"
        )
        assert oracle.is_auto_accept(verdict) is True

    def test_no_auto_accept_low_confidence(self, oracle: VisionOracle):
        verdict = VisionVerdict(
            pass_=True, failed_checks=[], confidence=0.79, status="completed"
        )
        assert oracle.is_auto_accept(verdict) is False

    def test_no_auto_accept_fail(self, oracle: VisionOracle):
        verdict = VisionVerdict(
            pass_=False, failed_checks=["geometry"], confidence=0.95, status="completed"
        )
        assert oracle.is_auto_accept(verdict) is False

    def test_no_auto_accept_unavailable(self, oracle: VisionOracle):
        verdict = VisionVerdict.unavailable("timeout")
        assert oracle.is_auto_accept(verdict) is False

    def test_no_auto_accept_parse_error(self, oracle: VisionOracle):
        verdict = VisionVerdict.parse_error("bad response")
        assert oracle.is_auto_accept(verdict) is False


# ---------------------------------------------------------------------------
# Evaluate method integration tests (mocked Ollama)
# ---------------------------------------------------------------------------


class TestEvaluate:
    """Test the evaluate() method with mocked Ollama calls."""

    def test_evaluate_returns_completed_verdict(self, oracle: VisionOracle):
        mock_response = '{"pass": true, "failed_checks": [], "confidence": 0.92}'
        with patch.object(oracle, "_call_ollama", return_value=mock_response):
            verdict = oracle.evaluate(b"fake_image_bytes")
        assert verdict.status == "completed"
        assert verdict.pass_ is True
        assert verdict.confidence == 0.92

    def test_evaluate_handles_unavailability(self, oracle: VisionOracle):
        with patch.object(
            oracle,
            "_call_ollama",
            side_effect=VisionOracleUnavailable("connection refused"),
        ):
            verdict = oracle.evaluate(b"fake_image_bytes")
        assert verdict.status == "vision_qa_unavailable"
        assert verdict.pass_ is False

    def test_evaluate_handles_parse_error(self, oracle: VisionOracle):
        with patch.object(oracle, "_call_ollama", return_value="nonsense"):
            verdict = oracle.evaluate(b"fake_image_bytes")
        assert verdict.status == "parse_error"

    def test_evaluate_accepts_base64_string(self, oracle: VisionOracle):
        mock_response = '{"pass": true, "failed_checks": [], "confidence": 0.85}'
        with patch.object(oracle, "_call_ollama", return_value=mock_response) as mock:
            verdict = oracle.evaluate("base64encodeddata")
        # Verify it passed the base64 string through correctly
        call_args = mock.call_args
        assert call_args.kwargs["image_b64"] == "base64encodeddata"
        assert verdict.pass_ is True

    def test_evaluate_with_additional_context(self, oracle: VisionOracle):
        mock_response = '{"pass": true, "failed_checks": [], "confidence": 0.88}'
        with patch.object(oracle, "_call_ollama", return_value=mock_response) as mock:
            verdict = oracle.evaluate(
                b"image_data",
                additional_context="A cozy living room with a fireplace",
            )
        # Check that context was passed to the prompt builder
        call_args = mock.call_args
        assert "cozy living room" in call_args.kwargs["user_prompt"]


# ---------------------------------------------------------------------------
# Prompt construction tests
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    """Test the prompt includes all seven categories."""

    def test_prompt_contains_all_categories(self, oracle: VisionOracle):
        prompt = oracle._build_prompt()
        for cat in oracle.checklist.categories:
            assert cat.id.upper() in prompt
            assert cat.name in prompt

    def test_prompt_contains_output_format(self, oracle: VisionOracle):
        prompt = oracle._build_prompt()
        assert '"pass"' in prompt
        assert '"failed_checks"' in prompt
        assert '"confidence"' in prompt

    def test_prompt_includes_additional_context(self, oracle: VisionOracle):
        prompt = oracle._build_prompt("A dark castle hallway")
        assert "A dark castle hallway" in prompt
        assert "Scene context" in prompt


# ---------------------------------------------------------------------------
# JSON extraction tests
# ---------------------------------------------------------------------------


class TestJsonExtraction:
    """Test the _extract_json static method."""

    def test_pure_json(self):
        text = '{"pass": true, "failed_checks": [], "confidence": 0.9}'
        result = VisionOracle._extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["pass"] is True

    def test_json_with_trailing_text(self):
        text = '{"pass": true, "failed_checks": [], "confidence": 0.9}\nSome extra text'
        result = VisionOracle._extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["pass"] is True

    def test_markdown_fenced_json(self):
        text = '```json\n{"pass": false, "failed_checks": ["mood"], "confidence": 0.7}\n```'
        result = VisionOracle._extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["pass"] is False

    def test_embedded_json(self):
        text = 'The analysis shows: {"pass": true, "confidence": 0.8, "failed_checks": []} is the result.'
        result = VisionOracle._extract_json(text)
        assert result is not None
        data = json.loads(result)
        assert data["pass"] is True

    def test_no_json_returns_none(self):
        text = "No JSON content here at all"
        result = VisionOracle._extract_json(text)
        assert result is None
