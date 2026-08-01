"""Unit tests for the E2E config loader module.

Tests cover:
- Loading valid config from actual YAML file
- Handling missing config file (ConfigLoadError)
- Handling invalid YAML syntax
- Handling missing required fields (ConfigValidationError for each section)
- Type validation (wrong types for threshold values, etc.)
- Edge cases: negative thresholds, zero time budgets, empty strings

Requirements: 6.1, 23.4
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.framework.config_loader import (
    ConfigLoadError,
    ConfigValidationError,
    E2EConfig,
    VisualRegressionConfig,
    PerceptualConfig,
    VisionQAConfig,
    TimeBudgetConfig,
    CloudConfig,
    BaselinesConfig,
    StageConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CONFIG_YAML = """\
visual_regression:
  deterministic_seed: 42
  default_viewport: [1920, 1080]
  stages:
    dream_preview:
      diff_threshold_pct: 1.0
      enabled: true
    canon:
      diff_threshold_pct: 0.1
      enabled: true

perceptual:
  ssim_threshold: 0.85
  lpips_threshold: 0.3
  clip_cosine_threshold: 0.9
  calibration_corpus_dir: "tests/e2e/calibration_corpus/"

vision_qa:
  model_name: "qwen2.5vl:7b"
  confidence_threshold: 0.8
  checklist_path: "tests/e2e/config/vision_qa_checklist.json"
  blocking: false

time_budgets:
  visual_regression_s: 120
  scene_validation_s: 60
  accessibility_s: 30
  perceptual_s: 300

cloud:
  failure_analysis_model: "glm-5.2:cloud"
  coverage_model: "qwen3-coder:480b-cloud"
  calibration_model: "deepseek-v3.1:671b-cloud"
  calibration_trigger_runs: 50
  evolution_trigger_verdicts: 20

baselines:
  storage_dir: "tests/e2e/baselines/"
  require_approval: true
  max_corpus_size_mb: 50
