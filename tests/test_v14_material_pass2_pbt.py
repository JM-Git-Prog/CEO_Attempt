"""Property-based tests for Pass 2 priority ordering.

# Feature: photo-to-real-3d-world-v14

## Property 12: Pass 2 Priority Ordering

**Validates: Requirements 5.2**

For any list of objects with different screen-space areas, the Pass 2
processing queue SHALL be ordered by area descending (largest objects
processed first).

Uses Hypothesis with custom strategies to generate:
- Lists of (object_id, area_pct) tuples with 1-20 items
- object_ids: unique strings
- area_pct: floats in (0.0, 1.0]

Verifies:
1. The returned list is ordered by area descending (comparing areas of
   adjacent items in the output against their original area values)
2. All input object IDs appear in the output (no items lost)
3. Output length equals input length
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.material_processor import MaterialProcessor


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Area percentage: positive float in (0.0, 1.0]
_area_pct = st.floats(
    min_value=1e-6, max_value=1.0, allow_nan=False, allow_infinity=False
)


@st.composite
def objects_with_unique_areas(draw: st.DrawFn) -> list[tuple[str, float]]:
    """Generate a list of (object_id, area_pct) tuples with unique IDs.

    Produces 1-20 items with unique string IDs and area values in (0.0, 1.0].
    """
    n = draw(st.integers(min_value=1, max_value=20))

    # Generate unique object IDs
    ids = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=10,
            ),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    # Generate area values for each object
    areas = draw(
        st.lists(_area_pct, min_size=n, max_size=n)
    )

    return list(zip(ids, areas))


@st.composite
def objects_with_distinct_areas(draw: st.DrawFn) -> list[tuple[str, float]]:
    """Generate objects where all areas are distinct (no ties).

    This makes the expected ordering unambiguous.
    """
    n = draw(st.integers(min_value=2, max_value=20))

    # Generate unique object IDs
    ids = draw(
        st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=10,
            ),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    # Generate distinct area values
    areas = draw(
        st.lists(
            _area_pct,
            min_size=n,
            max_size=n,
            unique=True,
        )
    )

    return list(zip(ids, areas))


# ---------------------------------------------------------------------------
# Property 12: Pass 2 Priority Ordering
# ---------------------------------------------------------------------------


class TestPass2PriorityOrdering:
    """Property 12: Pass 2 Priority Ordering.

    **Validates: Requirements 5.2**

    For any list of objects with different screen-space areas, the Pass 2
    processing queue SHALL be ordered by area descending (largest objects
    processed first).
    """

    @given(data=objects_with_distinct_areas())
    @settings(
        max_examples=500,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_queue_ordered_by_area_descending(
        self,
        data: list[tuple[str, float]],
    ) -> None:
        """Pass 2 queue is ordered by area descending (largest first)."""
        processor = MaterialProcessor()
        result = processor.get_pass2_queue(data)

        # Build a lookup from object_id to its area
        area_lookup = {obj_id: area for obj_id, area in data}

        # Verify adjacent pairs are in descending order
        for i in range(len(result) - 1):
            area_current = area_lookup[result[i]]
            area_next = area_lookup[result[i + 1]]
            assert area_current >= area_next, (
                f"Queue not in descending area order at index {i}: "
                f"{result[i]} (area={area_current}) followed by "
                f"{result[i + 1]} (area={area_next})"
            )

    @given(data=objects_with_unique_areas())
    @settings(
        max_examples=500,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_queue_preserves_all_objects(
        self,
        data: list[tuple[str, float]],
    ) -> None:
        """All input object IDs appear in the output queue."""
        processor = MaterialProcessor()
        result = processor.get_pass2_queue(data)

        input_ids = {obj_id for obj_id, _ in data}
        output_ids = set(result)

        assert input_ids == output_ids, (
            f"Object IDs mismatch.\n"
            f"  Missing from output: {input_ids - output_ids}\n"
            f"  Extra in output: {output_ids - input_ids}"
        )

    @given(data=objects_with_unique_areas())
    @settings(
        max_examples=500,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_queue_length_matches_input(
        self,
        data: list[tuple[str, float]],
    ) -> None:
        """Output queue has same length as input list."""
        processor = MaterialProcessor()
        result = processor.get_pass2_queue(data)

        assert len(result) == len(data), (
            f"Length mismatch: input has {len(data)} items, "
            f"output has {len(result)} items"
        )
