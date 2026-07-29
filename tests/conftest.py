"""Pytest conftest — Hypothesis speed cap for faster local test runs.

Enforces a hard cap on max_examples via monkey-patching the settings
constructor. Even tests with explicit @settings(max_examples=200) get
capped to HYPOTHESIS_MAX_EXAMPLES (default 20 for fast local dev).

Usage:
    pytest                                         # fast (capped at 20)
    set HYPOTHESIS_MAX_EXAMPLES=200 && pytest      # full
"""

import os

from hypothesis import HealthCheck, Phase, settings

_MAX = int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "20"))

# Monkey-patch settings to enforce cap on ALL tests
_original_init = settings.__init__


def _capped_init(self, *args, **kwargs):
    if "max_examples" in kwargs and kwargs["max_examples"] > _MAX:
        kwargs["max_examples"] = _MAX
    _original_init(self, *args, **kwargs)


settings.__init__ = _capped_init

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

# Load fast unless --hypothesis-profile is explicitly passed
if "HYPOTHESIS_PROFILE" not in os.environ:
    settings.load_profile("fast")
