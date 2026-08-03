"""Top-level orchestrator for the World Test Kit playtest run.

Coordinates the 9-layer test sequence, manages VRAM scheduling (ComfyUI first,
then vision model, then perceptual metrics), and produces the final report.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.e2e.world_test_kit.config import WorldTestKitConfig, load_wtk_config
from tests.e2e.world_test_kit.playtester import (
    ConversationResult,
    InteractionResult,
    NavigationResult,
    PipelineResult,
    PlaytestScores,
    PlaytesterAgent,
)
from tests.e2e.world_test_kit.evaluator import ScreenshotEval, VisionEvaluator
from tests.e2e.world_test_kit.reporter import PlaytestReport, PlaytestReporter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class LayerResult:
    """Result from a single test layer."""

    name: str
    passed: bool = False
    score: float = 0.0
    duration_s: float = 0.0
    skipped: bool = False
    error: str | None = None
    details: Any = None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class WorldTestOrchestrator:
    """Execute the full 9-layer playtest run.

    Manages:
    1. Server availability check
    2. Session creation
    3. Layer sequencing with VRAM awareness
    4. Report generation
    """

    def __init__(self, config: WorldTestKitConfig | None = None) -> None:
        self._config = config or load_wtk_config()
        self._reporter = PlaytestReporter(self._config)

    def run(self, prompt: str, layers: list[str] | None = None) -> PlaytestReport:
        """Execute the full 9-layer test run.

        Args:
            prompt: The world description prompt to submit.
            layers: Optional list of layer names to run. If None, runs all
                    enabled layers from config.

        Returns:
            PlaytestReport with scores, pass/fail, and detailed results.
        """
        session_id = uuid.uuid4().hex[:12]
        start_time = time.monotonic()
        results: dict[str, LayerResult] = {}

        logger.info("World Test Kit run starting — session=%s", session_id)

        # Determine which layers to run
        active_layers = self._resolve_layers(layers)
        logger.info("Active layers: %s", active_layers)

        # Import playwright sync API
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return self._reporter.generate({
                "session_id": session_id,
                "prompt": prompt,
                "error": "playwright not installed — run: pip install playwright",
                "duration_s": time.monotonic() - start_time,
                "layers": {},
            })

        # Check server is running before launching browser
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._config.server_url}/?v=16")
                if resp.status_code != 200:
                    return self._reporter.generate({
                        "session_id": session_id,
                        "prompt": prompt,
                        "error": f"Server returned HTTP {resp.status_code}. Start it with: python -c \"import uvicorn; uvicorn.run('src.web.app:app', host='127.0.0.1', port=8000)\"",
                        "duration_s": time.monotonic() - start_time,
                        "layers": {},
                    })
        except Exception as e:
            return self._reporter.generate({
                "session_id": session_id,
                "prompt": prompt,
                "error": f"Server not running at {self._config.server_url} — start it first. Error: {e}",
                "duration_s": time.monotonic() - start_time,
                "layers": {},
            })

        # Launch browser and run layers
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=self._config.headless)
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                )
                page = context.new_page()

                # Navigate to the application — let V16 JS create a fresh session
                url = f"{self._config.server_url}/?v=16&qa=1"
                page.goto(url, wait_until="networkidle", timeout=30_000)
                
                # Wait for V16 to create its session and show the conversation UI
                page.wait_for_selector('#message', timeout=15_000)

                # Create the playtester agent
                agent = PlaytesterAgent(page, self._config, session_id)

                # Create vision evaluator (loaded later for VRAM management)
                evaluator = VisionEvaluator(self._config)

                # Run layers in sequence
                if "conversation" in active_layers:
                    results["conversation"] = self._run_conversation(agent, prompt)

                if "pipeline_wait" in active_layers:
                    results["pipeline_wait"] = self._run_pipeline_wait(agent)

                # --- VRAM boundary: ComfyUI generation should be done by now ---

                if "navigation" in active_layers:
                    results["navigation"] = self._run_navigation(agent)

                if "interactions" in active_layers:
                    results["interactions"] = self._run_interactions(agent)

                # --- Vision model can load now (ComfyUI done) ---

                if "vision_eval" in active_layers:
                    results["vision_eval"] = self._run_vision_eval(
                        page, evaluator, prompt
                    )

                if "scene_validation" in active_layers:
                    results["scene_validation"] = self._run_scene_validation(page)

                if "performance" in active_layers:
                    results["performance"] = self._run_performance(page)

                if "accessibility" in active_layers:
                    results["accessibility"] = self._run_accessibility(page)

                # --- Experience judge (uses playtester model, not vision) ---

                if "experience_judge" in active_layers:
                    results["experience_judge"] = self._run_experience_judge(agent)

                browser.close()

        except Exception as e:
            logger.error("Orchestrator failed: %s", e)
            results["_fatal"] = LayerResult(
                name="_fatal",
                passed=False,
                error=str(e),
            )

        duration_s = time.monotonic() - start_time
        logger.info("World Test Kit run complete — %.1fs", duration_s)

        return self._reporter.generate({
            "session_id": session_id,
            "prompt": prompt,
            "duration_s": duration_s,
            "layers": {name: self._layer_to_dict(lr) for name, lr in results.items()},
        })

    # ------------------------------------------------------------------
    # Layer implementations
    # ------------------------------------------------------------------

    def _run_conversation(self, agent: PlaytesterAgent, prompt: str) -> LayerResult:
        """Layer 1: LLM-driven conversation and brief approval."""
        start = time.monotonic()
        try:
            result = agent.run_conversation(prompt)
            score = result.quality_score * 100
            return LayerResult(
                name="conversation",
                passed=result.brief_approved and score >= self._config.individual_minimum,
                score=score,
                duration_s=time.monotonic() - start,
                details=result,
            )
        except Exception as e:
            return LayerResult(
                name="conversation",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_pipeline_wait(self, agent: PlaytesterAgent) -> LayerResult:
        """Layer 2: Wait for pipeline stages to complete."""
        start = time.monotonic()
        try:
            result = agent.wait_for_pipeline()
            score = 100.0 if result.success else (len(result.stages_completed) * 25.0)
            return LayerResult(
                name="pipeline_wait",
                passed=result.success,
                score=min(score, 100.0),
                duration_s=time.monotonic() - start,
                details=result,
            )
        except Exception as e:
            return LayerResult(
                name="pipeline_wait",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_navigation(self, agent: PlaytesterAgent) -> LayerResult:
        """Layer 3: WASD movement testing."""
        start = time.monotonic()
        try:
            result = agent.navigate_world()
            score = result.score * 100
            return LayerResult(
                name="navigation",
                passed=result.responsive,
                score=score,
                duration_s=time.monotonic() - start,
                details=result,
            )
        except Exception as e:
            return LayerResult(
                name="navigation",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_interactions(self, agent: PlaytesterAgent) -> LayerResult:
        """Layer 4: Interactive object testing."""
        start = time.monotonic()
        try:
            result = agent.test_interactions()
            score = result.score * 100
            return LayerResult(
                name="interactions",
                passed=score >= self._config.individual_minimum,
                score=score,
                duration_s=time.monotonic() - start,
                details=result,
            )
        except Exception as e:
            return LayerResult(
                name="interactions",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_vision_eval(
        self, page: Any, evaluator: VisionEvaluator, prompt: str
    ) -> LayerResult:
        """Layer 5: Vision model screenshot evaluation."""
        start = time.monotonic()
        try:
            import base64

            screenshot_bytes = page.screenshot(type="png")
            image_b64 = base64.b64encode(screenshot_bytes).decode("ascii")

            result = evaluator.evaluate_screenshot(image_b64, prompt)
            score = (result.scene_match + result.quality) / 2.0
            return LayerResult(
                name="vision_eval",
                passed=score >= self._config.individual_minimum,
                score=score,
                duration_s=time.monotonic() - start,
                details=result,
            )
        except Exception as e:
            return LayerResult(
                name="vision_eval",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_scene_validation(self, page: Any) -> LayerResult:
        """Layer 6: Scene graph validation via QA harness."""
        start = time.monotonic()
        try:
            scene_graph = page.evaluate(
                """() => {
                    if (!window.__qa || !window.__qa.getSceneGraph) return null;
                    return window.__qa.getSceneGraph();
                }"""
            )
            if scene_graph is None:
                return LayerResult(
                    name="scene_validation",
                    passed=False,
                    score=0.0,
                    duration_s=time.monotonic() - start,
                    error="QA harness not available",
                )

            obj_count = len(scene_graph) if isinstance(scene_graph, list) else 0
            # Basic validation: scene has objects
            score = min(100.0, obj_count * 10.0) if obj_count > 0 else 0.0
            return LayerResult(
                name="scene_validation",
                passed=obj_count > 0,
                score=score,
                duration_s=time.monotonic() - start,
                details={"object_count": obj_count},
            )
        except Exception as e:
            return LayerResult(
                name="scene_validation",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_performance(self, page: Any) -> LayerResult:
        """Layer 7: Frame rate and performance check."""
        start = time.monotonic()
        try:
            perf = page.evaluate(
                """() => {
                    if (!window.__qa || !window.__qa.getRendererInfo) return null;
                    return window.__qa.getRendererInfo();
                }"""
            )
            # A simple FPS check via requestAnimationFrame timing
            fps = page.evaluate(
                """() => new Promise(resolve => {
                    let frames = 0;
                    const start = performance.now();
                    function count() {
                        frames++;
                        if (performance.now() - start < 1000) {
                            requestAnimationFrame(count);
                        } else {
                            resolve(frames);
                        }
                    }
                    requestAnimationFrame(count);
                })"""
            )

            fps_val = float(fps) if fps else 0
            # Score: 60fps = 100, 30fps = 75, 15fps = 50, <10 = 25
            if fps_val >= 55:
                score = 100.0
            elif fps_val >= 30:
                score = 75.0
            elif fps_val >= 15:
                score = 50.0
            else:
                score = 25.0

            return LayerResult(
                name="performance",
                passed=fps_val >= 15,
                score=score,
                duration_s=time.monotonic() - start,
                details={"fps": fps_val, "renderer_info": perf},
            )
        except Exception as e:
            return LayerResult(
                name="performance",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_accessibility(self, page: Any) -> LayerResult:
        """Layer 8: Basic accessibility checks."""
        start = time.monotonic()
        try:
            # Check for alt text, aria labels, keyboard navigation
            a11y = page.evaluate(
                """() => {
                    const images = document.querySelectorAll('img');
                    const missingAlt = Array.from(images).filter(i => !i.alt).length;
                    const buttons = document.querySelectorAll('button');
                    const missingLabel = Array.from(buttons).filter(
                        b => !b.getAttribute('aria-label') && !b.textContent.trim()
                    ).length;
                    return {
                        total_images: images.length,
                        missing_alt: missingAlt,
                        total_buttons: buttons.length,
                        missing_label: missingLabel,
                    };
                }"""
            )

            if a11y is None:
                return LayerResult(
                    name="accessibility",
                    passed=True,
                    score=70.0,
                    duration_s=time.monotonic() - start,
                )

            # Score based on compliance
            issues = a11y.get("missing_alt", 0) + a11y.get("missing_label", 0)
            total = a11y.get("total_images", 0) + a11y.get("total_buttons", 0)
            if total == 0:
                score = 100.0
            else:
                score = max(0.0, (1 - issues / max(total, 1)) * 100)

            return LayerResult(
                name="accessibility",
                passed=score >= self._config.individual_minimum,
                score=score,
                duration_s=time.monotonic() - start,
                details=a11y,
            )
        except Exception as e:
            return LayerResult(
                name="accessibility",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    def _run_experience_judge(self, agent: PlaytesterAgent) -> LayerResult:
        """Layer 9: LLM-judged overall experience evaluation."""
        start = time.monotonic()
        try:
            scores = agent.evaluate_experience()
            total = scores.weighted_total(self._config.weights)
            return LayerResult(
                name="experience_judge",
                passed=total >= self._config.pass_threshold,
                score=total,
                duration_s=time.monotonic() - start,
                details=scores,
            )
        except Exception as e:
            return LayerResult(
                name="experience_judge",
                passed=False,
                duration_s=time.monotonic() - start,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_layers(self, requested: list[str] | None) -> list[str]:
        """Resolve which layers to run based on config and request."""
        all_layers = [
            ("conversation", self._config.layers.conversation),
            ("pipeline_wait", self._config.layers.pipeline_wait),
            ("navigation", self._config.layers.navigation),
            ("interactions", self._config.layers.interactions),
            ("vision_eval", self._config.layers.vision_eval),
            ("scene_validation", self._config.layers.scene_validation),
            ("performance", self._config.layers.performance),
            ("accessibility", self._config.layers.accessibility),
            ("experience_judge", self._config.layers.experience_judge),
        ]

        if requested is not None:
            return [name for name, _ in all_layers if name in requested]

        return [name for name, enabled in all_layers if enabled]

    @staticmethod
    def _layer_to_dict(lr: LayerResult) -> dict[str, Any]:
        """Convert a LayerResult to a serializable dict."""
        d: dict[str, Any] = {
            "name": lr.name,
            "passed": lr.passed,
            "score": lr.score,
            "duration_s": round(lr.duration_s, 2),
        }
        if lr.skipped:
            d["skipped"] = True
        if lr.error:
            d["error"] = lr.error
        # Don't serialize complex detail objects — reporter handles that
        return d