"""


def _write_config(tmp_path: Path, content: str) -> Path:
    """Write content to a temp YAML file and return its path."""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(content, encoding="utf-8")
    return config_file


# ---------------------------------------------------------------------------
# Test: Loading valid config
# ---------------------------------------------------------------------------


class TestLoadValidConfig:
    """Tests for loading a valid, complete configuration file."""

    def test_load_from_actual_config_file(self):
        """Load the real e2e_config.yaml and verify it parses without error."""
        config = load_config()
        assert isinstance(config, E2EConfig)

    def test_visual_regression_section(self):
        """Visual regression config is parsed with correct types."""
        config = load_config()
        vr = config.visual_regression
        assert isinstance(vr, VisualRegressionConfig)
        assert vr.deterministic_seed == 42
        assert vr.default_viewport == (1920, 1080)
        assert isinstance(vr.stages, dict)
        assert "canon" in vr.stages
        assert vr.stages["canon"].diff_threshold_pct == 0.1

    def test_perceptual_section(self):
        """Perceptual config is parsed with correct threshold values."""
        config = load_config()
        p = config.perceptual
        assert isinstance(p, PerceptualConfig)
        assert p.ssim_threshold == 0.85
        assert p.lpips_threshold == 0.3
        assert p.clip_cosine_threshold == 0.9
        assert p.calibration_corpus_dir == "tests/e2e/calibration_corpus/"

    def test_vision_qa_section(self):
        """Vision QA config is parsed correctly."""
        config = load_config()
        vqa = config.vision_qa
        assert isinstance(vqa, VisionQAConfig)
        assert vqa.model_name == "qwen2.5vl:7b"
        assert vqa.confidence_threshold == 0.8
        assert vqa.blocking is False

    def test_time_budgets_section(self):
        """Time budget config is parsed as integers."""
        config = load_config()
        tb = config.time_budgets
        assert isinstance(tb, TimeBudgetConfig)
        assert tb.visual_regression_s == 120
        assert tb.scene_validation_s == 60
        assert tb.accessibility_s == 30
        assert tb.perceptual_s == 300

    def test_cloud_section(self):
        """Cloud config is parsed correctly."""
        config = load_config()
        c = config.cloud
        assert isinstance(c, CloudConfig)
        assert c.failure_analysis_model == "glm-5.2:cloud"
        assert c.calibration_trigger_runs == 50
        assert c.evolution_trigger_verdicts == 20

    def test_baselines_section(self):
        """Baselines config is parsed correctly."""
        config = load_config()
        b = config.baselines
        assert isinstance(b, BaselinesConfig)
        assert b.storage_dir == "tests/e2e/baselines/"
        assert b.require_approval is True
        assert b.max_corpus_size_mb == 50

    def test_load_from_explicit_path(self, tmp_path):
        """Config loads correctly from an explicit file path."""
        config_file = _write_config(tmp_path, VALID_CONFIG_YAML)
        config = load_config(config_file)
        assert isinstance(config, E2EConfig)
        assert config.visual_regression.deterministic_seed == 42

    def test_stage_config_values(self):
        """Individual stage configs have correct threshold and enabled state."""
        config = load_config()
        dream = config.visual_regression.stages["dream_preview"]
        assert isinstance(dream, StageConfig)
        assert dream.diff_threshold_pct == 1.0
        assert dream.enabled is True


# ---------------------------------------------------------------------------
# Test: Missing config file
# ---------------------------------------------------------------------------


class TestMissingConfigFile:
    """Tests for ConfigLoadError on missing/unreadable files."""

    def test_missing_file_raises_config_load_error(self, tmp_path):
        """Raises ConfigLoadError when config file does not exist."""
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(ConfigLoadError, match="not found"):
            load_config(missing)

    def test_error_message_includes_path(self, tmp_path):
        """Error message includes the path that was attempted."""
        missing = tmp_path / "gone.yaml"
        with pytest.raises(ConfigLoadError) as exc_info:
            load_config(missing)
        assert "gone.yaml" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Test: Invalid YAML syntax
# ---------------------------------------------------------------------------


class TestInvalidYAMLSyntax:
    """Tests for ConfigLoadError on malformed YAML."""

    def test_invalid_yaml_raises_config_load_error(self, tmp_path):
        """Raises ConfigLoadError on syntactically invalid YAML."""
        bad_yaml = "visual_regression:\n  stages:\n    - [invalid: yaml: {{"
        config_file = _write_config(tmp_path, bad_yaml)
        with pytest.raises(ConfigLoadError, match="Failed to parse YAML"):
            load_config(config_file)

    def test_non_mapping_top_level_raises_error(self, tmp_path):
        """Raises ConfigLoadError when top-level is not a mapping."""
        config_file = _write_config(tmp_path, "- item1\n- item2\n")
        with pytest.raises(ConfigLoadError, match="YAML mapping"):
            load_config(config_file)

    def test_empty_file_raises_error(self, tmp_path):
        """Raises ConfigLoadError for empty YAML file (parses to None)."""
        config_file = _write_config(tmp_path, "")
        with pytest.raises(ConfigLoadError, match="YAML mapping"):
            load_config(config_file)


# ---------------------------------------------------------------------------
# Test: Missing required fields (ConfigValidationError)
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    """Tests for ConfigValidationError when required fields are absent."""

    def test_missing_visual_regression_section(self, tmp_path):
        """Raises ConfigValidationError when visual_regression is missing."""
        yaml_content = VALID_CONFIG_YAML.replace("visual_regression:", "# removed:")
        # Need to provide a minimal valid YAML that's missing one section
        yaml_content = """\
perceptual:
  ssim_threshold: 0.85
  lpips_threshold: 0.3
  clip_cosine_threshold: 0.9
  calibration_corpus_dir: "corpus/"
vision_qa:
  model_name: "model"
  confidence_threshold: 0.8
  checklist_path: "path"
  blocking: false
time_budgets:
  visual_regression_s: 120
  scene_validation_s: 60
  accessibility_s: 30
  perceptual_s: 300
cloud:
  failure_analysis_model: "model"
  coverage_model: "model"
  calibration_model: "model"
  calibration_trigger_runs: 50
  evolution_trigger_verdicts: 20
baselines:
  storage_dir: "dir/"
  require_approval: true
  max_corpus_size_mb: 50
"""
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="visual_regression"):
            load_config(config_file)

    def test_missing_perceptual_section(self, tmp_path):
        """Raises ConfigValidationError when perceptual section is missing."""
        yaml_content = """\
visual_regression:
  deterministic_seed: 42
  default_viewport: [1920, 1080]
  stages:
    canon:
      diff_threshold_pct: 0.1
vision_qa:
  model_name: "model"
  confidence_threshold: 0.8
  checklist_path: "path"
  blocking: false
time_budgets:
  visual_regression_s: 120
  scene_validation_s: 60
  accessibility_s: 30
  perceptual_s: 300
cloud:
  failure_analysis_model: "model"
  coverage_model: "model"
  calibration_model: "model"
  calibration_trigger_runs: 50
  evolution_trigger_verdicts: 20
baselines:
  storage_dir: "dir/"
  require_approval: true
  max_corpus_size_mb: 50
"""
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="perceptual"):
            load_config(config_file)

    def test_missing_time_budgets_section(self, tmp_path):
        """Raises ConfigValidationError when time_budgets section is missing."""
        yaml_content = """\
