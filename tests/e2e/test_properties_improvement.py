"""Property-based tests for the self-improving loop modules.

Tests validate:
- Property 19: Test Artifact Organization
- Property 20: Cloud Analysis Verdict Routing
- Property 21: Proposed Test Format Validity
- Property 22: Threshold Recommendation Structure

Uses Hypothesis for property-based testing.

**Validates: Requirements 23.4, 23.5, 24.3–24.5, 25.3, 26.3**
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies for generating test data
# ---------------------------------------------------------------------------

# Strategy for valid run IDs (timestamp-like strings)
run_id_st = st.from_regex(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{6}", fullmatch=True)

# Strategy for test layer names
layer_st = st.sampled_from(
    ["visual", "perceptual", "scene", "accessibility", "gpu", "vision_qa"]
)

# Strategy for failure categories
category_st = st.sampled_from(
    ["regression", "flaky", "threshold", "infrastructure", "genuine_bug"]
)

# Strategy for confidence values
confidence_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

# Strategy for metric names
metric_name_st = st.sampled_from(["ssim", "lpips", "clip_cosine"])

# Strategy for test function names
test_name_st = st.from_regex(r"test_[a-z][a-z0-9_]{3,30}", fullmatch=True)


# ---------------------------------------------------------------------------
# Property 19: Test Artifact Organization
# **Validates: Requirements 23.4, 23.5**
# ---------------------------------------------------------------------------


class TestArtifactOrganization:
    """Property 19: Test Artifact Organization.

    *For any* test run, all artifacts SHALL be stored under
    tests/e2e/artifacts/{run_id}/ with subdirectories for each layer
    (visual, perceptual, scene, accessibility, gpu, vision_qa), and any
    test failure output SHALL include the artifact directory path.
    """

    @given(run_id=run_id_st, layer=layer_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_artifact_store_creates_correct_subdirectories(
        self, run_id: str, layer: str, tmp_path: Path
    ):
        """Artifact store creates all required layer subdirectories.

        **Validates: Requirements 23.4**
        """
        from tests.e2e.framework.artifact_store import ArtifactStore, ARTIFACT_LAYERS

        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(base_dir=td)
            run_dir = store.init_run(run_id)

            # All layer subdirectories must exist
            for expected_layer in ARTIFACT_LAYERS:
                layer_dir = run_dir / expected_layer
                assert layer_dir.exists(), f"Missing layer directory: {expected_layer}"
                assert layer_dir.is_dir()

            # Run directory is under the base path with the run_id
            assert run_dir.parent == Path(td)
            assert run_dir.name == run_id

    @given(run_id=run_id_st, layer=layer_st)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_failure_message_includes_artifact_path(
        self, run_id: str, layer: str, tmp_path: Path
    ):
        """Failure messages include the artifact directory path.

        **Validates: Requirements 23.5**
        """
        from tests.e2e.framework.artifact_store import ArtifactStore

        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(base_dir=td)
            store.init_run(run_id)

            msg = store.failure_message(layer, "test_example", "Something failed")

            # Message must contain the artifact directory path
            assert td in msg or run_id in msg
            assert "Artifacts:" in msg

    @given(run_id=run_id_st, layer=layer_st)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_artifacts_stored_under_correct_layer(
        self, run_id: str, layer: str, tmp_path: Path
    ):
        """Stored artifacts land in the correct layer subdirectory.

        **Validates: Requirements 23.4**
        """
        from tests.e2e.framework.artifact_store import ArtifactStore

        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(base_dir=td)
            store.init_run(run_id)

            artifact_path = store.store_artifact(layer, "test_file.json", '{"test": true}')

            # Artifact must be under {run_id}/{layer}/
            assert artifact_path.parent.name == layer
            assert artifact_path.parent.parent.name == run_id
            assert artifact_path.exists()


# ---------------------------------------------------------------------------
# Property 20: Cloud Analysis Verdict Routing
# **Validates: Requirements 24.3, 24.4, 24.5**
# ---------------------------------------------------------------------------


class TestCloudAnalysisVerdictRouting:
    """Property 20: Cloud Analysis Verdict Routing.

    *For any* cloud model analysis result with confidence >= 0.8, the system SHALL:
    - Tag tests categorized as "flaky" for retry-tolerance review
    - Propose updated threshold values for tests categorized as "threshold"

    And all analysis results SHALL be stored in
    tests/e2e/artifacts/{run_id}/cloud_analysis.json.
    """

    @given(
        test_name=test_name_st,
        confidence=st.floats(min_value=0.8, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_flaky_verdict_tagged_for_review(self, test_name: str, confidence: float):
        """Flaky verdicts with confidence >= 0.8 are tagged for retry-tolerance review.

        **Validates: Requirements 24.3**
        """
        from tests.e2e.improvement.failure_analyzer import (
            AnalysisVerdict,
            route_verdicts,
        )

        verdict = AnalysisVerdict(
            root_cause="Timing-dependent failure",
            suggested_fix="Add retry logic",
            confidence=confidence,
            category="flaky",
            test_name=test_name,
            tagged_flaky=True,  # High confidence flaky
        )

        report = route_verdicts([verdict])
        assert test_name in report.flaky_tests

    @given(
        test_name=test_name_st,
        confidence=st.floats(min_value=0.0, max_value=0.79, allow_nan=False),
    )
    @settings(max_examples=30)
    def test_low_confidence_flaky_not_tagged(self, test_name: str, confidence: float):
        """Flaky verdicts with confidence < 0.8 are NOT auto-tagged.

        **Validates: Requirements 24.3**
        """
        from tests.e2e.improvement.failure_analyzer import (
            AnalysisVerdict,
            route_verdicts,
        )

        verdict = AnalysisVerdict(
            root_cause="Possible timing issue",
            suggested_fix="Investigate",
            confidence=confidence,
            category="flaky",
            test_name=test_name,
            tagged_flaky=False,  # Low confidence → not tagged
        )

        report = route_verdicts([verdict])
        assert test_name not in report.flaky_tests

    @given(
        test_name=test_name_st,
        confidence=st.floats(min_value=0.8, max_value=1.0, allow_nan=False),
        threshold_value=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_threshold_verdict_proposes_updated_value(
        self, test_name: str, confidence: float, threshold_value: float
    ):
        """Threshold verdicts with confidence >= 0.8 propose updated values.

        **Validates: Requirements 24.4**
        """
        from tests.e2e.improvement.failure_analyzer import (
            AnalysisVerdict,
            route_verdicts,
        )

        verdict = AnalysisVerdict(
            root_cause="Metric barely missed threshold",
            suggested_fix=f"Update threshold to {threshold_value:.4f}",
            confidence=confidence,
            category="threshold",
            test_name=test_name,
            proposed_threshold=threshold_value,
        )

        report = route_verdicts([verdict])
        assert test_name in report.threshold_proposals
        assert report.threshold_proposals[test_name] == threshold_value

    @given(run_id=run_id_st, category=category_st, confidence=confidence_st)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_analysis_report_stores_as_json(
        self, run_id: str, category: str, confidence: float, tmp_path: Path
    ):
        """All analysis results are stored in cloud_analysis.json.

        **Validates: Requirements 24.5**
        """
        from tests.e2e.improvement.failure_analyzer import (
            AnalysisVerdict,
            CloudAnalysisReport,
            store_analysis_report,
        )

        verdict = AnalysisVerdict(
            root_cause="Test root cause",
            suggested_fix="Fix suggestion",
            confidence=confidence,
            category=category,
            test_name="test_example",
        )

        report = CloudAnalysisReport(
            run_id=run_id,
            verdicts=[verdict],
            timestamp="2026-07-30T14:00:00Z",
        )

        with tempfile.TemporaryDirectory() as td:
            artifacts_dir = Path(td) / run_id
            artifacts_dir.mkdir(parents=True)

            output_path = store_analysis_report(report, artifacts_dir)

            assert output_path.name == "cloud_analysis.json"
            assert output_path.exists()

            # Verify structure
            data = json.loads(output_path.read_text())
            assert data["run_id"] == run_id
            assert len(data["verdicts"]) == 1
            assert data["verdicts"][0]["category"] == category


# ---------------------------------------------------------------------------
# Property 21: Proposed Test Format Validity
# **Validates: Requirements 25.3**
# ---------------------------------------------------------------------------


class TestProposedTestFormatValidity:
    """Property 21: Proposed Test Format Validity.

    *For any* test case proposed by the coverage discovery cloud model,
    the output SHALL be a syntactically valid pytest file with a
    @pytest.mark.proposed marker, stored in tests/e2e/proposed/.
    """

    @given(
        test_name=test_name_st,
        layer=layer_st,
        description=st.text(min_size=5, max_size=80, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"),
            whitelist_characters=" ._-"
        )),
    )
    @settings(max_examples=50)
    def test_generated_stub_is_syntactically_valid(
        self, test_name: str, layer: str, description: str
    ):
        """Generated test stubs are syntactically valid Python.

        **Validates: Requirements 25.3**
        """
        from tests.e2e.improvement.coverage_discoverer import generate_test_stub

        stub_code = generate_test_stub(test_name, description, layer)

        # Must be valid Python
        try:
            compile(stub_code, "<test>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated stub is not valid Python: {e}")

    @given(test_name=test_name_st, layer=layer_st)
    @settings(max_examples=50)
    def test_generated_stub_has_proposed_marker(self, test_name: str, layer: str):
        """Generated test stubs contain @pytest.mark.proposed marker.

        **Validates: Requirements 25.3**
        """
        from tests.e2e.improvement.coverage_discoverer import generate_test_stub

        stub_code = generate_test_stub(test_name, "Test description", layer)
        assert "@pytest.mark.proposed" in stub_code

    @given(test_name=test_name_st, layer=layer_st)
    @settings(max_examples=30)
    def test_generated_stub_contains_test_function(self, test_name: str, layer: str):
        """Generated test stubs contain at least one test function.

        **Validates: Requirements 25.3**
        """
        from tests.e2e.improvement.coverage_discoverer import generate_test_stub

        stub_code = generate_test_stub(test_name, "Test description", layer)
        assert re.search(r"def test_\w+\s*\(", stub_code)

    @given(test_name=test_name_st, layer=layer_st)
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_validate_proposed_format_accepts_valid_files(
        self, test_name: str, layer: str, tmp_path: Path
    ):
        """validate_proposed_test_format() accepts correctly formatted files.

        **Validates: Requirements 25.3**
        """
        from tests.e2e.improvement.coverage_discoverer import (
            generate_test_stub,
            validate_proposed_test_format,
        )

        with tempfile.TemporaryDirectory() as td:
            stub_code = generate_test_stub(test_name, "Description", layer)
            file_path = Path(td) / f"test_proposed_{test_name}.py"
            file_path.write_text(stub_code, encoding="utf-8")

            assert validate_proposed_test_format(file_path) is True

    def test_validate_proposed_format_rejects_missing_marker(self, tmp_path: Path):
        """Files without @pytest.mark.proposed are rejected."""
        from tests.e2e.improvement.coverage_discoverer import validate_proposed_test_format

        file_path = tmp_path / "test_no_marker.py"
        file_path.write_text(
            "import pytest\n\ndef test_something():\n    pass\n",
            encoding="utf-8",
        )

        assert validate_proposed_test_format(file_path) is False

    def test_validate_proposed_format_rejects_syntax_error(self, tmp_path: Path):
        """Files with syntax errors are rejected."""
        from tests.e2e.improvement.coverage_discoverer import validate_proposed_test_format

        file_path = tmp_path / "test_bad_syntax.py"
        file_path.write_text(
            "@pytest.mark.proposed\ndef test_bad(:\n    pass\n",
            encoding="utf-8",
        )

        assert validate_proposed_test_format(file_path) is False


# ---------------------------------------------------------------------------
# Property 22: Threshold Recommendation Structure
# **Validates: Requirements 26.3**
# ---------------------------------------------------------------------------


class TestThresholdRecommendationStructure:
    """Property 22: Threshold Recommendation Structure.

    *For any* calibration recommendation output, the JSON SHALL contain
    per-metric threshold values with justification text explaining the
    statistical basis (mean, std, percentiles) for the recommendation.
    """

    @given(
        metric_name=metric_name_st,
        mean=st.floats(min_value=0.01, max_value=0.99, allow_nan=False),
        std=st.floats(min_value=0.001, max_value=0.2, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_recommendation_contains_metric_and_threshold(
        self, metric_name: str, mean: float, std: float
    ):
        """Recommendations contain metric_name and recommended_threshold.

        **Validates: Requirements 26.3**
        """
        from tests.e2e.improvement.threshold_calibrator import (
            MetricDistribution,
            ThresholdRecommendation,
        )

        dist = MetricDistribution(
            metric_name=metric_name,
            mean=mean,
            std=std,
            min_value=mean - 3 * std,
            max_value=mean + 3 * std,
            p5=mean - 2 * std,
            p25=mean - std,
            p50=mean,
            p75=mean + std,
            p95=mean + 2 * std,
            sample_count=50,
        )

        rec = ThresholdRecommendation(
            metric_name=metric_name,
            current_threshold=mean - std,
            recommended_threshold=mean - 2 * std,
            justification=f"Based on mean={mean:.4f}, std={std:.4f}. Using mean - 2*std as threshold.",
            distribution=dist,
        )

        d = rec.to_dict()
        assert "metric_name" in d
        assert "recommended_threshold" in d
        assert d["metric_name"] == metric_name
        assert isinstance(d["recommended_threshold"], float)

    @given(
        metric_name=metric_name_st,
        mean=st.floats(min_value=0.1, max_value=0.95, allow_nan=False),
        std=st.floats(min_value=0.005, max_value=0.1, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_recommendation_justification_mentions_statistics(
        self, metric_name: str, mean: float, std: float
    ):
        """Justification text explains the statistical basis.

        **Validates: Requirements 26.3**
        """
        from tests.e2e.improvement.threshold_calibrator import (
            MetricDistribution,
            ThresholdRecommendation,
        )

        dist = MetricDistribution(
            metric_name=metric_name,
            mean=mean,
            std=std,
            min_value=mean - 3 * std,
            max_value=mean + 3 * std,
            p5=mean - 2 * std,
            p25=mean - std,
            p50=mean,
            p75=mean + std,
            p95=mean + 2 * std,
            sample_count=50,
        )

        justification = (
            f"Statistical basis: mean={mean:.4f}, std={std:.4f}. "
            f"Recommended threshold uses mean - 2*std = {mean - 2 * std:.4f}"
        )

        rec = ThresholdRecommendation(
            metric_name=metric_name,
            current_threshold=mean - std,
            recommended_threshold=mean - 2 * std,
            justification=justification,
            distribution=dist,
        )

        d = rec.to_dict()
        # Justification must mention statistical basis
        just_lower = d["justification"].lower()
        assert any(
            term in just_lower
            for term in ("mean", "std", "percentile", "standard deviation")
        ), f"Justification missing statistical terms: {d['justification']}"

    @given(
        metric_name=metric_name_st,
        mean=st.floats(min_value=0.1, max_value=0.95, allow_nan=False),
        std=st.floats(min_value=0.005, max_value=0.1, allow_nan=False),
    )
    @settings(max_examples=30)
    def test_validate_recommendation_structure_function(
        self, metric_name: str, mean: float, std: float
    ):
        """validate_recommendation_structure() accepts well-formed data.

        **Validates: Requirements 26.3**
        """
        from tests.e2e.improvement.threshold_calibrator import (
            validate_recommendation_structure,
        )

        data = {
            "recommendations": [
                {
                    "metric_name": metric_name,
                    "recommended_threshold": mean - 2 * std,
                    "justification": f"Based on mean={mean:.4f} and std={std:.4f}. Threshold set at mean - 2*std.",
                }
            ]
        }

        assert validate_recommendation_structure(data) is True

    def test_validate_rejects_missing_recommendations_key(self):
        """Rejects data without recommendations key."""
        from tests.e2e.improvement.threshold_calibrator import (
            validate_recommendation_structure,
        )

        assert validate_recommendation_structure({}) is False
        assert validate_recommendation_structure({"other": []}) is False

    def test_validate_rejects_empty_justification(self):
        """Rejects recommendations with empty justification."""
        from tests.e2e.improvement.threshold_calibrator import (
            validate_recommendation_structure,
        )

        data = {
            "recommendations": [
                {
                    "metric_name": "ssim",
                    "recommended_threshold": 0.85,
                    "justification": "",
                }
            ]
        }
        assert validate_recommendation_structure(data) is False

    def test_validate_rejects_justification_without_stats(self):
        """Rejects justification that doesn't mention statistical basis."""
        from tests.e2e.improvement.threshold_calibrator import (
            validate_recommendation_structure,
        )

        data = {
            "recommendations": [
                {
                    "metric_name": "ssim",
                    "recommended_threshold": 0.85,
                    "justification": "This threshold seems about right.",
                }
            ]
        }
        assert validate_recommendation_structure(data) is False

    @given(
        metric_names=st.lists(metric_name_st, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_full_report_serialization_roundtrip(
        self, metric_names: list[str], tmp_path: Path
    ):
        """ThresholdRecommendationReport serializes to valid JSON with all fields.

        **Validates: Requirements 26.3**
        """
        from tests.e2e.improvement.threshold_calibrator import (
            MetricDistribution,
            ThresholdRecommendation,
            ThresholdRecommendationReport,
            store_recommendations,
        )

        recommendations = []
        for name in metric_names:
            dist = MetricDistribution(
                metric_name=name,
                mean=0.9,
                std=0.02,
                min_value=0.85,
                max_value=0.95,
                p5=0.86,
                p25=0.88,
                p50=0.90,
                p75=0.92,
                p95=0.94,
                sample_count=50,
            )
            recommendations.append(
                ThresholdRecommendation(
                    metric_name=name,
                    current_threshold=0.85,
                    recommended_threshold=0.86,
                    justification=f"Based on mean=0.9, std=0.02 for {name}.",
                    distribution=dist,
                )
            )

        report = ThresholdRecommendationReport(
            recommendations=recommendations,
            timestamp="2026-07-30T14:00:00Z",
            runs_analyzed=50,
        )

        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "recommendations.json"
            store_recommendations(report, output)

            # Verify file exists and has valid JSON
            assert output.exists()
            data = json.loads(output.read_text())
            assert len(data["recommendations"]) == len(metric_names)
            assert data["runs_analyzed"] == 50

            # Each recommendation has the required fields
            for rec in data["recommendations"]:
                assert "metric_name" in rec
                assert "recommended_threshold" in rec
                assert "justification" in rec
                assert rec["justification"]  # Non-empty
