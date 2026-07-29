"""Property-based test for placeholder geometry selection.

**Validates: Requirements 1.5**

Property 2: Placeholder Geometry Selection
For any bounding box (width, height) and pixel area, `select_placeholder_type` SHALL return:
- "sphere" when area < 1000px
- "cylinder" when aspect_ratio (width/height) < 0.5
- "box" when aspect_ratio > 2.0 or within [0.8, 1.2]
- "box" as the default for remaining cases
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.placeholder_generator import select_placeholder_type


# --- Strategies ---
width_st = st.integers(min_value=1, max_value=2000)
height_st = st.integers(min_value=1, max_value=2000)
area_st = st.integers(min_value=0, max_value=4_000_000)


@given(width=width_st, height=height_st, area=st.integers(min_value=0, max_value=999))
@settings(max_examples=50, deadline=None)
def test_small_area_always_sphere(width: int, height: int, area: int) -> None:
    """**Validates: Requirements 1.5**

    When area < 1000, select_placeholder_type SHALL always return "sphere"
    regardless of aspect ratio.
    """
    result = select_placeholder_type(width, height, area)
    assert result == "sphere", (
        f"Expected 'sphere' for area={area} < 1000, got '{result}' "
        f"(width={width}, height={height})"
    )


@given(width=width_st, height=height_st, area=st.integers(min_value=1000, max_value=4_000_000))
@settings(max_examples=50, deadline=None)
def test_thin_aspect_returns_cylinder(width: int, height: int, area: int) -> None:
    """**Validates: Requirements 1.5**

    When area >= 1000 and width/height < 0.5, select_placeholder_type SHALL
    always return "cylinder".
    """
    assume(width / height < 0.5)
    result = select_placeholder_type(width, height, area)
    assert result == "cylinder", (
        f"Expected 'cylinder' for aspect_ratio={width/height:.4f} < 0.5, "
        f"got '{result}' (width={width}, height={height}, area={area})"
    )


@given(width=width_st, height=height_st, area=st.integers(min_value=1000, max_value=4_000_000))
@settings(max_examples=50, deadline=None)
def test_wide_aspect_returns_box(width: int, height: int, area: int) -> None:
    """**Validates: Requirements 1.5**

    When area >= 1000 and width/height > 2.0, select_placeholder_type SHALL
    always return "box".
    """
    assume(width / height > 2.0)
    result = select_placeholder_type(width, height, area)
    assert result == "box", (
        f"Expected 'box' for aspect_ratio={width/height:.4f} > 2.0, "
        f"got '{result}' (width={width}, height={height}, area={area})"
    )


@given(width=width_st, height=height_st, area=st.integers(min_value=1000, max_value=4_000_000))
@settings(max_examples=50, deadline=None)
def test_square_aspect_returns_box(width: int, height: int, area: int) -> None:
    """**Validates: Requirements 1.5**

    When area >= 1000 and 0.8 <= width/height <= 1.2, select_placeholder_type
    SHALL always return "box".
    """
    aspect = width / height
    assume(0.8 <= aspect <= 1.2)
    result = select_placeholder_type(width, height, area)
    assert result == "box", (
        f"Expected 'box' for aspect_ratio={aspect:.4f} in [0.8, 1.2], "
        f"got '{result}' (width={width}, height={height}, area={area})"
    )


@given(width=width_st, height=height_st, area=area_st)
@settings(max_examples=50, deadline=None)
def test_result_always_valid_type(width: int, height: int, area: int) -> None:
    """**Validates: Requirements 1.5**

    For all inputs, select_placeholder_type SHALL always return one of
    ("sphere", "cylinder", "box").
    """
    result = select_placeholder_type(width, height, area)
    assert result in ("sphere", "cylinder", "box"), (
        f"Invalid result '{result}' for width={width}, height={height}, area={area}"
    )
