"""Configuration loader for the E2E World Test Kit.

Reads tests/e2e/config/world_test_kit.yaml and supports environment variable
overrides for all key settings (WTK_PLAYTESTER_MODEL, WTK_VISION_MODEL, etc.).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageTimeout:
    """Per-stage timeout settings in seconds."""

    conversation_s: float = 60.0
    pipeline_wait_s: float = 0.0  # 0 = no hard timeout, use stall detection
    stall_timeout_s: float = 900.0  # fail only if no progress for 15 min (GPU stages can take 5+ min)
    navigation_s: float = 30.0
    interaction_s: float = 60.0
    vision_eval_s: float = 120.0
    report_s: float = 10.0


@dataclass(frozen=True)
class ScoringWeights:
    """Weights for the 9 evaluation criteria (must sum to ~1.0)."""

    conversation_quality: float = 0.15
    brief_coherence: float = 0.10
    pipeline_success: float = 0.15
    navigation_responsiveness: float = 0.10
    interaction_correctness: float = 0.10
    visual_quality: float = 0.15
    scene_completeness: float = 0.10
    performance: float = 0.05
    overall_experience: float = 0.10


@dataclass(frozen=True)
class LayerFlags:
    """Enable/disable individual test layers."""

    conversation: bool = True
    pipeline_wait: bool = True
    navigation: bool = True
    interactions: bool = True
    vision_eval: bool = True
    scene_validation: bool = True
    performance: bool = True
    accessibility: bool = True
    experience_judge: bool = True


@dataclass(frozen=True)
class WorldTestKitConfig:
    """Top-level configuration for the World Test Kit."""

    playtester_model: str = "qwen3-coder-next"
    vision_model: str = "qwen2.5vl:7b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    server_url: str = "http://localhost:8000"
    pass_threshold: float = 60.0
    individual_minimum: float = 30.0
    max_conversation_turns: int = 5
    timeouts: StageTimeout = field(default_factory=StageTimeout)
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    layers: LayerFlags = field(default_factory=LayerFlags)
    headless: bool = True
    screenshot_on_failure: bool = True
    artifacts_dir: str = "tests/e2e/artifacts/playtest"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WTKConfigError(Exception):
    """Raised when the World Test Kit config cannot be loaded or is invalid."""
    pass


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _env_override(key: str, default: Any, cast_type: type = str) -> Any:
    """Check for an environment variable override, cast to type if present."""
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        if cast_type is bool:
            return val.lower() in ("1", "true", "yes", "on")
        return cast_type(val)
    except (ValueError, TypeError):
        return default


def _parse_timeouts(raw: dict[str, Any] | None) -> StageTimeout:
    """Parse timeout section from YAML."""
    if not raw:
        return StageTimeout()
    return StageTimeout(
        conversation_s=float(raw.get("conversation_s", 60.0)),
        pipeline_wait_s=float(raw.get("pipeline_wait_s", 0.0)),
        stall_timeout_s=float(raw.get("stall_timeout_s", 900.0)),
        navigation_s=float(raw.get("navigation_s", 30.0)),
        interaction_s=float(raw.get("interaction_s", 60.0)),
        vision_eval_s=float(raw.get("vision_eval_s", 120.0)),
        report_s=float(raw.get("report_s", 10.0)),
    )


def _parse_weights(raw: dict[str, Any] | None) -> ScoringWeights:
    """Parse scoring weights section from YAML."""
    if not raw:
        return ScoringWeights()
    return ScoringWeights(
        conversation_quality=float(raw.get("conversation_quality", 0.15)),
        brief_coherence=float(raw.get("brief_coherence", 0.10)),
        pipeline_success=float(raw.get("pipeline_success", 0.15)),
        navigation_responsiveness=float(raw.get("navigation_responsiveness", 0.10)),
        interaction_correctness=float(raw.get("interaction_correctness", 0.10)),
        visual_quality=float(raw.get("visual_quality", 0.15)),
        scene_completeness=float(raw.get("scene_completeness", 0.10)),
        performance=float(raw.get("performance", 0.05)),
        overall_experience=float(raw.get("overall_experience", 0.10)),
    )


def _parse_layers(raw: dict[str, Any] | None) -> LayerFlags:
    """Parse layer enable/disable flags from YAML."""
    if not raw:
        return LayerFlags()
    return LayerFlags(
        conversation=bool(raw.get("conversation", True)),
        pipeline_wait=bool(raw.get("pipeline_wait", True)),
        navigation=bool(raw.get("navigation", True)),
        interactions=bool(raw.get("interactions", True)),
        vision_eval=bool(raw.get("vision_eval", True)),
        scene_validation=bool(raw.get("scene_validation", True)),
        performance=bool(raw.get("performance", True)),
        accessibility=bool(raw.get("accessibility", True)),
        experience_judge=bool(raw.get("experience_judge", True)),
    )


def load_wtk_config(config_path: str | Path | None = None) -> WorldTestKitConfig:
    """Load and validate the World Test Kit configuration.

    Args:
        config_path: Path to world_test_kit.yaml. Defaults to
                     tests/e2e/config/world_test_kit.yaml.

    Returns:
        A WorldTestKitConfig with env var overrides applied.

    Raises:
        WTKConfigError: If the file is unreadable or invalid.
    """
    if config_path is None:
        config_path = (
            Path(__file__).resolve().parent.parent / "config" / "world_test_kit.yaml"
        )
    else:
        config_path = Path(config_path)

    raw: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise WTKConfigError(f"Failed to parse {config_path}: {e}")
    # If file doesn't exist, use all defaults — that's fine

    if not isinstance(raw, dict):
        raise WTKConfigError(
            f"Config must be a YAML mapping, got {type(raw).__name__}"
        )

    # Build config with env var overrides taking precedence
    playtester_model = _env_override(
        "WTK_PLAYTESTER_MODEL",
        raw.get("playtester_model", "qwen3-coder-next"),
    )
    vision_model = _env_override(
        "WTK_VISION_MODEL",
        raw.get("vision_model", "qwen2.5vl:7b"),
    )
    ollama_base_url = _env_override(
        "WTK_OLLAMA_URL",
        raw.get("ollama_base_url", "http://127.0.0.1:11434"),
    )
    server_url = _env_override(
        "WTK_SERVER_URL",
        raw.get("server_url", "http://localhost:8000"),
    )
    pass_threshold = _env_override(
        "WTK_PASS_THRESHOLD",
        raw.get("pass_threshold", 60.0),
        float,
    )
    individual_minimum = _env_override(
        "WTK_INDIVIDUAL_MINIMUM",
        raw.get("individual_minimum", 30.0),
        float,
    )
    max_turns = _env_override(
        "WTK_MAX_TURNS",
        raw.get("max_conversation_turns", 5),
        int,
    )
    headless = _env_override(
        "WTK_HEADLESS",
        raw.get("headless", True),
        bool,
    )

    return WorldTestKitConfig(
        playtester_model=playtester_model,
        vision_model=vision_model,
        ollama_base_url=ollama_base_url,
        server_url=server_url,
        pass_threshold=pass_threshold,
        individual_minimum=individual_minimum,
        max_conversation_turns=max_turns,
        timeouts=_parse_timeouts(raw.get("timeouts")),
        weights=_parse_weights(raw.get("weights")),
        layers=_parse_layers(raw.get("layers")),
        headless=headless,
        screenshot_on_failure=raw.get("screenshot_on_failure", True),
        artifacts_dir=raw.get("artifacts_dir", "tests/e2e/artifacts/playtest"),
    )
