"""Semantic labeling via Ollama vision analysis with heuristic fallback.

Assigns semantic labels to segmented objects using a vision-capable Ollama
model. Falls back to dimension-based heuristics when Ollama is unavailable
or returns unparseable results.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.photo_pipeline.models_v14 import (
    VALID_CATEGORIES,
    VALID_MATERIALS,
    SemanticLabel,
)

logger = logging.getLogger(__name__)


class SemanticLabeler:
    """Assign semantic labels to objects via Ollama vision analysis.

    Sends Object_PNG to a vision-capable Ollama model with a structured
    prompt requesting JSON output. Validates the response fields against
    the V14 taxonomy. Falls back to heuristic labeling on any failure
    (timeout, parse error, invalid response, Ollama unavailable).
    """

    MATERIAL_DENSITIES: dict[str, float] = {
        "wood": 600,
        "metal": 7800,
        "glass": 2500,
        "fabric": 200,
        "ceramic": 2300,
        "plastic": 950,
    }

    # Structured prompt for Ollama vision model
    _PROMPT = (
        "Analyze this image of a single object on a transparent background. "
        "Respond ONLY with a valid JSON object (no markdown, no explanation) "
        "containing these exact fields:\n"
        "{\n"
        '  "semantic_label": "<concise description, e.g. wooden dining chair>",\n'
        '  "primary_material": "<one of: wood, metal, glass, fabric, ceramic, plastic>",\n'
        '  "category": "<one of: props, architecture, foliage, hard-surface, set-dressing>",\n'
        '  "estimated_era": "<period/style, e.g. mid-century modern>",\n'
        '  "condition": "<one of: new, worn, broken>",\n'
        '  "is_architectural": <true or false>\n'
        "}"
    )

    def __init__(self, ollama_url: str = "http://localhost:11434") -> None:
        """Initialize with Ollama server URL.

        Args:
            ollama_url: Base URL for the Ollama API server.
        """
        self._ollama_url = ollama_url.rstrip("/")
        self._model = "llava"  # Vision-capable model

    async def label(
        self, object_png: Path, *, timeout_s: float = 10.0
    ) -> SemanticLabel:
        """Send Object_PNG to Ollama, parse structured JSON response.

        Encodes the image as base64, sends to Ollama's chat API with a
        structured prompt, parses the JSON response, and validates all
        fields. Falls back to heuristic labeling on any failure.

        Args:
            object_png: Path to the isolated object RGBA PNG.
            timeout_s: Maximum time to wait for Ollama response (default 10s).

        Returns:
            A validated SemanticLabel from Ollama or heuristic fallback.
        """
        try:
            # Read and encode image as base64
            image_data = object_png.read_bytes()
            image_b64 = base64.b64encode(image_data).decode("ascii")

            # Build request payload for Ollama chat API
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": self._PROMPT,
                        "images": [image_b64],
                    }
                ],
                "stream": False,
                "options": {
                    "flash_attn": True,
                },
            }

            # Send request with timeout
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._ollama_url}/api/chat",
                    json=payload,
                    timeout=timeout_s,
                )
                response.raise_for_status()

            # Parse response
            result = response.json()
            content = result.get("message", {}).get("content", "")

            # Parse JSON from content (handle potential markdown wrapping)
            parsed = self._parse_json_response(content)
            if parsed is None:
                logger.warning(
                    "Failed to parse Ollama JSON response for %s, using fallback",
                    object_png.name,
                )
                return self._fallback_from_image(object_png)

            # Validate and construct SemanticLabel
            label = self._validate_response(parsed)
            if label is None:
                logger.warning(
                    "Ollama response validation failed for %s, using fallback",
                    object_png.name,
                )
                return self._fallback_from_image(object_png)

            return label

        except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
            logger.warning(
                "Ollama labeling failed for %s: %s, using fallback",
                object_png.name,
                exc,
            )
            return self._fallback_from_image(object_png)
        except Exception as exc:
            logger.warning(
                "Unexpected error during Ollama labeling for %s: %s, using fallback",
                object_png.name,
                exc,
            )
            return self._fallback_from_image(object_png)

    def fallback_label(
        self, width: int, height: int, area_px: int
    ) -> SemanticLabel:
        """Heuristic fallback when Ollama unavailable.

        Classifies objects based on dimensions and area:
        - large + rectangular (area > 50000, 0.5 < aspect < 2.0)
            → category="props", material="wood", label="furniture item"
        - small + uniform (area < 5000)
            → category="set-dressing", material="ceramic",
              label="small decorative object"
        - tall + narrow (aspect < 0.5)
            → category="architecture", material="wood",
              label="structural element", is_architectural=True
        - default
            → category="props", material="plastic",
              label="unidentified object"

        Args:
            width: Object bounding box width in pixels.
            height: Object bounding box height in pixels.
            area_px: Object mask area in pixels.

        Returns:
            A valid SemanticLabel produced from heuristics.
        """
        # Compute aspect ratio (width / height), guard against zero
        aspect = width / height if height > 0 else 1.0

        # Large + rectangular → furniture
        if area_px > 50000 and 0.5 < aspect < 2.0:
            return SemanticLabel(
                semantic_label="furniture item",
                primary_material="wood",
                category="props",
                estimated_era="contemporary",
                condition="worn",
                is_architectural=False,
            )

        # Small + uniform → decorative
        if area_px < 5000:
            return SemanticLabel(
                semantic_label="small decorative object",
                primary_material="ceramic",
                category="set-dressing",
                estimated_era="contemporary",
                condition="new",
                is_architectural=False,
            )

        # Tall + narrow → architectural
        if aspect < 0.5:
            return SemanticLabel(
                semantic_label="structural element",
                primary_material="wood",
                category="architecture",
                estimated_era="contemporary",
                condition="worn",
                is_architectural=True,
            )

        # Default
        return SemanticLabel(
            semantic_label="unidentified object",
            primary_material="plastic",
            category="props",
            estimated_era="contemporary",
            condition="new",
            is_architectural=False,
        )

    def _fallback_from_image(self, object_png: Path) -> SemanticLabel:
        """Generate a fallback label from image file dimensions.

        Reads the PNG header to determine width/height, estimates area
        from those dimensions, and delegates to fallback_label().
        """
        try:
            # Try to get image dimensions from PNG header
            width, height = self._read_png_dimensions(object_png)
            area_px = width * height  # Approximate area from bounding box
        except Exception:
            # If we can't even read the PNG, use default
            width, height, area_px = 100, 100, 10000

        return self.fallback_label(width, height, area_px)

    @staticmethod
    def _read_png_dimensions(png_path: Path) -> tuple[int, int]:
        """Read width and height from PNG file header (IHDR chunk).

        PNG structure: 8-byte signature, then IHDR chunk with
        4-byte length, 4-byte type, 4-byte width, 4-byte height.

        Returns:
            Tuple of (width, height) in pixels.
        """
        with open(png_path, "rb") as f:
            # Skip 8-byte PNG signature
            f.read(8)
            # Skip 4-byte chunk length
            f.read(4)
            # Skip 4-byte chunk type (IHDR)
            f.read(4)
            # Read 4-byte width and 4-byte height (big-endian)
            width = int.from_bytes(f.read(4), "big")
            height = int.from_bytes(f.read(4), "big")
        return width, height

    @staticmethod
    def _parse_json_response(content: str) -> dict[str, Any] | None:
        """Parse JSON from Ollama response content.

        Handles cases where the model wraps JSON in markdown code blocks
        or adds preamble text.

        Returns:
            Parsed dict if successful, None otherwise.
        """
        # Strip whitespace
        content = content.strip()

        # Try direct parse first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        if "```" in content:
            # Find content between code fences
            parts = content.split("```")
            for part in parts[1::2]:  # Odd indices are inside fences
                # Strip language identifier if present
                lines = part.strip().split("\n", 1)
                if len(lines) > 1 and lines[0].strip() in ("json", ""):
                    json_str = lines[1].strip()
                else:
                    json_str = part.strip()
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue

        # Try finding JSON object in the content
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def _validate_response(parsed: dict[str, Any]) -> SemanticLabel | None:
        """Validate parsed JSON response has all required fields with valid values.

        Required fields: semantic_label, primary_material, category,
        estimated_era, condition, is_architectural.

        Returns:
            A SemanticLabel if valid, None otherwise.
        """
        required_fields = (
            "semantic_label",
            "primary_material",
            "category",
            "estimated_era",
            "condition",
            "is_architectural",
        )

        # Check all required fields exist
        for field in required_fields:
            if field not in parsed:
                return None

        # Validate field values
        semantic_label = str(parsed["semantic_label"]).strip()
        if not semantic_label:
            return None

        primary_material = str(parsed["primary_material"]).strip().lower()
        if primary_material not in VALID_MATERIALS:
            return None

        category = str(parsed["category"]).strip().lower()
        if category not in VALID_CATEGORIES:
            return None

        estimated_era = str(parsed["estimated_era"]).strip()
        if not estimated_era:
            return None

        condition = str(parsed["condition"]).strip().lower()
        if condition not in ("new", "worn", "broken"):
            return None

        is_architectural = parsed["is_architectural"]
        if not isinstance(is_architectural, bool):
            # Try to coerce string values
            if isinstance(is_architectural, str):
                is_architectural = is_architectural.lower() in ("true", "1", "yes")
            else:
                is_architectural = bool(is_architectural)

        try:
            return SemanticLabel(
                semantic_label=semantic_label,
                primary_material=primary_material,
                category=category,
                estimated_era=estimated_era,
                condition=condition,
                is_architectural=is_architectural,
            )
        except Exception:
            return None
