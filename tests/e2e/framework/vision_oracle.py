"""Vision oracle module — qwen2.5vl:7b semantic QA for rendered 3D worlds.

Wraps the local qwen2.5vl:7b vision model (via Ollama) to perform structured
seven-category quality checks on World screenshots. Integrates with the
Resource_Arbiter for VRAM scheduling so the vision model loads only after
ComfyUI generation completes.

Requirements: 20.1–20.5, 21.5
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionVerdict:
    """Structured verdict from the vision model.

    Attributes:
        pass_: True if all seven categories pass.
        failed_checks: List of category IDs that failed (empty if pass_=True).
        confidence: Model's confidence in the verdict (0.0–1.0).
        status: "completed", "vision_qa_unavailable", or "parse_error".
        raw_response: The raw text response from the model (for diagnostics).
    """

    pass_: bool
    failed_checks: list[str]
    confidence: float
    status: str = "completed"
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict for artifact storage."""
        return {
            "pass": self.pass_,
            "failed_checks": self.failed_checks,
            "confidence": self.confidence,
            "status": self.status,
            "raw_response": self.raw_response,
        }

    @classmethod
    def unavailable(cls, reason: str = "") -> "VisionVerdict":
        """Return a verdict indicating the vision model is unavailable.

        Requirements: 20.5 — handle unavailability gracefully without failure.
        """
        return cls(
            pass_=False,
            failed_checks=[],
            confidence=0.0,
            status="vision_qa_unavailable",
            raw_response=reason or "Vision QA model unavailable",
        )

    @classmethod
    def parse_error(cls, raw_response: str) -> "VisionVerdict":
        """Return a verdict indicating the model response couldn't be parsed."""
        return cls(
            pass_=False,
            failed_checks=[],
            confidence=0.0,
            status="parse_error",
            raw_response=raw_response,
        )


@dataclass(frozen=True)
class ChecklistCategory:
    """A single category from the seven-category QA checklist."""

    id: str
    name: str
    prompt: str
    weight: float = 1.0


@dataclass
class VisionChecklist:
    """The seven-category QA checklist loaded from config."""

    categories: list[ChecklistCategory] = field(default_factory=list)
    system_prompt: str = ""
    version: str = "1.0.0"

    @classmethod
    def from_json(cls, path: str | Path) -> "VisionChecklist":
        """Load checklist from the JSON config file.

        Args:
            path: Path to vision_qa_checklist.json.

        Returns:
            A populated VisionChecklist instance.

        Raises:
            FileNotFoundError: If the checklist file doesn't exist.
            json.JSONDecodeError: If the file contains invalid JSON.
            KeyError: If required fields are missing.
        """
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        categories = [
            ChecklistCategory(
                id=cat["id"],
                name=cat["name"],
                prompt=cat["prompt"],
                weight=cat.get("weight", 1.0),
            )
            for cat in data["categories"]
        ]
        return cls(
            categories=categories,
            system_prompt=data.get("system_prompt", ""),
            version=data.get("version", "1.0.0"),
        )


# ---------------------------------------------------------------------------
# Vision Oracle
# ---------------------------------------------------------------------------


