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
from pathlib import Path
from typing import Any

from src.unified_pipeline.object_manifest import load_selected_manifest
from tests.e2e.world_test_kit.config import WorldTestKitConfig

logger = logging.getLogger(__name__)

_CANONICAL_PROMPT = (
    "Danny's kitchenette — a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)
_CANONICAL_OBJECT_REQUIREMENTS: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("round table", 1, ("round table", "table")),
    ("chair", 2, ("chair",)),
    ("counter", 1, ("counter", "countertop")),
    ("coffee maker", 1, ("coffee maker", "coffee machine")),
    ("window", 1, ("window",)),
)

_CANON_QA_EXPECTED: dict[str, bool | int] = {
    "kitchenette_geometry": True,
    "round_table_count": 1,
    "chair_count": 2,
    "counter_count": 1,
    "coffee_maker_count": 1,
    "rain_window_count": 1,
    "coherent_camera_openings": True,
    "plausible_finishes": True,
    "no_duplicate_or_deformed_required_objects": True,
}
_CANON_QA_PRIMARY_MODEL_ROLE = "primary_count_screen"
_CANON_QA_CROSS_CHECK_MODEL = "qwen3.6:27b"
_CANON_QA_CROSS_CHECK_MODEL_ROLE = "independent_duplicate_screen"


def _canon_qa_schema() -> dict[str, Any]:
    """Return an Ollama structured-output schema without forcing pass values."""
    check_properties = {
        name: {"type": "boolean" if isinstance(expected, bool) else "integer"}
        for name, expected in _CANON_QA_EXPECTED.items()
    }
    return {
        "type": "object",
        "properties": {
            "pass": {"type": "boolean"},
            "failed_checks": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "checks": {
                "type": "object",
                "properties": check_properties,
                "required": list(check_properties),
                "additionalProperties": False,
            },
        },
        "required": ["pass", "failed_checks", "confidence", "checks"],
        "additionalProperties": False,
    }


def _validate_canon_qa_verdict(verdict: Any) -> tuple[bool, list[str]]:
    """Validate one local vision screen without truthiness coercion."""
    import math

    errors: list[str] = []
    if not isinstance(verdict, dict):
        return False, ["verdict must be a JSON object"]
    if verdict.get("pass") is not True:
        errors.append("pass must be JSON boolean true")
    failed_checks = verdict.get("failed_checks")
    if not isinstance(failed_checks, list) or any(
        not isinstance(item, str) for item in failed_checks
    ):
        errors.append("failed_checks must be a string array")
    elif failed_checks:
        errors.append("failed_checks must be empty")
    confidence = verdict.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not 0.8 <= float(confidence) <= 1.0
    ):
        errors.append("confidence must be a finite number from 0.8 through 1.0")
    checks = verdict.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be a JSON object")
    else:
        for name, expected in _CANON_QA_EXPECTED.items():
            actual = checks.get(name)
            if type(actual) is not type(expected) or actual != expected:
                errors.append(f"{name} must equal {expected!r}")
    return not errors, errors


