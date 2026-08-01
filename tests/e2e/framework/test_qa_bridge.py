"""Unit tests for the QA bridge module.

Tests bridge methods with mocked Playwright page, error handling when
window.__qa is undefined, and JSON parsing of scene graph data.

Requirements: 7.1–7.6
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from tests.e2e.framework.qa_bridge import (
    QABridge,
    QABridgeError,
    QAHarnessUnavailableError,
    DEFAULT_EVALUATE_TIMEOUT_MS,
)


@pytest.fixture
def mock_page():
    """Create a mock Playwright page with evaluate returning QA available."""
    page = MagicMock()
    page.evaluate = AsyncMock()
    return page


@pytest.fixture
def qa_available_page(mock_page):
    """Mock page where window.__qa is available (first evaluate returns True)."""

    call_count = 0

    async def evaluate_side_effect(expression, timeout=None):
        nonlocal call_count
        call_count += 1
        # First call checks availability — return True
        if "typeof window.__qa" in expression:
            return True
        return None

    mock_page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
    return mock_page


def make_qa_page(return_value):
    """Create a mock page that returns True for availability check, then return_value."""
    page = MagicMock()

    async def evaluate_side_effect(expression, timeout=None):
        if "typeof window.__qa" in expression:
            return True
        return return_value

    page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
    return page


# ============================================================================
# Section 1: Mocked Playwright page tests — bridge methods
# ============================================================================


class TestGetObjectCount:
    """Tests for QABridge.get_object_count() — Requirement 7.3."""

    @pytest.mark.asyncio
    async def test_returns_correct_integer(self):
        page = make_qa_page(42)
        bridge = QABridge(page)
        result = await bridge.get_object_count()
        assert result == 42
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_scene(self):
        page = make_qa_page(0)
        bridge = QABridge(page)
        result = await bridge.get_object_count()
        assert result == 0

    @pytest.mark.asyncio
    async def test_calls_correct_js_expression(self):
        page = make_qa_page(5)
        bridge = QABridge(page)
        await bridge.get_object_count()
        # Second call (first is availability check) should be getObjectCount
        calls = page.evaluate.call_args_list
        assert any("getObjectCount" in str(c) for c in calls)


class TestGetObjectPosition:
    """Tests for QABridge.get_object_position() — Requirement 7.4."""

    @pytest.mark.asyncio
    async def test_returns_xyz_dict(self):
        page = make_qa_page({"x": 1.5, "y": 2.0, "z": -3.7})
        bridge = QABridge(page)
        result = await bridge.get_object_position("door_01")
        assert result == {"x": 1.5, "y": 2.0, "z": -3.7}

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_object(self):
        page = make_qa_page(None)
        bridge = QABridge(page)
        result = await bridge.get_object_position("nonexistent_object")
        assert result is None

    @pytest.mark.asyncio
    async def test_converts_values_to_float(self):
        page = make_qa_page({"x": 1, "y": 2, "z": 3})
        bridge = QABridge(page)
        result = await bridge.get_object_position("obj_01")
        assert all(isinstance(v, float) for v in result.values())

    @pytest.mark.asyncio
    async def test_passes_object_id_to_js(self):
        page = make_qa_page({"x": 0, "y": 0, "z": 0})
        bridge = QABridge(page)
        await bridge.get_object_position("my_special_object")
        calls = page.evaluate.call_args_list
        assert any("my_special_object" in str(c) for c in calls)


class TestGetLighting:
    """Tests for QABridge.get_lighting() — Requirement 7.5."""

    @pytest.mark.asyncio
    async def test_returns_list_of_lighting_objects(self):
        lights = [
            {"type": "point", "position": {"x": 0, "y": 5, "z": 0}, "color": "#FFFFFF", "intensity": 1.0},
            {"type": "directional", "position": {"x": 10, "y": 10, "z": 10}, "color": "#FFF0E0", "intensity": 0.8},
        ]
        page = make_qa_page(lights)
        bridge = QABridge(page)
        result = await bridge.get_lighting()
        assert len(result) == 2
        assert result[0]["type"] == "point"
        assert result[1]["type"] == "directional"

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_null(self):
        page = make_qa_page(None)
        bridge = QABridge(page)
        result = await bridge.get_lighting()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_lights(self):
        page = make_qa_page([])
        bridge = QABridge(page)
        result = await bridge.get_lighting()
        assert result == []


class TestTriggerInteraction:
    """Tests for QABridge.trigger_interaction() — Requirement 7.6."""

    @pytest.mark.asyncio
    async def test_returns_success_and_state_dict(self):
        interaction_result = {"success": True, "state": {"open": True, "angle": 90}}
        page = make_qa_page(interaction_result)
        bridge = QABridge(page)
        result = await bridge.trigger_interaction("door_01", "click")
        assert result["success"] is True
        assert result["state"] == {"open": True, "angle": 90}

    @pytest.mark.asyncio
    async def test_passes_object_id_and_action_to_js(self):
        page = make_qa_page({"success": True, "state": {}})
        bridge = QABridge(page)
        await bridge.trigger_interaction("box_02", "push")
        calls = page.evaluate.call_args_list
        assert any("box_02" in str(c) and "push" in str(c) for c in calls)

    @pytest.mark.asyncio
    async def test_failed_interaction_returns_success_false(self):
        interaction_result = {"success": False, "state": {"error": "object_locked"}}
        page = make_qa_page(interaction_result)
        bridge = QABridge(page)
        result = await bridge.trigger_interaction("locked_door", "click")
        assert result["success"] is False


class TestGetSceneGraph:
    """Tests for QABridge.get_scene_graph() — Requirements 7.1–7.6."""

    @pytest.mark.asyncio
    async def test_returns_list_of_scene_node_dicts(self):
        scene_graph = [
            {"objectId": "chair_01", "meshCount": 3, "position": {"x": 1, "y": 0, "z": 2}},
            {"objectId": "table_01", "meshCount": 1, "position": {"x": 0, "y": 0, "z": 0}},
        ]
        page = make_qa_page(scene_graph)
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()
        assert len(result) == 2
        assert result[0]["objectId"] == "chair_01"
        assert result[0]["meshCount"] == 3
        assert result[1]["position"] == {"x": 0, "y": 0, "z": 0}

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_null(self):
        page = make_qa_page(None)
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_empty_scene(self):
        page = make_qa_page([])
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()
        assert result == []


class TestCaptureFrame:
    """Tests for QABridge.capture_frame()."""

    @pytest.mark.asyncio
    async def test_returns_base64_string(self):
        base64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        page = make_qa_page(base64_data)
        bridge = QABridge(page)
        result = await bridge.capture_frame()
        assert result == base64_data
        assert isinstance(result, str)


class TestGetRendererInfo:
    """Tests for QABridge.get_renderer_info()."""

    @pytest.mark.asyncio
    async def test_returns_renderer_config_dict(self):
        renderer_info = {"antialias": False, "preserveDrawingBuffer": True, "seed": 42}
        page = make_qa_page(renderer_info)
        bridge = QABridge(page)
        result = await bridge.get_renderer_info()
        assert result["antialias"] is False
        assert result["preserveDrawingBuffer"] is True
        assert result["seed"] == 42


# ============================================================================
# Section 2: Error handling tests
# ============================================================================


class TestQAHarnessUnavailable:
    """Tests for error handling when window.__qa is undefined."""

    @pytest.mark.asyncio
    async def test_raises_descriptive_error_when_qa_undefined(self):
        page = MagicMock()
        # window.__qa check returns False
        page.evaluate = AsyncMock(return_value=False)
        bridge = QABridge(page)

        with pytest.raises(QAHarnessUnavailableError) as exc_info:
            await bridge.get_object_count()

        error_msg = str(exc_info.value)
        assert "window.__qa" in error_msg
        assert "?qa=1" in error_msg

    @pytest.mark.asyncio
    async def test_error_message_mentions_query_parameter(self):
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=False)
        bridge = QABridge(page)

        with pytest.raises(QAHarnessUnavailableError) as exc_info:
            await bridge.get_lighting()

        assert "?qa=1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_all_methods_raise_when_qa_unavailable(self):
        """Every bridge method should raise when window.__qa is not defined."""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=False)
        bridge = QABridge(page)

        with pytest.raises(QAHarnessUnavailableError):
            await bridge.get_object_count()
        with pytest.raises(QAHarnessUnavailableError):
            await bridge.get_object_position("obj")
        with pytest.raises(QAHarnessUnavailableError):
            await bridge.get_lighting()
        with pytest.raises(QAHarnessUnavailableError):
            await bridge.trigger_interaction("obj", "click")
        with pytest.raises(QAHarnessUnavailableError):
            await bridge.get_scene_graph()
        with pytest.raises(QAHarnessUnavailableError):
            await bridge.capture_frame()
        with pytest.raises(QAHarnessUnavailableError):
            await bridge.get_renderer_info()


class TestTimeoutHandling:
    """Tests for timeout error handling."""

    @pytest.mark.asyncio
    async def test_raises_error_on_timeout(self):
        page = MagicMock()

        call_count = 0

        async def evaluate_side_effect(expression, timeout=None):
            nonlocal call_count
            call_count += 1
            if "typeof window.__qa" in expression:
                return True
            raise TimeoutError("Timeout 10000ms exceeded")

        page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
        bridge = QABridge(page, timeout_ms=10000)

        with pytest.raises(QABridgeError) as exc_info:
            await bridge.get_object_count()

        assert "timed out" in str(exc_info.value)
        assert "10000ms" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_error_includes_timeout_value(self):
        page = MagicMock()

        async def evaluate_side_effect(expression, timeout=None):
            if "typeof window.__qa" in expression:
                return True
            raise Exception("Timeout 5000ms exceeded")

        page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
        bridge = QABridge(page, timeout_ms=5000)

        with pytest.raises(QABridgeError) as exc_info:
            await bridge.get_scene_graph()

        assert "5000ms" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_evaluate_failure_raises_bridge_error(self):
        """Non-timeout evaluate failures should also raise QABridgeError."""
        page = MagicMock()

        async def evaluate_side_effect(expression, timeout=None):
            if "typeof window.__qa" in expression:
                return True
            raise Exception("JavaScript execution context was destroyed")

        page.evaluate = AsyncMock(side_effect=evaluate_side_effect)
        bridge = QABridge(page)

        with pytest.raises(QABridgeError) as exc_info:
            await bridge.get_object_count()

        assert "evaluate failed" in str(exc_info.value)


class TestNullReturnsHandling:
    """Tests for graceful handling of null/None returns."""

    @pytest.mark.asyncio
    async def test_get_object_position_returns_none_for_nonexistent(self):
        page = make_qa_page(None)
        bridge = QABridge(page)
        result = await bridge.get_object_position("nonexistent_id_12345")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_lighting_returns_empty_list_on_null(self):
        page = make_qa_page(None)
        bridge = QABridge(page)
        result = await bridge.get_lighting()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_scene_graph_returns_empty_list_on_null(self):
        page = make_qa_page(None)
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()
        assert result == []


# ============================================================================
# Section 3: JSON parsing tests for scene graph data
# ============================================================================


class TestSceneGraphJsonParsing:
    """Tests for JSON parsing of complex scene graph data."""

    @pytest.mark.asyncio
    async def test_parses_complex_scene_graph_with_multiple_objects(self):
        """Parse a realistic scene graph with diverse object types."""
        scene_graph = [
            {
                "objectId": "sofa_01",
                "meshCount": 5,
                "position": {"x": -2.5, "y": 0.0, "z": 1.2},
            },
            {
                "objectId": "coffee_table_01",
                "meshCount": 2,
                "position": {"x": -1.0, "y": 0.0, "z": 1.5},
            },
            {
                "objectId": "lamp_floor_01",
                "meshCount": 3,
                "position": {"x": -3.5, "y": 0.0, "z": 0.5},
            },
            {
                "objectId": "bookshelf_01",
                "meshCount": 8,
                "position": {"x": 3.0, "y": 0.0, "z": -2.0},
            },
            {
                "objectId": "rug_01",
                "meshCount": 1,
                "position": {"x": 0.0, "y": 0.01, "z": 0.0},
            },
        ]
        page = make_qa_page(scene_graph)
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()

        assert len(result) == 5
        assert result[0]["objectId"] == "sofa_01"
        assert result[0]["meshCount"] == 5
        assert result[0]["position"]["x"] == -2.5
        assert result[3]["objectId"] == "bookshelf_01"
        assert result[4]["position"]["y"] == 0.01

    @pytest.mark.asyncio
    async def test_handles_empty_scene_zero_objects(self):
        """Scene graph with 0 objects should return empty list."""
        page = make_qa_page([])
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()
        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_handles_lighting_with_various_light_types(self):
        """Parse lighting data with point, directional, and spot lights."""
        lights = [
            {
                "type": "point",
                "position": {"x": 0, "y": 3.0, "z": 0},
                "color": "#FFFFFF",
                "intensity": 1.0,
            },
            {
                "type": "directional",
                "position": {"x": 5, "y": 10, "z": 5},
                "color": "#FFF8E1",
                "intensity": 0.6,
            },
            {
                "type": "spot",
                "position": {"x": -2, "y": 4, "z": 1},
                "color": "#FFE0B2",
                "intensity": 1.5,
            },
        ]
        page = make_qa_page(lights)
        bridge = QABridge(page)
        result = await bridge.get_lighting()

        assert len(result) == 3
        assert result[0]["type"] == "point"
        assert result[0]["intensity"] == 1.0
        assert result[1]["type"] == "directional"
        assert result[1]["color"] == "#FFF8E1"
        assert result[2]["type"] == "spot"
        assert result[2]["intensity"] == 1.5

    @pytest.mark.asyncio
    async def test_parses_scene_graph_with_floating_point_positions(self):
        """Ensure floating point precision is maintained through parsing."""
        scene_graph = [
            {
                "objectId": "precise_obj",
                "meshCount": 1,
                "position": {"x": 3.141592653589793, "y": -0.001, "z": 99999.99},
            },
        ]
        page = make_qa_page(scene_graph)
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()

        pos = result[0]["position"]
        assert pos["x"] == pytest.approx(3.141592653589793)
        assert pos["y"] == pytest.approx(-0.001)
        assert pos["z"] == pytest.approx(99999.99)

    @pytest.mark.asyncio
    async def test_single_object_scene_graph(self):
        """Scene with exactly one object."""
        scene_graph = [
            {
                "objectId": "floor_plane",
                "meshCount": 1,
                "position": {"x": 0, "y": 0, "z": 0},
            },
        ]
        page = make_qa_page(scene_graph)
        bridge = QABridge(page)
        result = await bridge.get_scene_graph()
        assert len(result) == 1
        assert result[0]["objectId"] == "floor_plane"


# ============================================================================
# Section 4: Bridge initialization and configuration tests
# ============================================================================


class TestBridgeConfiguration:
    """Tests for bridge initialization and configuration."""

    def test_default_timeout(self):
        page = MagicMock()
        bridge = QABridge(page)
        assert bridge.timeout_ms == DEFAULT_EVALUATE_TIMEOUT_MS

    def test_custom_timeout(self):
        page = MagicMock()
        bridge = QABridge(page, timeout_ms=5000)
        assert bridge.timeout_ms == 5000

    def test_page_property(self):
        page = MagicMock()
        bridge = QABridge(page)
        assert bridge.page is page

    @pytest.mark.asyncio
    async def test_timeout_passed_to_evaluate(self):
        page = make_qa_page(10)
        bridge = QABridge(page, timeout_ms=7500)
        await bridge.get_object_count()
        # Check that timeout was passed to evaluate calls
        for call in page.evaluate.call_args_list:
            _, kwargs = call
            assert kwargs.get("timeout") == 7500
