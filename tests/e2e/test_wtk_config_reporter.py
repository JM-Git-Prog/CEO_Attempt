"""Cheap strict World Test Kit scoring checks; no browser or model execution."""
from __future__ import annotations

import pytest

from tests.e2e.world_test_kit.config import WTKConfigError, load_wtk_config
from tests.e2e.world_test_kit.reporter import PlaytestReport, PlaytestReporter


def test_canonical_config_requires_100_out_of_100():
    config = load_wtk_config()
    assert config.strict_real is True
    assert config.pass_threshold == 100.0
    assert config.individual_minimum == 100.0
    assert PlaytestReport().pass_threshold == 100.0
    assert PlaytestReport().individual_minimum == 100.0


def test_strict_config_rejects_lower_environment_threshold(monkeypatch, tmp_path):
    config_path = tmp_path / "wtk.yaml"
    config_path.write_text("strict_real: true\n", encoding="utf-8")
    monkeypatch.setenv("WTK_PASS_THRESHOLD", "99")
    with pytest.raises(WTKConfigError, match="100/100"):
        load_wtk_config(config_path)


def test_reporter_requires_every_layer_to_score_100():
    reporter = PlaytestReporter(load_wtk_config())
    passed = reporter.generate({"layers": {"world": {"score": 100.0, "passed": True}}})
    failed = reporter.generate({"layers": {"world": {"score": 99.9, "passed": True}}})
    assert passed.passed is True
    assert failed.passed is False