class VisionOracle:
    """Semantic QA oracle wrapping qwen2.5vl:7b via Ollama.

    Submits World screenshots with the seven-category QA checklist and
    parses structured JSON verdicts. Handles model unavailability gracefully
    by returning a "vision_qa_unavailable" status without failing.

    Requirements:
        20.1 — Submit World screenshot with seven-category checklist
        20.2 — Require structured JSON verdict (pass, failed_checks, confidence)
        20.3 — Auto-accept when pass=true AND confidence >= 0.8
        20.4 — Log failed checks as warnings (advisory, not blocking)
        20.5 — Handle unavailability gracefully
        21.5 — Schedule after ComfyUI generation completes (VRAM via Resource_Arbiter)
    """

    DEFAULT_MODEL = "qwen2.5vl:7b"
    DEFAULT_CONFIDENCE_THRESHOLD = 0.8
    DEFAULT_TIMEOUT_S = 120.0
    # Valid category IDs from the checklist
    VALID_CATEGORIES = frozenset(
        {"geometry", "count", "camera", "openings", "finish", "mood", "scale"}
    )

    def __init__(
        self,
        *,
        model_name: str | None = None,
        confidence_threshold: float | None = None,
        checklist: VisionChecklist | None = None,
        checklist_path: str | Path | None = None,
        ollama_base_url: str = "http://127.0.0.1:11434",
        timeout_s: float | None = None,
    ) -> None:
        """Initialize the VisionOracle.

        Args:
            model_name: Ollama model name. Defaults to "qwen2.5vl:7b".
            confidence_threshold: Minimum confidence for auto-accept. Default 0.8.
            checklist: Pre-loaded VisionChecklist. If None, loads from checklist_path.
            checklist_path: Path to vision_qa_checklist.json. Used if checklist is None.
            ollama_base_url: Ollama API base URL. Default localhost:11434.
            timeout_s: Max seconds to wait for model response. Default 120s.
        """
        self.model_name = model_name or self.DEFAULT_MODEL
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else self.DEFAULT_CONFIDENCE_THRESHOLD
        )
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.timeout_s = timeout_s or self.DEFAULT_TIMEOUT_S

        # Load checklist
        if checklist is not None:
            self.checklist = checklist
        elif checklist_path is not None:
            self.checklist = VisionChecklist.from_json(checklist_path)
        else:
            # Default path relative to this file
            default_path = (
                Path(__file__).resolve().parent.parent
                / "config"
                / "vision_qa_checklist.json"
            )
            self.checklist = VisionChecklist.from_json(default_path)

    def evaluate(
        self,
        image_data: bytes | str,
        *,
        additional_context: str = "",
    ) -> VisionVerdict:
        """Evaluate a World screenshot against the seven-category QA checklist.

        This is the main entry point for synchronous evaluation. It calls
        the Ollama chat API with the image and checklist prompt, then parses
        the structured JSON response.

        Args:
            image_data: Either raw image bytes (PNG/JPEG) or a base64-encoded
                        string of the image.
            additional_context: Optional extra context about the scene
                                (e.g., the conversation description).

        Returns:
            A VisionVerdict with the structured assessment. On any error
            (model unavailable, parse failure, timeout), returns a verdict
            with status != "completed" — never raises.

        Requirements: 20.1–20.5
        """
        # Convert to base64 if raw bytes
        if isinstance(image_data, bytes):
            image_b64 = base64.b64encode(image_data).decode("ascii")
        else:
            image_b64 = image_data

        # Build the user prompt with the checklist
        user_prompt = self._build_prompt(additional_context)

        # Call Ollama
        try:
            raw_response = self._call_ollama(
                system_prompt=self.checklist.system_prompt,
                user_prompt=user_prompt,
                image_b64=image_b64,
            )
        except VisionOracleUnavailable as exc:
            logger.warning(
                "Vision QA unavailable: %s — returning skip status", exc
            )
            return VisionVerdict.unavailable(str(exc))

        # Parse the response
        verdict = self._parse_verdict(raw_response)
        return verdict

    def is_auto_accept(self, verdict: VisionVerdict) -> bool:
        """Check if a verdict qualifies for automatic acceptance.

        Auto-accept when pass == True AND confidence >= threshold.
        Requirements: 20.3
        """
        return (
            verdict.status == "completed"
            and verdict.pass_
            and verdict.confidence >= self.confidence_threshold
        )

    def is_available(self) -> bool:
        """Check if the vision model is available via Ollama.

        Makes a lightweight API call to verify the model can be reached.
        Returns False on any failure without raising.
        """
        try:
            import httpx

            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.ollama_base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                data = resp.json()
                models = data.get("models", [])
                model_names = [m.get("name", "") for m in models]
                # Check if our model is available (with or without :latest tag)
                for name in model_names:
                    base_name = name.split(":")[0] if ":" in name else name
                    if (
                        name == self.model_name
                        or base_name == self.model_name.split(":")[0]
                    ):
                        return True
                return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _build_prompt(self, additional_context: str = "") -> str:
        """Build the user prompt incorporating the seven-category checklist.

        Requirements: 20.1 — seven-category QA checklist
        """
        lines = [
            "Evaluate this rendered 3D world screenshot against the following "
            "quality checklist. For each category, determine PASS or FAIL.",
            "",
        ]

        for cat in self.checklist.categories:
            lines.append(f"**{cat.id.upper()} — {cat.name}:** {cat.prompt}")
            lines.append("")

        if additional_context:
            lines.append(f"**Scene context:** {additional_context}")
            lines.append("")

        lines.extend([
            "Respond with ONLY a JSON object in this exact format:",
            '{"pass": true/false, "failed_checks": ["category_id", ...], "confidence": 0.0-1.0}',
            "",
            "Rules:",
            '- "pass" is true only if ALL categories pass',
            '- "failed_checks" contains the IDs of categories that failed (empty if pass is true)',
            '- "confidence" is your overall confidence in the verdict (0.0 to 1.0)',
            "- Respond with ONLY the JSON, no other text",
        ])

        return "\n".join(lines)

    def _call_ollama(
        self,
        system_prompt: str,
        user_prompt: str,
        image_b64: str,
    ) -> str:
        """Call the Ollama chat API with the image.

        Uses httpx for synchronous HTTP calls to the Ollama REST API.

        Args:
            system_prompt: System message for the model.
            user_prompt: User message with the checklist prompt.
            image_b64: Base64-encoded image data.

        Returns:
            The model's text response.

        Raises:
            VisionOracleUnavailable: On any communication or model error.
        """
        import httpx

        url = f"{self.ollama_base_url}/api/chat"
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [image_b64],
                },
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,  # Low temp for deterministic QA
                "num_predict": 512,  # Bounded output
            },
        }

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise VisionOracleUnavailable(
                f"Ollama request timed out after {self.timeout_s}s: {exc}"
            ) from exc
        except (httpx.ConnectError, httpx.HTTPError, OSError) as exc:
            raise VisionOracleUnavailable(
                f"Cannot reach Ollama at {self.ollama_base_url}: {exc}"
            ) from exc

        if resp.status_code != 200:
            raise VisionOracleUnavailable(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise VisionOracleUnavailable(
                f"Ollama returned non-JSON response: {exc}"
            ) from exc

        # Extract the message content from the chat response
        message = data.get("message", {})
        content = message.get("content", "")
        if not content:
            raise VisionOracleUnavailable(
                "Ollama returned empty content in response"
            )

        return content

    def _parse_verdict(self, raw_response: str) -> VisionVerdict:
        """Parse a structured JSON verdict from the model response.

        Handles various response formats: pure JSON, JSON in markdown fences,
        or JSON embedded in text. Validates the required fields.

        Requirements: 20.2 — structured JSON with pass, failed_checks, confidence
        """
        # Try to extract JSON from the response
        json_str = self._extract_json(raw_response)
        if json_str is None:
            logger.warning(
                "Vision QA: could not extract JSON from response: %s",
                raw_response[:200],
            )
            return VisionVerdict.parse_error(raw_response)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(
                "Vision QA: invalid JSON in response: %s", json_str[:200]
            )
            return VisionVerdict.parse_error(raw_response)

        if not isinstance(data, dict):
            logger.warning("Vision QA: response is not a JSON object")
            return VisionVerdict.parse_error(raw_response)

        # Extract and validate fields
        pass_value = data.get("pass")
        failed_checks = data.get("failed_checks", [])
        confidence = data.get("confidence", 0.0)

        # Validate types
        if not isinstance(pass_value, bool):
            # Try to coerce common responses
            if pass_value in (1, "true", "True"):
                pass_value = True
            elif pass_value in (0, "false", "False"):
                pass_value = False
            else:
                logger.warning(
                    "Vision QA: 'pass' field is not boolean: %r", pass_value
                )
                return VisionVerdict.parse_error(raw_response)

        if not isinstance(failed_checks, list):
            failed_checks = []

        # Filter to valid category IDs only
        failed_checks = [
            check
            for check in failed_checks
            if isinstance(check, str) and check in self.VALID_CATEGORIES
        ]

        # Validate and clamp confidence
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        # Consistency check: if pass=True but failed_checks is non-empty, resolve
        if pass_value and failed_checks:
            pass_value = False

        # If pass=False but no failed_checks, that's fine — model may be uncertain

        return VisionVerdict(
            pass_=pass_value,
            failed_checks=failed_checks,
            confidence=confidence,
            status="completed",
            raw_response=raw_response,
        )

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Extract a JSON object from potentially messy model output.

        Handles:
        - Pure JSON text
        - JSON in markdown code fences (```json ... ```)
        - JSON embedded in surrounding text
        """
        text = text.strip()

        # Try direct parse first
        if text.startswith("{"):
            # Find the matching closing brace
            brace_count = 0
            for i, ch in enumerate(text):
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        return text[: i + 1]
            return text  # No matched brace, try anyway

        # Try markdown code fence
        fence_pattern = re.compile(
            r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL
        )
        match = fence_pattern.search(text)
        if match:
            return match.group(1).strip()

        # Try to find embedded JSON object
        obj_pattern = re.compile(r"\{[^{}]*\}", re.DOTALL)
        match = obj_pattern.search(text)
        if match:
            return match.group(0)

        return None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VisionOracleUnavailable(Exception):
    """Raised internally when the vision model cannot be reached.

    This is caught by VisionOracle.evaluate() and converted to a
    VisionVerdict with status="vision_qa_unavailable". It never propagates
    to the caller — the oracle handles unavailability gracefully (Req 20.5).
    """

    pass