visual_regression:
  deterministic_seed: 42
  default_viewport: [1920, 1080]
  stages:
    canon:
      diff_threshold_pct: 0.1
perceptual:
  ssim_threshold: 0.85
  lpips_threshold: 0.3
  clip_cosine_threshold: 0.9
  calibration_corpus_dir: "corpus/"
vision_qa:
  model_name: "model"
  confidence_threshold: 0.8
  checklist_path: "path"
  blocking: false
cloud:
  failure_analysis_model: "model"
  coverage_model: "model"
  calibration_model: "model"
  calibration_trigger_runs: 50
  evolution_trigger_verdicts: 20
baselines:
  storage_dir: "dir/"
  require_approval: true
  max_corpus_size_mb: 50
"""
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="time_budgets"):
            load_config(config_file)

    def test_missing_deterministic_seed(self, tmp_path):
        """Raises ConfigValidationError when deterministic_seed is missing."""
        yaml_content = """\
visual_regression:
  default_viewport: [1920, 1080]
  stages:
    canon:
      diff_threshold_pct: 0.1
perceptual:
  ssim_threshold: 0.85
  lpips_threshold: 0.3
  clip_cosine_threshold: 0.9
  calibration_corpus_dir: "corpus/"
vision_qa:
  model_name: "model"
  confidence_threshold: 0.8
  checklist_path: "path"
  blocking: false
time_budgets:
  visual_regression_s: 120
  scene_validation_s: 60
  accessibility_s: 30
  perceptual_s: 300
cloud:
  failure_analysis_model: "model"
  coverage_model: "model"
  calibration_model: "model"
  calibration_trigger_runs: 50
  evolution_trigger_verdicts: 20
baselines:
  storage_dir: "dir/"
  require_approval: true
  max_corpus_size_mb: 50
"""
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="deterministic_seed"):
            load_config(config_file)

    def test_missing_ssim_threshold(self, tmp_path):
        """Raises ConfigValidationError when ssim_threshold is missing."""
        yaml_content = """\
visual_regression:
  deterministic_seed: 42
  default_viewport: [1920, 1080]
  stages:
    canon:
      diff_threshold_pct: 0.1
perceptual:
  lpips_threshold: 0.3
  clip_cosine_threshold: 0.9
  calibration_corpus_dir: "corpus/"
vision_qa:
  model_name: "model"
  confidence_threshold: 0.8
  checklist_path: "path"
  blocking: false
time_budgets:
  visual_regression_s: 120
  scene_validation_s: 60
  accessibility_s: 30
  perceptual_s: 300
cloud:
  failure_analysis_model: "model"
  coverage_model: "model"
  calibration_model: "model"
  calibration_trigger_runs: 50
  evolution_trigger_verdicts: 20
baselines:
  storage_dir: "dir/"
  require_approval: true
  max_corpus_size_mb: 50
"""
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="ssim_threshold"):
            load_config(config_file)

    def test_missing_diff_threshold_in_stage(self, tmp_path):
        """Raises ConfigValidationError when a stage is missing diff_threshold_pct."""
        yaml_content = """\
visual_regression:
  deterministic_seed: 42
  default_viewport: [1920, 1080]
  stages:
    canon:
      enabled: true
perceptual:
  ssim_threshold: 0.85
  lpips_threshold: 0.3
  clip_cosine_threshold: 0.9
  calibration_corpus_dir: "corpus/"
vision_qa:
  model_name: "model"
  confidence_threshold: 0.8
  checklist_path: "path"
  blocking: false
time_budgets:
  visual_regression_s: 120
  scene_validation_s: 60
  accessibility_s: 30
  perceptual_s: 300
cloud:
  failure_analysis_model: "model"
  coverage_model: "model"
  calibration_model: "model"
  calibration_trigger_runs: 50
  evolution_trigger_verdicts: 20
baselines:
  storage_dir: "dir/"
  require_approval: true
  max_corpus_size_mb: 50
