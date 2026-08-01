"""Configuration loader for the E2E testing framework.

Parses tests/e2e/config/e2e_config.yaml into typed Python dataclasses.
Supports per-stage threshold configuration and validates required fields.

Validates: Requirements 3.4, 6.1, 22.1–22.6
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageConfig:
    """Configuration for a single pipeline stage's visual regression settings."""

    diff_threshold_pct: float
    enabled: bool = True


@dataclass(frozen=True)
class VisualRegressionConfig:
    """Per-stage thresholds and capture settings for visual regression."""

    deterministic_seed: int
    default_viewport: tuple[int, int]
    stages: dict[str, StageConfig]


@dataclass(frozen=True)
class PerceptualConfig:
    """Composite gate thresholds for perceptual fidelity."""

    ssim_threshold: float
    lpips_threshold: float
    clip_cosine_threshold: float
    calibration_corpus_dir: str


@dataclass(frozen=True)
class VisionQAConfig:
    """Vision model oracle settings."""

    model_name: str
    confidence_threshold: float
    checklist_path: str
    blocking: bool


@dataclass(frozen=True)
class TimeBudgetConfig:
    """Execution time limits per test layer (in seconds)."""

    visual_regression_s: int
    scene_validation_s: int
    accessibility_s: int
    perceptual_s: int


@dataclass(frozen=True)
class CloudConfig:
    """Self-improving loop cloud model settings."""

    failure_analysis_model: str
    coverage_model: str
    calibration_model: str
    calibration_trigger_runs: int
    evolution_trigger_verdicts: int


@dataclass(frozen=True)
class BaselinesConfig:
    """Baseline storage and approval settings."""

    storage_dir: str
    require_approval: bool
    max_corpus_size_mb: int


@dataclass(frozen=True)
class E2EConfig:
    """Top-level configuration container for the full E2E testing framework."""

    visual_regression: VisualRegressionConfig
    perceptual: PerceptualConfig
    vision_qa: VisionQAConfig
    time_budgets: TimeBudgetConfig
    cloud: CloudConfig
    baselines: BaselinesConfig


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ConfigLoadError(Exception):
    """Raised when the config file is missing, unreadable, or invalid."""

    pass


class ConfigValidationError(ConfigLoadError):
    """Raised when required fields are missing or have invalid values."""

    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_key(data: dict[str, Any], key: str, section: str) -> Any:
    """Retrieve a required key from a dict, raising on absence."""
    if key not in data:
        raise ConfigValidationError(
            f"Missing required field '{key}' in section '{section}'"
        )
    return data[key]


def _parse_stage_config(name: str, raw: dict[str, Any]) -> StageConfig:
    """Parse a single stage config dict."""
    diff_threshold = _require_key(raw, "diff_threshold_pct", f"stages.{name}")
    if not isinstance(diff_threshold, (int, float)):
        raise ConfigValidationError(
            f"stages.{name}.diff_threshold_pct must be a number, got {type(diff_threshold).__name__}"
        )
    if diff_threshold < 0:
        raise ConfigValidationError(
            f"stages.{name}.diff_threshold_pct must be >= 0, got {diff_threshold}"
        )
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigValidationError(
            f"stages.{name}.enabled must be a boolean, got {type(enabled).__name__}"
        )
    return StageConfig(diff_threshold_pct=float(diff_threshold), enabled=enabled)


def _parse_visual_regression(raw: dict[str, Any]) -> VisualRegressionConfig:
    """Parse the visual_regression section."""
    section = "visual_regression"
    seed = _require_key(raw, "deterministic_seed", section)
    if not isinstance(seed, int):
        raise ConfigValidationError(
            f"{section}.deterministic_seed must be an integer, got {type(seed).__name__}"
        )

    viewport_raw = _require_key(raw, "default_viewport", section)
    if not isinstance(viewport_raw, list) or len(viewport_raw) != 2:
        raise ConfigValidationError(
            f"{section}.default_viewport must be a list of [width, height]"
        )
    viewport = (int(viewport_raw[0]), int(viewport_raw[1]))

    stages_raw = _require_key(raw, "stages", section)
    if not isinstance(stages_raw, dict):
        raise ConfigValidationError(f"{section}.stages must be a mapping")

    stages: dict[str, StageConfig] = {}
    for stage_name, stage_data in stages_raw.items():
        if not isinstance(stage_data, dict):
            raise ConfigValidationError(
                f"{section}.stages.{stage_name} must be a mapping"
            )
        stages[stage_name] = _parse_stage_config(stage_name, stage_data)

    return VisualRegressionConfig(
        deterministic_seed=seed,
        default_viewport=viewport,
        stages=stages,
    )


def _parse_perceptual(raw: dict[str, Any]) -> PerceptualConfig:
    """Parse the perceptual section."""
    section = "perceptual"
    ssim = _require_key(raw, "ssim_threshold", section)
    lpips = _require_key(raw, "lpips_threshold", section)
    clip = _require_key(raw, "clip_cosine_threshold", section)
    corpus_dir = _require_key(raw, "calibration_corpus_dir", section)

    for name, val in [("ssim_threshold", ssim), ("lpips_threshold", lpips), ("clip_cosine_threshold", clip)]:
        if not isinstance(val, (int, float)):
            raise ConfigValidationError(
                f"{section}.{name} must be a number, got {type(val).__name__}"
            )

    if not isinstance(corpus_dir, str):
        raise ConfigValidationError(
            f"{section}.calibration_corpus_dir must be a string"
        )

    return PerceptualConfig(
        ssim_threshold=float(ssim),
        lpips_threshold=float(lpips),
        clip_cosine_threshold=float(clip),
        calibration_corpus_dir=corpus_dir,
    )


