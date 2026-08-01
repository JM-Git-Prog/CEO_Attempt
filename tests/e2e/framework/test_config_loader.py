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
