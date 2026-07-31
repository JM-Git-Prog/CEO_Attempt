"""Unified pipeline adapter for the V14 semantic labeler.

Bridges the existing `src/photo_pipeline/stages/semantic_labeler.py`
into the unified pipeline's data model (ObjectCanon).

The UnifiedSemanticLabeler wraps the existing SemanticLabeler, translating
between unified ObjectCanon inputs and dict-based label outputs suitable
for the WorldContract, warehouse cataloging, and physics estimation.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.photo_pipeline.stages.semantic_labeler import SemanticLabeler
from src.unified_pipeline.models import ObjectCanon

logger = logging.getLogger(__name__)

# Required fields in every label response (Req 13.5)
_REQUIRED_FIELDS = (
    "semantic_label",
    "primary_material",
    "category",
    "estimated_era",
    "condition",
    "is_architectural",
)

# Valid taxonomy values for response validation (Req 13.5)
_VALID_CATEGORIES = (
    "props",
    "architecture",
    "foliage",
    "hard-surface",
    "set-dressing",
)
_VALID_MATERIALS = ("wood", "metal", "glass", "fabric", "ceramic", "plastic")
_VALID_CONDITIONS = ("new", "worn", "broken")


def _validate_label_response(response: dict[str, Any]) -> bool:
    """Validate that a label response contains all required fields with valid values.

    Checks:
    - All required fields present (Req 13.5)
    - Category matches taxonomy (Req 13.5)
    - Material is in valid set
    - Condition is in valid set
    - semantic_label and estimated_era are non-empty strings

    Args:
        response: Dict with label fields.

    Returns:
        True if valid, False otherwise.
    """
    for field in _REQUIRED_FIELDS:
        if field not in response:
            return False

    if not isinstance(response["semantic_label"], str) or not response["semantic_label"]:
        return False
    if response["primary_material"] not in _VALID_MATERIALS:
        return False
    if response["category"] not in _VALID_CATEGORIES:
        return False
    if not isinstance(response["estimated_era"], str) or not response["estimated_era"]:
        return False
    if response["condition"] not in _VALID_CONDITIONS:
        return False
    if not isinstance(response["is_architectural"], bool):
        return False

    return True


class UnifiedSemanticLabeler:
    """Adapter wrapping the V14 SemanticLabeler for the unified pipeline.

    Accepts an ObjectCanon and produces a validated dict with semantic
    label fields. Delegates to the existing Ollama-based labeler for
    vision analysis (Req 13.1, 13.2) and falls back to dimension-based
    heuristics when Ollama is unavailable (Req 13.3).

    The returned dict determines:
    - Warehouse category (Req 13.4)
    - Material density for physics estimation (Req 13.4)
    - Asset filename (Req 13.4)

    Usage:
        labeler = UnifiedSemanticLabeler()
        result = await labeler.label(object_canon)
        # result: {"semantic_label": "...", "primary_material": "...", ...}
    """

    def __init__(self, ollama_url: str = "http://localhost:11434") -> None:
        """Initialize the adapter with the underlying V14 labeler.

        Args:
            ollama_url: Base URL for the Ollama API server.
        """
        self._labeler = SemanticLabeler(ollama_url=ollama_url)

    async def label(self, object_canon: ObjectCanon) -> dict[str, Any]:
        """Label an object using Ollama vision analysis with heuristic fallback.

        Sends the Object_PNG referenced by the ObjectCanon to the Ollama
        vision model. Validates the response has all required fields
        (Req 13.5). Falls back to heuristic labeling based on image
        dimensions/mask shape on failure (Req 13.3).

        Args:
            object_canon: The approved ObjectCanon with image_path pointing
                to the isolated object RGBA PNG.

        Returns:
            Dict with keys: semantic_label, primary_material, category,
            estimated_era, condition, is_architectural.
        """
        image_path = Path(object_canon.image_path)

        try:
            # Delegate to existing V14 labeler (Req 13.1, 13.2)
            semantic_label = await self._labeler.label(image_path, timeout_s=10.0)

            # Convert SemanticLabel dataclass to dict
            response = {
                "semantic_label": semantic_label.semantic_label,
                "primary_material": semantic_label.primary_material,
                "category": semantic_label.category,
                "estimated_era": semantic_label.estimated_era,
                "condition": semantic_label.condition,
                "is_architectural": semantic_label.is_architectural,
            }

            # Validate response completeness (Req 13.5)
            if not _validate_label_response(response):
                logger.warning(
                    "Ollama response for %s failed validation, using fallback",
                    object_canon.object_name,
                )
                return self._heuristic_fallback(object_canon)

            return response

        except Exception as exc:
            # Any failure → heuristic fallback (Req 13.3)
            logger.warning(
                "Semantic labeling failed for %s: %s, using heuristic fallback",
                object_canon.object_name,
                exc,
            )
            return self._heuristic_fallback(object_canon)

    def _heuristic_fallback(self, object_canon: ObjectCanon) -> dict[str, Any]:
        """Generate a label from heuristics based on dimensions/mask shape.

        Delegates to the existing SemanticLabeler.fallback_label() using
        image dimensions read from the Object_PNG. If the image cannot
        be read, uses conservative defaults.

        Args:
            object_canon: The ObjectCanon with image_path and mask_coverage.

        Returns:
            Dict with all required label fields.
        """
        image_path = Path(object_canon.image_path)

        try:
            # Read PNG dimensions from header
            width, height = SemanticLabeler._read_png_dimensions(image_path)
            # Estimate area from mask_coverage and image dimensions
            total_pixels = width * height
            area_px = int(total_pixels * object_canon.mask_coverage) if object_canon.mask_coverage > 0 else total_pixels
        except Exception:
            # Cannot read image — use defaults
            width, height, area_px = 100, 100, 10000

        # Delegate to existing heuristic logic
        semantic_label = self._labeler.fallback_label(width, height, area_px)

        return {
            "semantic_label": semantic_label.semantic_label,
            "primary_material": semantic_label.primary_material,
            "category": semantic_label.category,
            "estimated_era": semantic_label.estimated_era,
            "condition": semantic_label.condition,
            "is_architectural": semantic_label.is_architectural,
        }
