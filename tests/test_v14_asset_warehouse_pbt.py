"""Property-based tests for Asset Warehouse.

# Feature: photo-to-real-3d-world-v14

## Property 21: Asset Warehouse Filename Uniqueness

**Validates: Requirements 7.7**

For any two distinct (semantic_label, session_id, mask_id) tuples where the
effective (slug, session_short, mask_id) triple differs, the generated filename
SHALL be different, preventing file collisions.

The filename format is: {slug}_{session_short}_{mask_id}.glb
- slug: slugified semantic_label (lowercase, hyphens, alphanumeric only)
- session_short: first 6 characters of session_id
- mask_id: the mask identifier string

Two tuples that differ only in session_id chars 7+ would produce the same
filename — this is handled by the collision resolver at save time, not by
_generate_filename alone. The property focuses on:
distinct (slug, session_short, mask_id) → distinct filename.

Also tests determinism: same inputs → same filename.
"""

from __future__ import annotations

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.asset_warehouse import AssetWarehouse


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Semantic labels: non-empty strings with printable characters that produce
# non-empty slugs after slugification
_printable_label = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    min_size=1,
    max_size=50,
)

# Session IDs: at least 6 alphanumeric characters (realistic session IDs)
_session_id = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=6,
    max_size=40,
)

# Mask IDs: short alphanumeric identifiers like "obj_01", "mask_3"
_mask_id = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)


def _slugify(label: str) -> str:
    """Mirror the slugification logic from AssetWarehouse._generate_filename."""
    import re

    slug = label.lower()
    slug = slug.replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    if not slug:
        slug = "asset"
    return slug


# ---------------------------------------------------------------------------
# Property 21: Asset Warehouse Filename Uniqueness
# ---------------------------------------------------------------------------


class TestAssetWarehouseFilenameUniquenessProperty:
    """Property 21: Asset Warehouse Filename Uniqueness.

    **Validates: Requirements 7.7**
    """

    @given(
        label1=_printable_label,
        session_id1=_session_id,
        mask_id1=_mask_id,
        label2=_printable_label,
        session_id2=_session_id,
        mask_id2=_mask_id,
    )
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_distinct_effective_tuples_produce_distinct_filenames(
        self,
        label1: str,
        session_id1: str,
        mask_id1: str,
        label2: str,
        session_id2: str,
        mask_id2: str,
    ) -> None:
        """Distinct (slug, session_short, mask_id) triples → distinct filenames.

        We assume the effective triple differs (slug OR session_short OR mask_id),
        then assert the generated filenames are different.
        """
        warehouse = AssetWarehouse()

        # Compute effective components
        slug1 = _slugify(label1)
        slug2 = _slugify(label2)
        session_short1 = session_id1[:6]
        session_short2 = session_id2[:6]

        # Only test when the effective triple is actually distinct
        assume(
            (slug1, session_short1, mask_id1) != (slug2, session_short2, mask_id2)
        )

        filename1 = warehouse._generate_filename(label1, session_id1, mask_id1)
        filename2 = warehouse._generate_filename(label2, session_id2, mask_id2)

        assert filename1 != filename2, (
            f"Filename collision detected!\n"
            f"  Input 1: label={label1!r}, session={session_id1!r}, mask={mask_id1!r}\n"
            f"  Input 2: label={label2!r}, session={session_id2!r}, mask={mask_id2!r}\n"
            f"  Slug 1={slug1!r}, Short 1={session_short1!r}\n"
            f"  Slug 2={slug2!r}, Short 2={session_short2!r}\n"
            f"  Both produced: {filename1!r}"
        )

    @given(
        label=_printable_label,
        session_id=_session_id,
        mask_id=_mask_id,
    )
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_same_inputs_produce_same_filename_deterministic(
        self,
        label: str,
        session_id: str,
        mask_id: str,
    ) -> None:
        """Same (label, session_id, mask_id) → same filename (deterministic).

        Calling _generate_filename twice with identical inputs must always
        produce the identical result.
        """
        warehouse = AssetWarehouse()

        filename_a = warehouse._generate_filename(label, session_id, mask_id)
        filename_b = warehouse._generate_filename(label, session_id, mask_id)

        assert filename_a == filename_b, (
            f"Non-deterministic filename generation!\n"
            f"  Input: label={label!r}, session={session_id!r}, mask={mask_id!r}\n"
            f"  Call 1: {filename_a!r}\n"
            f"  Call 2: {filename_b!r}"
        )

    @given(
        label=_printable_label,
        session_id=_session_id,
        mask_id=_mask_id,
    )
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_filename_ends_with_glb_extension(
        self,
        label: str,
        session_id: str,
        mask_id: str,
    ) -> None:
        """Generated filenames always end with .glb extension."""
        warehouse = AssetWarehouse()

        filename = warehouse._generate_filename(label, session_id, mask_id)

        assert filename.endswith(".glb"), (
            f"Filename does not end with .glb: {filename!r}"
        )

    @given(
        label=_printable_label,
        session_id=_session_id,
        mask_id=_mask_id,
    )
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_filename_contains_expected_structure(
        self,
        label: str,
        session_id: str,
        mask_id: str,
    ) -> None:
        """Filename follows {slug}_{session_short}_{mask_id}.glb structure."""
        warehouse = AssetWarehouse()

        filename = warehouse._generate_filename(label, session_id, mask_id)
        expected_slug = _slugify(label)
        expected_session_short = session_id[:6]

        # The filename should start with the slug
        assert filename.startswith(expected_slug + "_"), (
            f"Filename {filename!r} doesn't start with slug {expected_slug!r}_"
        )

        # The filename (without .glb) should end with the mask_id
        stem = filename[:-4]  # Strip .glb
        assert stem.endswith("_" + mask_id), (
            f"Filename stem {stem!r} doesn't end with _{mask_id!r}"
        )

        # The middle part should be the session_short
        # stem = {slug}_{session_short}_{mask_id}
        expected_full = f"{expected_slug}_{expected_session_short}_{mask_id}"
        assert stem == expected_full, (
            f"Filename structure mismatch:\n"
            f"  Expected stem: {expected_full!r}\n"
            f"  Actual stem:   {stem!r}"
        )

    @given(
        session_id=_session_id,
        mask_id=_mask_id,
    )
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_empty_slug_labels_use_fallback(
        self,
        session_id: str,
        mask_id: str,
    ) -> None:
        """Labels that slugify to empty string use 'asset' fallback slug."""
        warehouse = AssetWarehouse()

        # Labels composed entirely of special characters slugify to empty
        special_labels = ["!!!", "###", "...", "@@@", "   ", "---"]

        for label in special_labels:
            filename = warehouse._generate_filename(label, session_id, mask_id)
            expected_session_short = session_id[:6]
            expected = f"asset_{expected_session_short}_{mask_id}.glb"
            assert filename == expected, (
                f"Label {label!r} should use 'asset' fallback.\n"
                f"  Expected: {expected!r}\n"
                f"  Got:      {filename!r}"
            )
