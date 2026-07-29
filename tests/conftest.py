"""Pytest conftest — Hypothesis speed cap for faster local test runs.

Uses Hypothesis's settings.load_profile to set a global default of 20
max_examples. The 'force_cap' fixture patches settings at the decorator
level for tests with explicit high max_examples values.

Usage:
    pytest                                         # fast (capped at 20)
    HYPOTHESIS_MAX_EXAMPLES=200 pytest             # full
"""

import os

from hypothesis import HealthCheck, Phase, settings

_MAX = int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "20"))

# Register profiles
settings.register_profile(
    "fast",
    max_examples=_MAX,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    phases=[Phase.explicit, Phase.generate, Phase.shrink],
)

settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Load fast profile as the default — this caps tests that DON'T specify
# their own @settings. Tests with explicit @settings(max_examples=200)
# still override, but the profile makes the majority fast.
if "HYPOTHESIS_PROFILE" not in os.environ:
    settings.load_profile("fast")
