"""Vision evaluation using qwen2.5vl:7b for screenshot-based quality assessment.

Provides structured evaluation of rendered 3D world screenshots, returning
numeric scores and identified issues. Integrates with the existing
VisionOracle framework but provides a simpler interface for the playtest flow.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from tests.e2e.world_test_kit.config import WorldTestKitConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScreenshotEval:
    """Result of evaluating a single screenshot."""

    scene_match: float = 0.0  # 0–100: how well the scene matches expectations
    quality: float = 0.0  # 0–100: overall visual quality
    issues: list[str] = field(default_factory=list)
    available: bool = True
    raw_response: str = ""


# ---------------------------------------------------------------------------
# Vision Evaluator
# ---------------------------------------------------------------------------


class VisionEvaluator:
    """Vision model evaluator wrapping qwen2.5vl:7b via Ollama.

    Evaluates rendered screenshots for scene correctness, visual quality,
    and identifies issues. Falls back gracefully when the model is unavailable.
    """

    def __init__(self, config: WorldTestKitConfig) -> None:
        self._config = config
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        """Check if the vision model is reachable (cached)."""
        if self._available is None:
            self._available = self._check_available()
        return self._available

    def evaluate_screenshot(self, image_b64: str, context: str) -> ScreenshotEval:
        """Submit screenshot to vision model with context about expected content.

        Args:
            image_b64: Base64-encoded PNG screenshot.
            context: Description of what the scene should show.

        Returns:
            ScreenshotEval with scores and identified issues.
            Returns neutral scores if the model is unavailable.
        """
        if not self.available:
            return ScreenshotEval(
                scene_match=50.0,
                quality=50.0,
                issues=["Vision model unavailable — scores are defaults"],
                available=False,
            )

        prompt = (
            f"Evaluate this 3D rendered scene screenshot.\n\n"
            f"Expected content: {context}\n\n"
            f"Respond with ONLY a JSON object:\n"
            f'{{"scene_match": 0-100, "quality": 0-100, "issues": ["issue1", ...]}}\n\n'
            f"Where:\n"
            f"- scene_match: how well the rendered scene matches the expected content (0=wrong, 100=perfect)\n"
            f"- quality: overall visual quality (lighting, textures, composition) (0=terrible, 100=excellent)\n"
            f"- issues: list of specific problems found (empty if none)\n"
        )

        try:
            raw = self._call_vision(prompt, image_b64)
            return self._parse_eval(raw)
        except Exception as e:
            logger.warning("Vision evaluation failed: %s", e)
            return ScreenshotEval(
                scene_match=50.0,
                quality=50.0,
                issues=[f"Evaluation error: {e}"],
                available=True,
                raw_response=str(e),
            )

    def batch_evaluate(
        self, screenshots: list[tuple[str, str]]
    ) -> list[ScreenshotEval]:
        """Evaluate multiple screenshots in sequence.

        Args:
            screenshots: List of (image_b64, context) tuples.

        Returns:
            List of ScreenshotEval results in the same order.
        """
        results = []
        for image_b64, context in screenshots:
            result = self.evaluate_screenshot(image_b64, context)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_available(self) -> bool:
        """Check if the vision model is available via Ollama."""
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._config.ollama_base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                target = self._config.vision_model
                for name in models:
                    if target in name or name.startswith(target.split(":")[0]):
                        return True
                return False
        except Exception:
            return False

    def _call_vision(self, prompt: str, image_b64: str) -> str:
        """Call the vision model via Ollama chat API."""
        import httpx

        payload = {
            "model": self._config.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64],
                },
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_predict": 512,
            },
        }

        with httpx.Client(timeout=self._config.timeouts.vision_eval_s) as client:
            resp = client.post(
                f"{self._config.ollama_base_url}/api/chat",
                json=payload,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP {resp.status_code}")
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            if not content:
                raise RuntimeError("Empty response from vision model")
            return content

    def _parse_eval(self, raw: str) -> ScreenshotEval:
        """Parse the vision model's JSON response into a ScreenshotEval."""
        text = raw.strip()

        # Handle markdown fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return ScreenshotEval(
                scene_match=50.0,
                quality=50.0,
                issues=["Could not parse vision model response"],
                raw_response=raw,
            )

        try:
            data = json.loads(text[start:end])
        except json.JSONDecodeError:
            return ScreenshotEval(
                scene_match=50.0,
                quality=50.0,
                issues=["Invalid JSON from vision model"],
                raw_response=raw,
            )

        scene_match = max(0.0, min(100.0, float(data.get("scene_match", 50))))
        quality = max(0.0, min(100.0, float(data.get("quality", 50))))
        issues = data.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        issues = [str(i) for i in issues]

        return ScreenshotEval(
            scene_match=scene_match,
            quality=quality,
            issues=issues,
            available=True,
            raw_response=raw,
        )