def _parse_vision_qa(raw: dict[str, Any]) -> VisionQAConfig:
    """Parse the vision_qa section."""
    section = "vision_qa"
    model_name = _require_key(raw, "model_name", section)
    confidence = _require_key(raw, "confidence_threshold", section)
    checklist_path = _require_key(raw, "checklist_path", section)
    blocking = _require_key(raw, "blocking", section)

    if not isinstance(model_name, str):
        raise ConfigValidationError(f"{section}.model_name must be a string")
    if not isinstance(confidence, (int, float)):
        raise ConfigValidationError(
            f"{section}.confidence_threshold must be a number"
        )
    if not isinstance(checklist_path, str):
        raise ConfigValidationError(f"{section}.checklist_path must be a string")
    if not isinstance(blocking, bool):
        raise ConfigValidationError(f"{section}.blocking must be a boolean")

    return VisionQAConfig(
        model_name=model_name,
        confidence_threshold=float(confidence),
        checklist_path=checklist_path,
        blocking=blocking,
    )


def _parse_time_budgets(raw: dict[str, Any]) -> TimeBudgetConfig:
    """Parse the time_budgets section."""
    section = "time_budgets"
    fields = [
        "visual_regression_s",
        "scene_validation_s",
        "accessibility_s",
        "perceptual_s",
    ]
    values: dict[str, int] = {}
    for f in fields:
        val = _require_key(raw, f, section)
        if not isinstance(val, int):
            raise ConfigValidationError(
                f"{section}.{f} must be an integer, got {type(val).__name__}"
            )
        if val <= 0:
            raise ConfigValidationError(f"{section}.{f} must be > 0, got {val}")
        values[f] = val

    return TimeBudgetConfig(**values)


def _parse_cloud(raw: dict[str, Any]) -> CloudConfig:
    """Parse the cloud section."""
    section = "cloud"
    failure_model = _require_key(raw, "failure_analysis_model", section)
    coverage_model = _require_key(raw, "coverage_model", section)
    calibration_model = _require_key(raw, "calibration_model", section)
    trigger_runs = _require_key(raw, "calibration_trigger_runs", section)
    trigger_verdicts = _require_key(raw, "evolution_trigger_verdicts", section)

    for name, val in [("failure_analysis_model", failure_model), ("coverage_model", coverage_model), ("calibration_model", calibration_model)]:
        if not isinstance(val, str):
            raise ConfigValidationError(f"{section}.{name} must be a string")

    for name, val in [("calibration_trigger_runs", trigger_runs), ("evolution_trigger_verdicts", trigger_verdicts)]:
        if not isinstance(val, int):
            raise ConfigValidationError(
                f"{section}.{name} must be an integer, got {type(val).__name__}"
            )
        if val <= 0:
            raise ConfigValidationError(f"{section}.{name} must be > 0, got {val}")

    return CloudConfig(
        failure_analysis_model=failure_model,
        coverage_model=coverage_model,
        calibration_model=calibration_model,
        calibration_trigger_runs=trigger_runs,
        evolution_trigger_verdicts=trigger_verdicts,
    )


def _parse_baselines(raw: dict[str, Any]) -> BaselinesConfig:
    """Parse the baselines section."""
    section = "baselines"
    storage_dir = _require_key(raw, "storage_dir", section)
    require_approval = _require_key(raw, "require_approval", section)
    max_size = _require_key(raw, "max_corpus_size_mb", section)

    if not isinstance(storage_dir, str):
        raise ConfigValidationError(f"{section}.storage_dir must be a string")
    if not isinstance(require_approval, bool):
        raise ConfigValidationError(f"{section}.require_approval must be a boolean")
    if not isinstance(max_size, int):
        raise ConfigValidationError(
            f"{section}.max_corpus_size_mb must be an integer"
        )
    if max_size <= 0:
        raise ConfigValidationError(
            f"{section}.max_corpus_size_mb must be > 0, got {max_size}"
        )

    return BaselinesConfig(
        storage_dir=storage_dir,
        require_approval=require_approval,
        max_corpus_size_mb=max_size,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(config_path: str | Path | None = None) -> E2EConfig:
    """Load and validate the E2E testing configuration from a YAML file.

    Args:
        config_path: Path to the YAML config file. If None, uses the default
                     location at ``tests/e2e/config/e2e_config.yaml`` relative
                     to the project root.

    Returns:
        A fully validated E2EConfig instance.

    Raises:
        ConfigLoadError: If the file cannot be read or parsed.
        ConfigValidationError: If required fields are missing or invalid.
    """
    if config_path is None:
        # Resolve relative to project root (3 levels up from this file)
        config_path = (
            Path(__file__).resolve().parent.parent / "config" / "e2e_config.yaml"
        )
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise ConfigLoadError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"Failed to parse YAML config at {config_path}: {e}")

    if not isinstance(raw, dict):
        raise ConfigLoadError(
            f"Config file must contain a YAML mapping at top level, got {type(raw).__name__}"
        )

    # Parse each top-level section
    vr_raw = _require_key(raw, "visual_regression", "root")
    perceptual_raw = _require_key(raw, "perceptual", "root")
    vision_qa_raw = _require_key(raw, "vision_qa", "root")
    time_budgets_raw = _require_key(raw, "time_budgets", "root")
    cloud_raw = _require_key(raw, "cloud", "root")
    baselines_raw = _require_key(raw, "baselines", "root")

    return E2EConfig(
        visual_regression=_parse_visual_regression(vr_raw),
        perceptual=_parse_perceptual(perceptual_raw),
        vision_qa=_parse_vision_qa(vision_qa_raw),
        time_budgets=_parse_time_budgets(time_budgets_raw),
        cloud=_parse_cloud(cloud_raw),
        baselines=_parse_baselines(baselines_raw),
    )
