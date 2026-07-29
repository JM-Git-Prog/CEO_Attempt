"""Property-based test for placeholder geometry selection.

**Validates: Requirements 1.5**

Property 2: Placeholder Geometry Selection
For any bounding box (width, height) and pixel area, `select_placeholder_type` SHALL return:
- "sphere" when area < 1000px
- "cylinder" when aspect_ratio (width/height) < 0.5
- "box" when aspect_ratio > 2.0 or within [0.8, 1.2]
- "box" as the default for remaining cases
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.photo_pipeline.stages.placeholder_generator import select_placeholder_type


@given(
    width=st.integers(min_value=1, max_value=10000),
    height=st.integers(min_value=1, max_value=10000),
    area=st.integers(min_value=0, max_value=10_000_000),
)
@settings(max_examples=30)
def test_placeholder_geometry_selection_property(
    width: int, height: int, area: int
) -> None:
    """**Validates: Requirements 1.5**

    For any (width, height, area), select_placeholder_type returns the correct
    geometry type based on the decision rules evaluated in priority order.
    """
    result = select_placeholder_type(width, height, area)

    # Result must always be one of the valid geometry types
    assert result in ("sphere", "cylinder", "box"), (
        f"Invalid result '{result}' for width={width}, height={height}, area={area}"
    )

    # Verify decision rules in priority order
    if area < 1000:
        assert result == "sphere", (
            f"Expected 'sphere' for area={area} < 1000, got '{result}'"
        )
    else:
        aspect_ratio = width / height
        if aspect_ratio < 0.5:
            assert result == "cylinder", (
                f"Expected 'cylinder' for aspect_ratio={aspect_ratio:.4f} < 0.5, "
                f"got '{result}'"
            )
        elif aspect_ratio > 2.0:
            assert result == "box", (
                f"Expected 'box' for aspect_ratio={aspect_ratio:.4f} > 2.0, "
                f"got '{result}'"
            )
        elif 0.8 <= aspect_ratio <= 1.2:
            assert result == "box", (
                f"Expected 'box' for aspect_ratio={aspect_ratio:.4f} in [0.8, 1.2], "
                f"got '{result}'"
            )
        else:
            # Default case: remaining aspect ratios (0.5 <= ar <= 0.8 or 1.2 < ar <= 2.0)
            assert result == "box", (
                f"Expected 'box' as default for aspect_ratio={aspect_ratio:.4f}, "
                f"got '{result}'"
            )