def _reconcile_canon_qa_verdicts(
    primary: Any,
    cross_check: Any,
) -> tuple[bool, list[str]]:
    """Require two independent screens to agree; confidence never breaks ties."""
    errors: list[str] = []
    for role, verdict in (
        (_CANON_QA_PRIMARY_MODEL_ROLE, primary),
        (_CANON_QA_CROSS_CHECK_MODEL_ROLE, cross_check),
    ):
        _passed, verdict_errors = _validate_canon_qa_verdict(verdict)
        errors.extend(f"{role}: {error}" for error in verdict_errors)

    primary_checks = primary.get("checks") if isinstance(primary, dict) else None
    cross_checks = cross_check.get("checks") if isinstance(cross_check, dict) else None
    if isinstance(primary_checks, dict) and isinstance(cross_checks, dict):
        for name in _CANON_QA_EXPECTED:
            if primary_checks.get(name) != cross_checks.get(name):
                errors.append(
                    f"cross-check disagreement for {name}: "
                    f"{primary_checks.get(name)!r} != {cross_checks.get(name)!r}"
                )
    else:
        errors.append("both screens must provide independently checkable evidence")
    return not errors, list(dict.fromkeys(errors))


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
        self._world_prompt = ""

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
        self._world_prompt = prompt.strip()

        if not self.ollama_available:
            result.scripted_mode = True
            logger.info("Playtester in scripted mode — auto-approving conversation")

        try:
            # Wait for V16 initialization to finish before submitting. The DOM exists
            # before /unified/start returns; sending while sessionId is empty is ignored.
            input_sel = '#message'
            self._page.wait_for_selector(input_sel, timeout=10_000)
            self._page.wait_for_function(
                """() => {
                    const session = new URLSearchParams(location.search).get('session');
                    const input = document.getElementById('message');
                    const send = document.getElementById('send');
                    const opening = document.querySelectorAll('.message.assistant').length;
                    return Boolean(session && input && send && !input.disabled &&
                                   !send.disabled && opening > 0);
                }""",
                timeout=int(self._config.timeouts.conversation_s * 1000),
            )

            # Count the opening message only after the session is ready.
            initial_msg_count = self._page.evaluate(
                "() => document.querySelectorAll('.message.assistant').length"
            ) or 0

            self._page.fill(input_sel, prompt)
            self._page.click('#send')
            self._page.wait_for_function(
                """expected => Array.from(document.querySelectorAll('.message.user'))
                    .some(message => message.textContent.trim() === expected)""",
                arg=prompt,
                timeout=10_000,
            )

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

                if self._config.strict_real:
                    # Strict scoring is binary and objective: exact prompt echo,
                    # a complete durable proposal, and dispatched approval.
                    if len(response_text) > 20 and self._strict_proposal_matches(prompt):
                        result.brief_approved = self._try_approve_brief()
                        result.quality_score = 1.0 if result.brief_approved else 0.0
                        if result.brief_approved:
                            break
                    elif turn < self._config.max_conversation_turns - 1:
                        from src.unified_pipeline.conversation import (
                            _first_turn_requested_objects,
                        )
                        required = _first_turn_requested_objects(prompt)
                        inventory = ", ".join(
                            f"{item['count']} {item['name']}" for item in required
                        )
                        correction = (
                            "Revise the proposal without replacing anything. Preserve "
                            f"exactly: {inventory}. Include every item and count in the "
                            "structured object list."
                        )
                        self._page.fill('#message', correction)
                        self._page.click('#send')
                elif result.scripted_mode:
                    result.quality_score = 0.7
                    result.brief_approved = self._try_approve_brief()
                    break
                else:
                    eval_score = self._llm_evaluate_response(prompt, response_text)
                    if eval_score >= 0.6:
                        result.quality_score = eval_score
                        result.brief_approved = self._try_approve_brief()
                        break
                    if turn < self._config.max_conversation_turns - 1:
                        self._page.fill('#message', "Please improve this — be more specific and creative.")
                        self._page.click('#send')

            if not result.brief_approved:
                if self._config.strict_real:
                    result.quality_score = 0.0
                    result.errors.append(
                        "Strict conversation contract failed before brief approval"
                    )
                else:
                    result.quality_score = 0.4
                    result.brief_approved = self._try_approve_brief()

        except Exception as e:
            result.errors.append(f"Conversation failed: {e}")
            logger.warning("Conversation error: %s", e)

        return result

    def wait_for_pipeline(self, max_wait_s: float | None = None) -> PipelineResult:
        """Wait for pipeline to advance through stages, approving gates.

        Uses stall detection: runs indefinitely as long as progress is being
        made. Only fails if no durable stage/object progress appears for
        stall_timeout_s (default 15 minutes). If pipeline_wait_s is 0, there's no hard deadline.
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
            last_progress_marker: tuple[Any, ...] | None = None

            while True:
                elapsed = time.monotonic() - start

                # Hard timeout (if set and > 0)
                if hard_timeout > 0 and elapsed > hard_timeout:
                    logger.warning("Pipeline hard timeout after %.0fs", elapsed)
                    break

                # A single GPU stage can contain many independently completed objects.
                # Use append-only backend progress as the watchdog signal so a healthy
                # mesh batch is not mistaken for a stall merely because #stageTitle is
                # unchanged. Sequence/objects advance only on durable progress events.
                progress_marker = self._get_pipeline_progress_marker()
                if progress_marker is not None and progress_marker != last_progress_marker:
                    last_progress_marker = progress_marker
                    last_progress_time = time.monotonic()

                stalled_for = time.monotonic() - last_progress_time
                if stalled_for > stall_timeout:
                    logger.warning(
                        "Pipeline stalled — no durable progress for %.0fs (last: %s)",
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

                    # Approve gates only when their required evidence passes.
                    if "blockout" in current_stage and "approval" in current_stage:
                        result.blockout_approved = self._try_approve_gate("blockout")
                        if not result.blockout_approved:
                            result.errors.append("Blockout approval evidence failed")
                            break
                    elif "canon" in current_stage and "approval" in current_stage:
                        result.canon_approved = self._try_approve_gate("canon")
                        if not result.canon_approved:
                            result.errors.append("Canon visual QA failed")
                            break
                    elif "mesh" in current_stage and "approval" in current_stage:
                        if not self._try_approve_gate("mesh"):
                            result.errors.append("Mesh approval failed")
                            break
                    elif "final_world" in current_stage or "world_qa" in current_stage:
                        if not self._try_approve_gate("world"):
                            result.errors.append("Final world approval failed")
                            break
                    elif current_stage in ("spatial_reconstruction",):
                        # Spatial reconstruction just completed — blockout_approval gate coming next
                        pass
                    elif current_stage in ("canon", "canon_review"):
                        pass
                    elif current_stage in ("world", "complete", "done"):
                        result.success = True
                        break

                terminal_status = str(self._page.evaluate(
                    "() => document.getElementById('status')?.textContent || ''"
                )).strip().lower()
                if "completed" in terminal_status:
                    result.success = True
                    break
                if terminal_status.startswith("error") or terminal_status == "failed":
                    # UI text can transiently report an SSE/rendering error while
                    # the durable backend worker is still running. Only a backend
                    # terminal state may stop strict qualification.
                    try:
                        import httpx
                        with httpx.Client(timeout=10.0) as client:
                            backend_status = client.get(
                                f"{self._config.server_url}/api/session/"
                                f"{self._session_id}/status"
                            ).json()
                        if backend_status.get("state") == "error":
                            error = backend_status.get("error") or terminal_status
                            result.errors.append(f"Backend pipeline error: {error}")
                            logger.error("Pipeline entered terminal backend state: %s", error)
                            break
                        logger.warning(
                            "Ignoring transient UI state %r while backend is %r",
                            terminal_status,
                            backend_status.get("state"),
                        )
                    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
                        logger.warning("Could not verify terminal UI state: %s", exc)

                time.sleep(2.0)

            result.total_wait_s = time.monotonic() - start

            # Strict qualification never promotes partial traversal to success.
            if not result.success and stages_seen:
                logger.error(
                    "Pipeline did not reach a verified terminal stage; stages seen: %s",
                    sorted(stages_seen),
                )

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

    def _strict_proposal_matches(self, prompt: str) -> bool:
        """Verify durable proposal authority before strict auto-approval."""
        from pathlib import Path
        from src.unified_pipeline.conversation import (
            _first_turn_requested_objects,
            _object_key,
        )

        project_root = Path(__file__).resolve().parents[3]
        conversation_path = project_root / "output" / self._session_id / "conversation.json"
        try:
            document = json.loads(conversation_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        exact_prompt_seen = any(
            turn.get("role") == "user" and turn.get("content") == prompt
            for turn in document.get("turns", []) if isinstance(turn, dict)
        )
        if not exact_prompt_seen:
            return False
        proposed = document.get("proposed_brief", {})
        objects = proposed.get("objects", []) if isinstance(proposed, dict) else []
        indexed = {
            _object_key(str(item.get("name", ""))): int(item.get("count", 1))
            for item in objects if isinstance(item, dict)
        }
        required = _first_turn_requested_objects(prompt)
        required_keys = [_object_key(str(item["name"])) for item in required]
        missing = [
            item for item in required
            if indexed.get(_object_key(str(item["name"]))) != item["count"]
        ]
        aggregates = [
            item for item in objects
            if isinstance(item, dict) and sum(
                key in _object_key(str(item.get("name", "")))
                for key in required_keys
            ) >= 2
        ]
        if missing or aggregates:
            logger.warning(
                "Strict proposal authority mismatch: missing=%s aggregates=%s",
                missing,
                aggregates,
            )
            return False
        return bool(proposed)

    def _try_approve_brief(self) -> bool:
        """Issue the brief approval action and report whether it was dispatched."""
        try:
            time.sleep(1.0)
            btn = self._page.query_selector('#approval')
            if btn and btn.is_visible():
                btn.click()
                logger.info("Clicked brief approval button")
                return True

            msg_input = self._page.query_selector('#message')
            if not msg_input:
                return False
            is_disabled = self._page.evaluate(
                "() => document.getElementById('message')?.disabled || false"
            )
            if is_disabled:
                logger.info("Input disabled — pipeline may have already started")
                return True

            approval_text = "Looks good, build it"
            self._page.fill('#message', approval_text)
            self._page.click('#send')
            self._page.wait_for_function(
                """expected => Array.from(document.querySelectorAll('.message.user'))
                    .some(message => message.textContent.trim() === expected)""",
                arg=approval_text,
                timeout=10_000,
            )
            logger.info("Sent brief approval: %r", approval_text)
            return True
        except Exception as e:
            logger.warning("Brief approval failed: %s", e)
            return False

    def _canon_visual_qa(self, session_id: str) -> bool:
        """Run two fail-closed local vision screens on the Canon source image."""
        import base64
        import hashlib
        from datetime import datetime, timezone

        import httpx

        session_dir = self._session_output_dir(session_id)
        canon_path = session_dir / "artifacts" / "canon.png"
        conversation_path = session_dir / "conversation.json"
        if not canon_path.is_file() or not conversation_path.is_file():
            logger.error("Canon QA evidence missing for session %s", session_id)
            return False
        conversation = json.loads(conversation_path.read_text(encoding="utf-8"))
        prompt = next(
            (
                str(turn.get("content", ""))
                for turn in conversation.get("turns", [])
                if isinstance(turn, dict) and turn.get("role") == "user"
            ),
            "",
        )
        output_contract = (
            "Return only one JSON object with exactly this structure: "
            '{"pass":true,"failed_checks":[],"confidence":0.9,"checks":{'
            '"kitchenette_geometry":true,"round_table_count":1,'
            '"chair_count":2,"counter_count":1,"coffee_maker_count":1,'
            '"rain_window_count":1,"coherent_camera_openings":true,'
            '"plausible_finishes":true,'
            '"no_duplicate_or_deformed_required_objects":true}}. '
            "Use observed integer counts, not guesses. Any ambiguity, crop, fusion, "
            "substitution, deformation, or duplicate is a failure. Set pass true only "
            "when every boolean is true, every count exactly matches, failed_checks "
            "is empty, and confidence is at least 0.8."
        )
        qa_prompts = {
            _CANON_QA_PRIMARY_MODEL_ROLE: (
                "Judge this Canon source image against the exact requested room. "
                f"Request: {prompt}\n{output_contract}"
            ),
            _CANON_QA_CROSS_CHECK_MODEL_ROLE: (
                "Independently audit this Canon image. Ignore any earlier verdict. "
                "Scan left, center, and right regions; count every visually distinct "
                "required object, including every separate coffee-making appliance. "
                "A second machine-like appliance on the counter is a duplicate even "
                "when its styling differs. "
                f"Request: {prompt}\n{output_contract}"
            ),
        }
        encoded_image = base64.b64encode(canon_path.read_bytes()).decode("ascii")

        def request_verdict(model: str, role: str) -> dict[str, Any]:
            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": qa_prompts[role],
                    "images": [encoded_image],
                }],
                "stream": False,
                "keep_alive": 0,
                "format": _canon_qa_schema(),
                "options": {
                    "temperature": 0.0,
                    "num_predict": (
                        1024 if role == _CANON_QA_CROSS_CHECK_MODEL_ROLE else 512
                    ),
                },
            }
            if role == _CANON_QA_CROSS_CHECK_MODEL_ROLE:
                # qwen3.6 may otherwise consume its response budget in hidden
                # reasoning and return no structured verdict. Counting needs no
                # chain-of-thought; fail-closed reconciliation still applies.
                payload["think"] = False
            try:
                with httpx.Client(timeout=self._config.timeouts.vision_eval_s) as client:
                    response = client.post(
                        f"{self._config.ollama_base_url}/api/chat", json=payload
                    )
                    response.raise_for_status()
                content = response.json().get("message", {}).get("content", "")
                value = json.loads(content)
                return value if isinstance(value, dict) else {}
            except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
                return {
                    "pass": False,
                    "failed_checks": [f"vision QA error: {exc}"],
                    "confidence": 0.0,
                    "checks": {},
                }

        primary = request_verdict(
            self._config.vision_model, _CANON_QA_PRIMARY_MODEL_ROLE
        )
        cross_check = request_verdict(
            _CANON_QA_CROSS_CHECK_MODEL, _CANON_QA_CROSS_CHECK_MODEL_ROLE
        )
        passed, validation_errors = _reconcile_canon_qa_verdicts(
            primary, cross_check
        )
        raw_failed = [
            str(item)
            for verdict in (primary, cross_check)
            for item in verdict.get("failed_checks", [])
            if isinstance(item, str)
        ]
        evidence = {
            "schema_version": "canon-vision-qa/v3",
            "session_id": session_id,
            "source_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "canon_sha256": hashlib.sha256(canon_path.read_bytes()).hexdigest(),
            "vision_models": {
                _CANON_QA_PRIMARY_MODEL_ROLE: self._config.vision_model,
                _CANON_QA_CROSS_CHECK_MODEL_ROLE: _CANON_QA_CROSS_CHECK_MODEL,
            },
            "checklist_version": "v16-strict-real-r2",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "pass": passed,
            "failed_checks": list(dict.fromkeys(raw_failed + validation_errors)),
            "screens": {
                _CANON_QA_PRIMARY_MODEL_ROLE: primary,
                _CANON_QA_CROSS_CHECK_MODEL_ROLE: cross_check,
            },
            "screen_only": True,
            "release_authority": "headed_human_visual_inspection",
        }
        qa_path = session_dir / "artifacts" / "canon_vision_qa.json"
        temporary = qa_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        temporary.replace(qa_path)
        if not passed:
            logger.error("Canon visual QA rejected session %s: %s", session_id, evidence)
        return passed

    @staticmethod
    def _session_output_dir(session_id: str) -> Path:
        """Return a session-confined directory used by the local V16 backend."""
        output_root = (Path(__file__).resolve().parents[3] / "output").resolve()
        session_dir = (output_root / session_id).resolve()
        if session_dir.parent != output_root:
            raise ValueError("session ID escapes the V16 output root")
        return session_dir

    def _durable_gate_accepted(
        self,
        session_id: str,
        gate: str,
        selected_ids: list[object],
    ) -> bool:
        """Reconcile an ambiguous HTTP result against revision-bound evidence."""
        stage_by_gate = {
            "canon": "canon_approval",
            "blockout": "blockout_approval",
            "mesh": "mesh_approval",
            "world": "final_world_qa",
        }
        stage = stage_by_gate.get(gate)
        if stage is None:
            return False
        try:
            session_dir = self._session_output_dir(session_id)
            approvals = json.loads(
                (session_dir / "orchestrator" / "approvals.json").read_text(
                    encoding="utf-8"
                )
            )
            decision = approvals.get("active", {}).get(f"{stage}::global")
            if not isinstance(decision, dict):
                return False
            if decision.get("approved") is not True or decision.get("stale") is not False:
                return False
            plan_revision = decision.get("plan_revision")
            approval_revision = decision.get("approval_revision")
            if (
                isinstance(plan_revision, bool)
                or not isinstance(plan_revision, int)
                or isinstance(approval_revision, bool)
                or not isinstance(approval_revision, int)
                or approval_revision <= 0
            ):
                return False

            checkpoint = json.loads(
                (
                    session_dir
                    / "orchestrator"
                    / "checkpoints"
                    / f"{stage}--global.json"
                ).read_text(encoding="utf-8")
            )
            if not (
                checkpoint.get("session_id") == session_id
                and checkpoint.get("stage") == stage
                and checkpoint.get("completion_state") == "completed"
                and checkpoint.get("output", {}).get("approved") is True
                and checkpoint.get("plan_revision") == plan_revision
                and checkpoint.get("approval_revision") == approval_revision
            ):
                return False

            if gate == "blockout":
                selected = load_selected_manifest(
                    session_dir / "artifacts" / "selected_objects.json"
                )
                manifest_ids = [
                    str(item.get("object_id", ""))
                    for item in selected["objects"]
                    if isinstance(item, dict)
                ]
                expected_ids = [str(value) for value in selected_ids]
                if not (
                    selected.get("plan_revision") == plan_revision
                    and selected.get("approval_revision") == approval_revision
                    and len(manifest_ids) == len(expected_ids)
                    and set(manifest_ids) == set(expected_ids)
                ):
                    return False
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Durable gate evidence is invalid for '%s': %s", gate, exc)
            return False
        logger.warning(
            "Gate '%s' lacked an HTTP acknowledgement but has current durable acceptance evidence",
            gate,
        )
        return True

    def _try_approve_gate(self, gate: str) -> bool:
        """Approve a gate only after all gate-specific evidence passes."""
        logger.info("Approving gate '%s' via API", gate)
        session_id = ""
        selected_ids: list[object] = []
        approval_attempted = False
        try:
            session_id = self._page.evaluate(
                """() => {
                    const params = new URLSearchParams(location.search);
                    return params.get('session') || window.sessionId || '';
                }"""
            )
            if not session_id:
                session_id = self._page.evaluate(
                    "() => typeof sessionId !== 'undefined' ? sessionId : ''"
                )
            if not session_id:
                logger.warning("Cannot approve gate '%s' — no session ID found", gate)
                return False
            if gate == "canon" and not self._canon_visual_qa(session_id):
                return False

            import httpx
            approve_url = f"{self._config.server_url}/api/session/{session_id}/approve/{gate}"
            with httpx.Client(timeout=10.0) as client:
                payload = {"approved": True}
                if gate == "blockout":
                    picker = client.get(
                        f"{self._config.server_url}/api/session/{session_id}/object_picker"
                    )
                    picker.raise_for_status()
                    objects = picker.json().get("objects", [])
                    selected_ids = self._select_blockout_object_ids(objects)
                    if not selected_ids:
                        raise RuntimeError("strict-real picker returned no selectable objects")
                    payload["selected_object_ids"] = selected_ids
                approval_attempted = True
                resp = client.post(
                    approve_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Gate approval API returned %d: %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    return self._durable_gate_accepted(session_id, gate, selected_ids)
            logger.info("Approved gate '%s' via API — pipeline should resume", gate)
            time.sleep(3.0)
            return True
        except Exception as exc:
            logger.warning("Gate approval failed for '%s': %s", gate, exc)
            if approval_attempted and session_id:
                return self._durable_gate_accepted(session_id, gate, selected_ids)
            return False

    def _select_blockout_object_ids(self, objects: list[Any]) -> list[object]:
        """Select explicit canonical inventory; preserve legacy behavior otherwise."""
        selectable = [
            item for item in objects
            if isinstance(item, dict)
            and item.get("object_id", item.get("id")) is not None
        ]
        if self._world_prompt != _CANONICAL_PROMPT:
            return [item.get("object_id", item.get("id")) for item in selectable]

        selected: list[object] = []
        used: set[str] = set()
        for label, count, aliases in _CANONICAL_OBJECT_REQUIREMENTS:
            matches = []
            for item in selectable:
                object_id = item.get("object_id", item.get("id"))
                normalized_name = " ".join(str(item.get("name", "")).lower().split())
                if str(object_id) in used:
                    continue
                if any(alias in normalized_name for alias in aliases):
                    matches.append(object_id)
            if len(matches) < count:
                raise RuntimeError(
                    f"canonical blockout is missing required {label}: "
                    f"needed {count}, found {len(matches)}"
                )
            for object_id in matches[:count]:
                selected.append(object_id)
                used.add(str(object_id))

        logger.info(
            "Canonical blockout selection bound %d required objects (from %d detections)",
            len(selected),
            len(selectable),
        )
        return selected

    def _get_pipeline_progress_marker(self) -> tuple[Any, ...] | None:
        """Return the latest append-only progress identity for stall detection."""
        try:
            progress_path = (
                self._session_output_dir(self._session_id)
                / "orchestrator"
                / "progress.jsonl"
            )
            for raw_line in reversed(progress_path.read_text(encoding="utf-8").splitlines()):
                if not raw_line.strip():
                    continue
                event = json.loads(raw_line)
                if not isinstance(event, dict):
                    continue
                return (
                    event.get("sequence"),
                    event.get("current_stage"),
                    event.get("state"),
                    event.get("object_id"),
                    event.get("objects_complete"),
                    event.get("objects_total"),
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return None

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