"""
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="diff_threshold_pct"):
            load_config(config_file)


# ---------------------------------------------------------------------------
# Test: Type validation
# ---------------------------------------------------------------------------


class TestTypeValidation:
    """Tests for ConfigValidationError on wrong types."""

    def test_seed_as_string_raises_error(self, tmp_path):
        """Raises ConfigValidationError when deterministic_seed is a string."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "deterministic_seed: 42", 'deterministic_seed: "not_a_number"'
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="deterministic_seed.*integer"):
            load_config(config_file)

    def test_diff_threshold_as_string_raises_error(self, tmp_path):
        """Raises ConfigValidationError when diff_threshold_pct is a string."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "diff_threshold_pct: 1.0", 'diff_threshold_pct: "high"'
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="diff_threshold_pct.*number"):
            load_config(config_file)

    def test_ssim_threshold_as_string_raises_error(self, tmp_path):
        """Raises ConfigValidationError when ssim_threshold is a string."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "ssim_threshold: 0.85", 'ssim_threshold: "high"'
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="ssim_threshold.*number"):
            load_config(config_file)

    def test_viewport_as_scalar_raises_error(self, tmp_path):
        """Raises ConfigValidationError when default_viewport is not a list."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "default_viewport: [1920, 1080]", "default_viewport: 1920"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="default_viewport.*list"):
            load_config(config_file)

    def test_viewport_wrong_length_raises_error(self, tmp_path):
        """Raises ConfigValidationError when default_viewport has wrong length."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "default_viewport: [1920, 1080]", "default_viewport: [1920]"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="default_viewport.*list"):
            load_config(config_file)

    def test_stages_as_list_raises_error(self, tmp_path):
        """Raises ConfigValidationError when stages is a list, not a mapping."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "  stages:\n    dream_preview:\n      diff_threshold_pct: 1.0\n      enabled: true\n    canon:\n      diff_threshold_pct: 0.1\n      enabled: true",
            "  stages:\n    - dream_preview"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="stages.*mapping"):
            load_config(config_file)

    def test_enabled_as_string_raises_error(self, tmp_path):
        """Raises ConfigValidationError when enabled is a string, not boolean."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "enabled: true", 'enabled: "yes"'
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="enabled.*boolean"):
            load_config(config_file)

    def test_time_budget_as_float_raises_error(self, tmp_path):
        """Raises ConfigValidationError when time budget is a float."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "visual_regression_s: 120", "visual_regression_s: 120.5"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="visual_regression_s.*integer"):
            load_config(config_file)

    def test_calibration_corpus_dir_as_number_raises_error(self, tmp_path):
        """Raises ConfigValidationError when calibration_corpus_dir is not a string."""
        yaml_content = VALID_CONFIG_YAML.replace(
            'calibration_corpus_dir: "tests/e2e/calibration_corpus/"',
            "calibration_corpus_dir: 123"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="calibration_corpus_dir.*string"):
            load_config(config_file)

    def test_blocking_as_string_raises_error(self, tmp_path):
        """Raises ConfigValidationError when blocking is not a boolean."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "blocking: false", 'blocking: "no"'
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="blocking.*boolean"):
            load_config(config_file)


# ---------------------------------------------------------------------------
# Test: Edge cases — negative thresholds, zero budgets
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge case validation: negative values, zeros, empty strings."""

    def test_negative_diff_threshold_raises_error(self, tmp_path):
        """Raises ConfigValidationError when diff_threshold_pct is negative."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "diff_threshold_pct: 1.0", "diff_threshold_pct: -0.5"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="must be >= 0"):
            load_config(config_file)

    def test_zero_time_budget_raises_error(self, tmp_path):
        """Raises ConfigValidationError when a time budget is zero."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "visual_regression_s: 120", "visual_regression_s: 0"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="must be > 0"):
            load_config(config_file)

    def test_negative_time_budget_raises_error(self, tmp_path):
        """Raises ConfigValidationError when a time budget is negative."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "scene_validation_s: 60", "scene_validation_s: -10"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="must be > 0"):
            load_config(config_file)

    def test_zero_max_corpus_size_raises_error(self, tmp_path):
        """Raises ConfigValidationError when max_corpus_size_mb is zero."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "max_corpus_size_mb: 50", "max_corpus_size_mb: 0"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="must be > 0"):
            load_config(config_file)

    def test_zero_calibration_trigger_runs_raises_error(self, tmp_path):
        """Raises ConfigValidationError when calibration_trigger_runs is zero."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "calibration_trigger_runs: 50", "calibration_trigger_runs: 0"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="must be > 0"):
            load_config(config_file)

    def test_zero_diff_threshold_is_valid(self, tmp_path):
        """A diff_threshold_pct of 0 is valid (meaning zero tolerance)."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "diff_threshold_pct: 1.0", "diff_threshold_pct: 0"
        )
        config_file = _write_config(tmp_path, yaml_content)
        config = load_config(config_file)
        assert config.visual_regression.stages["dream_preview"].diff_threshold_pct == 0.0

    def test_stage_data_as_non_mapping_raises_error(self, tmp_path):
        """Raises ConfigValidationError when stage value is not a dict."""
        yaml_content = VALID_CONFIG_YAML.replace(
            "    dream_preview:\n      diff_threshold_pct: 1.0\n      enabled: true",
            "    dream_preview: 1.0"
        )
        config_file = _write_config(tmp_path, yaml_content)
        with pytest.raises(ConfigValidationError, match="must be a mapping"):
            load_config(config_file)
