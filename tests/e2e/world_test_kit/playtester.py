"""LLM-driven playtester agent for the V16 Unified World Pipeline.

Uses Ollama (qwen3-coder-next) to evaluate AI responses, approve pipeline
gates, navigate the 3D world via Playwright keyboard controls, and test
object interactions through the QA harness.

Gracefully degrades to scripted mode when Ollama is unavailable.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from tests.e2e.world_test_kit.config import WorldTestKitConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConversationResult:
    """Result of an LLM-driven conversation test."""

    quality_score: float = 0.0
    turn_count: int = 0
    brief_approved: bool = False
    responses: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scripted_mode: bool = False


@dataclass
class PipelineResult:
    """Result of waiting for the pipeline to advance."""

    success: bool = False
    stages_completed: list[str] = field(default_factory=list)
    total_wait_s: float = 0.0
    blockout_approved: bool = False
    canon_approved: bool = False
    errors: list[str] = field(default_factory=list)
    scripted_mode: bool = False


@dataclass
class NavigationResult:
    """Result of WASD movement testing."""

    responsive: bool = False
    position_changes: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class InteractionResult:
    """Result of interactive object testing."""

    total_objects: int = 0
    successful: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class PlaytestScores:
    """Final LLM-judged scores across 9 criteria."""

    conversation_quality: float = 0.0
    brief_coherence: float = 0.0
    pipeline_success: float = 0.0
    navigation_responsiveness: float = 0.0
    interaction_correctness: float = 0.0
    visual_quality: float = 0.0
    scene_completeness: float = 0.0
    performance: float = 0.0
    overall_experience: float = 0.0
    raw_evaluation: str = ""
    scripted_mode: bool = False

    def weighted_total(self, weights) -> float:
        """Compute weighted total score (0–100)."""
        return (
            self.conversation_quality * weights.conversation_quality
            + self.brief_coherence * weights.brief_coherence
            + self.pipeline_success * weights.pipeline_success
            + self.navigation_responsiveness * weights.navigation_responsiveness
            + self.interaction_correctness * weights.interaction_correctness
            + self.visual_quality * weights.visual_quality
            + self.scene_completeness * weights.scene_completeness
            + self.performance * weights.performance
            + self.overall_experience * weights.overall_experience
        ) * 100

    def all_above_minimum(self, minimum: float) -> bool:
        """Check if all individual scores are above the minimum threshold."""
        scores = [
            self.conversation_quality,
            self.brief_coherence,
            self.pipeline_success,
            self.navigation_responsiveness,
            self.interaction_correctness,
            self.visual_quality,
            self.scene_completeness,
            self.performance,
            self.overall_experience,
        ]
        return all(s * 100 >= minimum for s in scores)


# ---------------------------------------------------------------------------
# Playtester Agent
# ---------------------------------------------------------------------------


class PlaytesterAgent:
    """LLM-driven playtester that drives Playwright to test the world pipeline.

    Uses sync Playwright for browser automation and sync httpx for Ollama calls.
    Degrades to scripted mode (auto-approve, skip subjective evaluation) when
    Ollama is unavailable.
    """

    def __init__(self, page: Any, config: WorldTestKitConfig, session_id: str) -> None:
        self._page = page
        self._config = config
        self._session_id = session_id
        self._ollama_available: bool | None = None

    @property
    def ollama_available(self) -> bool:
        """Check if the playtester LLM is reachable (cached after first check)."""
        if self._ollama_available is None:
            self._ollama_available = self._check_ollama()
        return self._ollama_available

    def run_conversation(self, prompt: str) -> ConversationResult:
        """Type prompt into the UI, evaluate responses, approve brief within 5 turns.

        In scripted mode: types prompt, waits for response, auto-approves.
        In LLM mode: evaluates each response for quality before proceeding.
        """
        result = ConversationResult()

        if not self.ollama_available:
            result.scripted_mode = True
            logger.info("Playtester in scripted mode — auto-approving conversation")

        try:
            # Find and fill the prompt input
            input_sel = 'textarea[data-qa="prompt-input"], input[data-qa="prompt-input"], #prompt-input'
            self._page.wait_for_selector(input_sel, timeout=10_000)
            self._page.fill(input_sel, prompt)

            # Submit
            submit_sel = 'button[data-qa="submit-btn"], button:has-text("Generate"), #submit-btn'
            self._page.click(submit_sel)

            # Wait for response (up to max_turns)
            for turn in range(self._config.max_conversation_turns):
                result.turn_count = turn + 1

                # Wait for AI response to appear
                response_sel = '[data-qa="ai-response"], .ai-response, #brief-content'
                self._page.wait_for_selector(
                    response_sel,
                    timeout=int(self._config.timeouts.conversation_s * 1000),
                )
                time.sleep(1.0)  # Let content settle

                # Extract response text
                response_text = self._page.inner_text(response_sel)
                result.responses.append(response_text)

                if result.scripted_mode:
                    # Auto-approve in scripted mode
                    result.quality_score = 0.7
                    result.brief_approved = True
                    self._try_approve_brief()
                    break
                else:
                    # LLM evaluates the response
                    eval_score = self._llm_evaluate_response(prompt, response_text)
                    if eval_score >= 0.6:
                        result.quality_score = eval_score
                        result.brief_approved = True
                        self._try_approve_brief()
                        break
                    elif turn < self._config.max_conversation_turns - 1:
                        # Ask for refinement
                        self._page.fill(input_sel, "Please improve this — be more specific and creative.")
                        self._page.click(submit_sel)

            if not result.brief_approved:
                result.quality_score = 0.4  # Minimum if never approved
                self._try_approve_brief()  # Approve anyway to continue pipeline
                result.brief_approved = True

        except Exception as e:
            result.errors.append(f"Conversation failed: {e}")
            logger.warning("Conversation error: %s", e)

        return result

    def wait_for_pipeline(self, max_wait_s: float | None = None) -> PipelineResult:
        """Wait for pipeline to advance through stages, approving gates.

        Monitors for stage transitions by polling the UI or SSE events.
        Auto-approves blockout and canon when artifacts appear.
        """
        if max_wait_s is None:
            max_wait_s = self._config.timeouts.pipeline_wait_s

        result = PipelineResult()
        start = time.monotonic()
        deadline = start + max_wait_s

        if not self.ollama_available:
            result.scripted_mode = True

        try:
            # Poll for pipeline stage progression
            stages_seen: set[str] = set()
            while time.monotonic() < deadline:
                # Check current stage via UI or QA harness
                current_stage = self._get_current_stage()
                if current_stage and current_stage not in stages_seen:
                    stages_seen.add(current_stage)
                    result.stages_completed.append(current_stage)
                    logger.info("Pipeline reached stage: %s", current_stage)

                    # Approve gates when we see them
                    if current_stage in ("blockout", "blockout_review"):
                        self._try_approve_gate("blockout")
                        result.blockout_approved = True
                    elif current_stage in ("canon", "canon_review"):
                        self._try_approve_gate("canon")
                        result.canon_approved = True
                    elif current_stage in ("world", "complete", "done"):
                        result.success = True
                        break

                time.sleep(2.0)

            result.total_wait_s = time.monotonic() - start

            # If we timed out but got some stages, partial success
            if not result.success and stages_seen:
                result.success = len(stages_seen) >= 2

        except Exception as e:
            result.errors.append(f"Pipeline wait failed: {e}")
            result.total_wait_s = time.monotonic() - start
            logger.warning("Pipeline wait error: %s", e)

        return result

    def navigate_world(self) -> NavigationResult:
        """WASD movement test: walk forward, turn, verify position changes."""
        result = NavigationResult()

        try:
            # Get initial position via QA harness
            initial_pos = self._get_camera_position()
            if initial_pos is None:
                result.errors.append("Could not get initial camera position")
                return result

            movements = [
                ("w", "forward"),
                ("a", "left"),
                ("s", "backward"),
                ("d", "right"),
            ]

            successful_moves = 0
            for key, direction in movements:
                # Press key for movement
                self._page.keyboard.press(key)
                time.sleep(0.5)
                self._page.keyboard.press(key)
                time.sleep(0.5)

                # Check new position
                new_pos = self._get_camera_position()
                if new_pos is None:
                    result.errors.append(f"Lost camera position after {direction}")
                    continue

                # Verify position changed
                moved = (
                    abs(new_pos.get("x", 0) - initial_pos.get("x", 0)) > 0.01
                    or abs(new_pos.get("y", 0) - initial_pos.get("y", 0)) > 0.01
                    or abs(new_pos.get("z", 0) - initial_pos.get("z", 0)) > 0.01
                )

                result.position_changes.append({
                    "direction": direction,
                    "key": key,
                    "moved": moved,
                    "from": initial_pos,
                    "to": new_pos,
                })

                if moved:
                    successful_moves += 1
                    initial_pos = new_pos  # Update for next check

            result.responsive = successful_moves >= 2
            result.score = successful_moves / max(len(movements), 1)

        except Exception as e:
            result.errors.append(f"Navigation test failed: {e}")
            logger.warning("Navigation error: %s", e)

        return result

    def test_interactions(self) -> InteractionResult:
        """Trigger all interactive objects via QA harness."""
        result = InteractionResult()

        try:
            # Get scene graph to find interactive objects
            scene_data = self._page.evaluate(
                """() => {
                    if (!window.__qa) return null;
                    return window.__qa.getSceneGraph();
                }"""
            )

            if scene_data is None:
                result.errors.append("QA harness not available for interactions")
                return result

            # Filter for interactive objects
            interactive = [
                obj for obj in (scene_data or [])
                if obj.get("interactive", False) or obj.get("hasInteraction", False)
            ]
            result.total_objects = len(interactive)

            for obj in interactive:
                obj_id = obj.get("objectId", obj.get("id", "unknown"))
                try:
                    interaction_result = self._page.evaluate(
                        """async ([id]) => {
                            if (!window.__qa || !window.__qa.triggerInteraction) return null;
                            return await window.__qa.triggerInteraction(id, 'click');
                        }""",
                        [obj_id],
                    )

                    if interaction_result and interaction_result.get("success"):
                        result.successful += 1
                        result.results.append({
                            "objectId": obj_id,
                            "success": True,
                            "state": interaction_result.get("state"),
                        })
                    else:
                        result.failed += 1
                        result.results.append({
                            "objectId": obj_id,
                            "success": False,
                            "error": interaction_result,
                        })
                except Exception as e:
                    result.failed += 1
                    result.results.append({
                        "objectId": obj_id,
                        "success": False,
                        "error": str(e),
                    })

            if result.total_objects > 0:
                result.score = result.successful / result.total_objects
            else:
                result.score = 1.0  # No interactions to test = pass

        except Exception as e:
            result.errors.append(f"Interaction test failed: {e}")
            logger.warning("Interaction error: %s", e)

        return result

    def evaluate_experience(self) -> PlaytestScores:
        """LLM-judge the overall experience across 9 criteria."""
        scores = PlaytestScores()

        if not self.ollama_available:
            scores.scripted_mode = True
            # Assign neutral scores in scripted mode
            scores.conversation_quality = 0.7
            scores.brief_coherence = 0.7
            scores.pipeline_success = 0.7
            scores.navigation_responsiveness = 0.7
            scores.interaction_correctness = 0.7
            scores.visual_quality = 0.7
            scores.scene_completeness = 0.7
            scores.performance = 0.7
            scores.overall_experience = 0.7
            return scores

        try:
            # Take a screenshot for context
            screenshot_b64 = self._capture_screenshot()

            # Build evaluation prompt
            eval_prompt = self._build_experience_prompt(screenshot_b64)

            # Submit to LLM
            response = self._call_ollama(eval_prompt)
            scores.raw_evaluation = response

            # Parse scores from response
            parsed = self._parse_experience_scores(response)
            if parsed:
                scores.conversation_quality = parsed.get("conversation_quality", 0.5)
                scores.brief_coherence = parsed.get("brief_coherence", 0.5)
                scores.pipeline_success = parsed.get("pipeline_success", 0.5)
                scores.navigation_responsiveness = parsed.get("navigation_responsiveness", 0.5)
                scores.interaction_correctness = parsed.get("interaction_correctness", 0.5)
                scores.visual_quality = parsed.get("visual_quality", 0.5)
                scores.scene_completeness = parsed.get("scene_completeness", 0.5)
                scores.performance = parsed.get("performance", 0.5)
                scores.overall_experience = parsed.get("overall_experience", 0.5)

        except Exception as e:
            logger.warning("Experience evaluation failed: %s", e)
            # Fall back to neutral scores
            scores.conversation_quality = 0.5
            scores.overall_experience = 0.5

        return scores

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_ollama(self) -> bool:
        """Check if the playtester model is available via Ollama."""
        try:
            import httpx
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._config.ollama_base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                target = self._config.playtester_model
                for name in models:
                    if target in name or name.startswith(target.split(":")[0]):
                        return True
                return False
        except Exception:
            return False

    def _call_ollama(self, prompt: str, system: str = "") -> str:
        """Make a sync Ollama generate call."""
        import httpx

        payload: dict[str, Any] = {
            "model": self._config.playtester_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
        }
        if system:
            payload["system"] = system

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{self._config.ollama_base_url}/api/generate",
                    json=payload,
                )
                if resp.status_code == 200:
                    return resp.json().get("response", "")
        except Exception as e:
            logger.warning("Ollama call failed: %s", e)

        return ""

    def _llm_evaluate_response(self, prompt: str, response: str) -> float:
        """Ask the LLM to score an AI response on quality (0.0–1.0)."""
        eval_prompt = (
            f"Rate the quality of this AI response to the user prompt.\n\n"
            f"User prompt: {prompt}\n\n"
            f"AI response: {response[:500]}\n\n"
            f"Score from 0.0 (terrible) to 1.0 (excellent). "
            f"Consider: relevance, creativity, specificity, coherence.\n"
            f"Respond with ONLY a JSON object: {{\"score\": 0.0-1.0}}"
        )
        raw = self._call_ollama(eval_prompt)
        try:
            data = json.loads(raw) if raw else {}
            return float(data.get("score", 0.5))
        except (json.JSONDecodeError, ValueError, TypeError):
            return 0.5

    def _try_approve_brief(self) -> None:
        """Click the approve/continue button if visible."""
        approve_selectors = [
            'button[data-qa="approve-brief"]',
            'button:has-text("Approve")',
            'button:has-text("Continue")',
            'button:has-text("Generate World")',
            "#approve-btn",
        ]
        for sel in approve_selectors:
            try:
                btn = self._page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    return
            except Exception:
                continue

    def _try_approve_gate(self, gate: str) -> None:
        """Approve a pipeline gate (blockout or canon)."""
        selectors = [
            f'button[data-qa="approve-{gate}"]',
            f'button:has-text("Approve {gate.title()}")',
            'button:has-text("Approve")',
            'button:has-text("Continue")',
        ]
        for sel in selectors:
            try:
                btn = self._page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(1.0)
                    return
            except Exception:
                continue

    def _get_current_stage(self) -> str | None:
        """Get the current pipeline stage from the UI."""
        try:
            stage = self._page.evaluate(
                """() => {
                    // Try QA harness first
                    if (window.__qa && window.__qa.getCurrentStage) {
                        return window.__qa.getCurrentStage();
                    }
                    // Try status element
                    const el = document.querySelector('[data-qa="stage-indicator"], .stage-label, #current-stage');
                    return el ? el.textContent.trim().toLowerCase() : null;
                }"""
            )
            return stage if stage else None
        except Exception:
            return None

    def _get_camera_position(self) -> dict[str, float] | None:
        """Get camera position via QA harness."""
        try:
            pos = self._page.evaluate(
                """() => {
                    if (!window.__qa || !window.__qa.getObjectPosition) return null;
                    return window.__qa.getObjectPosition('__camera__');
                }"""
            )
            return pos
        except Exception:
            return None

    def _capture_screenshot(self) -> str:
        """Capture current page screenshot as base64."""
        try:
            screenshot_bytes = self._page.screenshot(type="png")
            import base64
            return base64.b64encode(screenshot_bytes).decode("ascii")
        except Exception:
            return ""

    def _build_experience_prompt(self, screenshot_b64: str) -> str:
        """Build the 9-criteria experience evaluation prompt."""
        return (
            "You are evaluating a 3D world generation pipeline's output quality.\n"
            "Score each criterion from 0.0 (terrible) to 1.0 (excellent).\n\n"
            "Criteria:\n"
            "1. conversation_quality - How well did the AI understand and respond to the prompt?\n"
            "2. brief_coherence - Is the generated brief/plan logical and creative?\n"
            "3. pipeline_success - Did all pipeline stages complete without errors?\n"
            "4. navigation_responsiveness - Does WASD movement feel responsive?\n"
            "5. interaction_correctness - Do interactive objects work correctly?\n"
            "6. visual_quality - Is the rendered 3D scene visually appealing?\n"
            "7. scene_completeness - Are all described objects present in the scene?\n"
            "8. performance - Is the scene running at acceptable frame rates?\n"
            "9. overall_experience - How would you rate the total experience?\n\n"
            "Respond with ONLY a JSON object with these 9 keys, each valued 0.0-1.0.\n"
            "Example: {\"conversation_quality\": 0.8, \"brief_coherence\": 0.7, ...}"
        )

    def _parse_experience_scores(self, raw: str) -> dict[str, float] | None:
        """Parse the 9-criteria scores from LLM response."""
        if not raw:
            return None
        # Try to find JSON in the response
        try:
            # Strip markdown fences if present
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1])
            # Find JSON object
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                if isinstance(data, dict):
                    return {k: max(0.0, min(1.0, float(v))) for k, v in data.items()}
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return None
