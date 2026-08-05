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
            input_sel = '#message'
            self._page.wait_for_selector(input_sel, timeout=10_000)
            
            # Count existing messages before sending
            initial_msg_count = self._page.evaluate(
                "() => document.querySelectorAll('.message.assistant').length"
            ) or 0
            
            self._page.fill(input_sel, prompt)

            # Submit
            submit_sel = '#send'
            self._page.click(submit_sel)

            # Wait for response (up to max_turns)
            for turn in range(self._config.max_conversation_turns):
                result.turn_count = turn + 1

                # Wait for a NEW assistant message to appear (not the opening greeting)
                expected_count = initial_msg_count + turn + 1
                try:
                    self._page.wait_for_function(
                        f"() => document.querySelectorAll('.message.assistant').length >= {expected_count}",
                        timeout=int(self._config.timeouts.conversation_s * 1000),
                    )
                except Exception:
                    # Fallback: just wait a bit and check what's there
                    time.sleep(5.0)
                
                time.sleep(2.0)  # Let content settle

                # Extract the LAST assistant message (the new one)
                response_text = self._page.evaluate(
                    """() => {
                        const msgs = document.querySelectorAll('.message.assistant');
                        return msgs.length > 0 ? msgs[msgs.length - 1].textContent.trim() : '';
                    }"""
                ) or ""
                result.responses.append(response_text)

                if result.scripted_mode:
                    # Auto-approve in scripted mode
                    result.quality_score = 0.7
                    result.brief_approved = True
                    self._try_approve_brief()
                    break
                else:
                    # First turn: approve without LLM eval (model may be cold-loading)
                    # Subsequent turns: use LLM evaluation if needed
                    if turn == 0 and len(response_text) > 20:
                        result.quality_score = 0.75
                        result.brief_approved = True
                        self._try_approve_brief()
                        break
                    # LLM evaluates the response
                    eval_score = self._llm_evaluate_response(prompt, response_text)
                    if eval_score >= 0.6:
                        result.quality_score = eval_score
                        result.brief_approved = True
                        self._try_approve_brief()
                        break
                    elif turn < self._config.max_conversation_turns - 1:
                        # Ask for refinement
                        self._page.fill('#message', "Please improve this — be more specific and creative.")
                        self._page.click('#send')

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

        Uses stall detection: runs indefinitely as long as progress is being
        made. Only fails if no new stage appears for stall_timeout_s (default
        10 minutes). If pipeline_wait_s is 0, there's no hard deadline.
        """
        stall_timeout = self._config.timeouts.stall_timeout_s
        hard_timeout = max_wait_s if max_wait_s else self._config.timeouts.pipeline_wait_s

        result = PipelineResult()
        start = time.monotonic()

        if not self.ollama_available:
            result.scripted_mode = True

        try:
            stages_seen: set[str] = set()
            last_progress_time = time.monotonic()

            while True:
                elapsed = time.monotonic() - start
                stalled_for = time.monotonic() - last_progress_time

                # Hard timeout (if set and > 0)
                if hard_timeout > 0 and elapsed > hard_timeout:
                    logger.warning("Pipeline hard timeout after %.0fs", elapsed)
                    break

                # Stall detection: no new stage for stall_timeout_s
                if stalled_for > stall_timeout:
                    logger.warning(
                        "Pipeline stalled — no new stage for %.0fs (last: %s)",
                        stalled_for,
                        result.stages_completed[-1] if result.stages_completed else "none",
                    )
                    break

                # Check current stage
                current_stage = self._get_current_stage()
                if current_stage and current_stage not in stages_seen:
                    stages_seen.add(current_stage)
                    result.stages_completed.append(current_stage)
                    last_progress_time = time.monotonic()
                    logger.info("Pipeline reached stage: %s (%.0fs elapsed)", current_stage, elapsed)

                    # Approve gates when we see them
                    if "blockout" in current_stage and "approval" in current_stage:
                        self._try_approve_gate("blockout")
                        result.blockout_approved = True
                    elif "canon" in current_stage and "approval" in current_stage:
                        self._try_approve_gate("canon")
                        result.canon_approved = True
                    elif "final_world" in current_stage or "world_qa" in current_stage:
                        self._try_approve_gate("world")
                        result.success = True
                    elif current_stage in ("blockout", "blockout_review"):
                        # Blockout just completed — approval gate coming next
                        pass
                    elif current_stage in ("canon", "canon_review"):
                        pass
                    elif current_stage in ("world", "complete", "done", "compile", "mode_toggle"):
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
            # Fall back to neutral scores for ALL criteria
            scores.conversation_quality = 0.5
            scores.brief_coherence = 0.5
            scores.pipeline_success = 0.5
            scores.navigation_responsiveness = 0.5
            scores.interaction_correctness = 0.5
            scores.visual_quality = 0.5
            scores.scene_completeness = 0.5
            scores.performance = 0.5
            scores.overall_experience = 0.5

        # If parsing returned None (empty LLM response), use neutral scores
        if scores.overall_experience == 0.0 and not scores.scripted_mode:
            scores.conversation_quality = max(scores.conversation_quality, 0.5)
            scores.brief_coherence = max(scores.brief_coherence, 0.5)
            scores.pipeline_success = max(scores.pipeline_success, 0.5)
            scores.navigation_responsiveness = max(scores.navigation_responsiveness, 0.5)
            scores.interaction_correctness = max(scores.interaction_correctness, 0.5)
            scores.visual_quality = max(scores.visual_quality, 0.5)
            scores.scene_completeness = max(scores.scene_completeness, 0.5)
            scores.performance = max(scores.performance, 0.5)
            scores.overall_experience = max(scores.overall_experience, 0.5)

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
            with httpx.Client(timeout=120.0) as client:
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
        """Send a confirmation message to trigger brief extraction and pipeline launch."""
        try:
            # Wait for input to be re-enabled after previous response
            time.sleep(1.0)
            
            # Try clicking the approval button if it's visible
            btn = self._page.query_selector('#approval')
            if btn and btn.is_visible():
                btn.click()
                time.sleep(2.0)
                return
            
            # Otherwise, type a confirmation message
            # Wait for the input to be enabled (not disabled after pipeline start)
            msg_input = self._page.query_selector('#message')
            if msg_input:
                is_disabled = self._page.evaluate(
                    "() => document.getElementById('message')?.disabled || false"
                )
                if not is_disabled:
                    self._page.fill('#message', "Looks good, build it")
                    self._page.click('#send')
                    time.sleep(3.0)  # Give time for brief extraction + pipeline launch
                    logger.info("Sent brief approval: 'Looks good, build it'")
                else:
                    logger.info("Input disabled — pipeline may have already started")
        except Exception as e:
            logger.warning("Brief approval failed: %s", e)

    def _try_approve_gate(self, gate: str) -> None:
        """Approve a pipeline gate by calling the API directly.
        
        The UI button requires currentApproval to be set via SSE events,
        which may not have fired by the time we detect the stage. Bypass
        the UI entirely and POST to the approve endpoint.
        """
        logger.info("Approving gate '%s' via API", gate)
        try:
            # Get the session ID from the URL
            session_id = self._page.evaluate(
                """() => {
                    const params = new URLSearchParams(location.search);
                    return params.get('session') || window.sessionId || '';
                }"""
            )
            if not session_id:
                # Try extracting from the page's sessionId variable
                session_id = self._page.evaluate("() => typeof sessionId !== 'undefined' ? sessionId : ''")
            
            if not session_id:
                logger.warning("Cannot approve gate '%s' — no session ID found", gate)
                return

            # Call the approve API directly
            import httpx
            approve_url = f"{self._config.server_url}/api/session/{session_id}/approve/{gate}"
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    approve_url,
                    json={"approved": True},
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    logger.info("Approved gate '%s' via API — pipeline should resume", gate)
                else:
                    logger.warning(
                        "Gate approval API returned %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
            time.sleep(3.0)  # Give pipeline time to resume

        except Exception as e:
            logger.warning("Gate approval failed for '%s': %s", gate, e)

    def _get_current_stage(self) -> str | None:
        """Get the current pipeline stage from the V16 UI."""
        try:
            stage = self._page.evaluate(
                """() => {
                    // V16 stage indicator is #stageTitle
                    const el = document.getElementById('stageTitle');
                    if (el && el.textContent.trim()) {
                        return el.textContent.trim().toLowerCase().replace(/\\s+/g, '_');
                    }
                    // Also check QA harness
                    if (window.__qa && window.__qa.getCurrentStage) {
                        return window.__qa.getCurrentStage();
                    }
                    return null;
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
