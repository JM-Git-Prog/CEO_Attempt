"""Focused tests for Task 11.8.4c deterministic recliner refinement support."""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import given, strategies as st

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import refine_recliner_art_bible as refinement


def test_art_bible_prompts_bind_required_appearance_and_exclusions() -> None:
    """Unit example validating the exact Task 11.8.4c cue/prompt contract.

    **Validates: Requirements 38.4, 38.5, 38.8, 38.11, 39.3, 39.5**
    """
    record = refinement.build_cues_and_prompts()
    positive = record["positive_prompt"].lower()
    negative = record["negative_prompt"].lower()
    assert record["authoritative_art_bible"]["path"] == str(refinement.ART_BIBLE_PATH)
    assert record["authoritative_art_bible"]["sha256"] == refinement.ART_BIBLE_SHA256
    for phrase in ("soft overstuffed", "worn mottled medium-brown", "conventional low rectangular recliner base", "footrest physically integrated", "left arm", "right arm"):
        assert phrase in positive
    for phrase in ("rigid thin or blocky", "pedestal base", "detached floating footrest", "pristine modern", "fused room", "melted topology", "blob-like"):
        assert phrase in negative
    assert record["authority_boundary"]["metric_plan"].startswith("sole")
    assert "appearance" in record["authority_boundary"]["art_bible_and_canon"]


def test_common_gate_order_matches_locked_task_11_8_4_order() -> None:
    """Unit edge check: human approval remains last and cannot be manufactured.

    **Validates: Requirements 39.1, 39.2, 39.3, 39.4, 39.5, 39.13, 39.14**
    """
    assert refinement.COMMON_GATE_ORDER == [
        "evidence_chain_integrity",
        "stable_uuid_binding",
        "golden_room_source_identity",
        "independent_loadability",
        "non_placeholder_geometry",
        "recognizable_recliner_silhouette_identity",
        "no_fused_scene_or_ground_sheet_geometry",
        "no_obvious_catastrophic_reconstruction_artifacts",
        "neutral_multi_angle_turntable_evidence",
        "durable_non_temporary_material_continuity",
        "no_unresolved_external_materials_or_buffers",
        "explicit_hash_bound_human_approval",
    ]


@given(
    st.dictionaries(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=64), min_size=1, max_size=12),
    st.dictionaries(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=64), min_size=1, max_size=12),
)
def test_candidate_fingerprint_is_deterministic_under_mapping_order(inputs: dict[str, str], outputs: dict[str, str]) -> None:
    """Property: hash binding is independent of insertion order.

    **Validates: Requirements 39.4, 41.3, 41.6**
    """
    expected = refinement.candidate_fingerprint(inputs, outputs)
    assert refinement.candidate_fingerprint(dict(reversed(list(inputs.items()))), dict(reversed(list(outputs.items())))) == expected
    assert len(expected) == 64
    assert all(character in "0123456789abcdef" for character in expected)
