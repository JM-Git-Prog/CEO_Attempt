"""E2E World Test Kit — unified LLM-driven playtester for the V16 Unified World Pipeline.

Provides a 9-layer automated playtest that uses local Ollama models to drive
Playwright, evaluate AI conversations, approve pipeline gates, navigate the 3D
world, test interactions, and score the overall experience.

Gracefully degrades to scripted mode when Ollama models are unavailable.
"""

__version__ = "1.0.0"

from tests.e2e.world_test_kit.config import WorldTestKitConfig, load_wtk_config
from tests.e2e.world_test_kit.orchestrator import WorldTestOrchestrator
from tests.e2e.world_test_kit.playtester import PlaytesterAgent
from tests.e2e.world_test_kit.evaluator import VisionEvaluator
from tests.e2e.world_test_kit.reporter import PlaytestReporter

__all__ = [
    "__version__",
    "WorldTestKitConfig",
    "load_wtk_config",
    "WorldTestOrchestrator",
    "PlaytesterAgent",
    "VisionEvaluator",
    "PlaytestReporter",
]
