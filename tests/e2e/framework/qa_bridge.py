"""QA Bridge — Python ↔ window.__qa protocol for Playwright.

Wraps a Playwright page object and provides typed Python access to the
`window.__qa` JavaScript API injected by browser.py when `?qa=1` is present.

Each method:
1. Calls page.evaluate() with the corresponding window.__qa.methodName()
2. Parses the JSON response into typed Python objects
3. Handles timeout gracefully — raises QABridgeError if window.__qa is unavailable
4. Handles null/undefined returns (e.g., getObjectPosition returns None if not found)

Requirements: 7.1–7.6, 8.1–8.4
"""
from __future__ import annotations

import json
from typing import Any


# Default timeout for page.evaluate() calls (milliseconds)
DEFAULT_EVALUATE_TIMEOUT_MS = 10_000


class QABridgeError(Exception):
    """Raised when QA bridge operations fail.

    Common causes:
    - Playwright evaluate timed out (page unresponsive or heavy scene loading)
    - JavaScript expression threw an error
    - Unexpected return type from QA harness method
    """


class QAHarnessUnavailableError(QABridgeError):
    """Raised when window.__qa is not available on the page.

    This typically means the page was not loaded with the ?qa=1 query parameter.
    The QA harness is only injected by browser.py when ?qa=1 is in the URL.
    """


class QABridge:
    """Python bridge to the window.__qa QA Harness in the Three.js viewer.

    Provides typed async methods that call the corresponding window.__qa.*
    JavaScript methods via Playwright's page.evaluate(). Handles JSON
    serialization/deserialization between Python and browser JS automatically.

    The QA harness is only available when the viewer URL includes ?qa=1.
    If the harness is unavailable, methods raise QAHarnessUnavailableError
    with a descriptive message guiding the developer to fix the issue.

    Usage:
        bridge = QABridge(page, timeout_ms=10000)
        await bridge.ensure_qa_available()
        count = await bridge.get_object_count()
        position = await bridge.get_object_position("door_01")
        lights = await bridge.get_lighting()
        result = await bridge.trigger_interaction("door_01", "click")
        graph = await bridge.get_scene_graph()
        frame = await bridge.capture_frame()
        info = await bridge.get_renderer_info()

    Args:
        page: A Playwright async page object loaded with ?qa=1.
        timeout_ms: Timeout in milliseconds for page.evaluate calls.
            Default 10000 (10 seconds). Increase for scenes with heavy
            physics or interaction settling.
    """

    def __init__(self, page: Any, timeout_ms: int = DEFAULT_EVALUATE_TIMEOUT_MS) -> None:
        self._page = page
        self._timeout_ms = timeout_ms

    @property
    def page(self) -> Any:
        """The underlying Playwright page object."""
        return self._page

    @property
    def timeout_ms(self) -> int:
        """Timeout in milliseconds for evaluate calls."""
        return self._timeout_ms

    @timeout_ms.setter
    def timeout_ms(self, value: int) -> None:
        if value <= 0:
            raise ValueError("timeout_ms must be positive")
        self._timeout_ms = value

    async def ensure_qa_available(self) -> None:
        """Verify that window.__qa is present and functional.

        Call this once after page navigation to confirm the QA harness loaded.
        If window.__qa is not available, raises QAHarnessUnavailableError with
        guidance on how to fix the issue (typically: add ?qa=1 to the URL).

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If the page is unresponsive.
        """
        try:
            result = await self._page.evaluate(
                """() => {
                    if (typeof window.__qa === 'undefined') return 'missing';
                    if (typeof window.__qa !== 'object' || window.__qa === null) return 'invalid';
                    return 'ok';
                }""",
                timeout=self._timeout_ms,
            )
        except Exception as exc:
            raise QABridgeError(
                "Failed to check window.__qa availability. The page may not "
                "have loaded, or Playwright lost connection to the browser. "
                f"Underlying error: {exc}"
            ) from exc

        if result == "missing":
            raise QAHarnessUnavailableError(
                "window.__qa is not defined. The QA harness is only active "
                "when the page is loaded with the ?qa=1 URL parameter. "
                "Ensure the viewer URL includes ?qa=1 (e.g., "
                "http://localhost:8000/?v=16&qa=1)."
            )
        elif result == "invalid":
            raise QAHarnessUnavailableError(
                "window.__qa exists but is not a valid object. The QA harness "
                "may have failed to initialize. Check the browser console for "
                "JavaScript errors during viewer startup."
            )

    async def get_object_count(self) -> int:
        """Get the count of loaded 3D objects in the scene.

        Returns:
            Number of ObjectInstance meshes currently loaded in the scene.

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If evaluation fails or returns invalid data.
        """
        result = await self._evaluate("window.__qa.getObjectCount()")
        if not isinstance(result, (int, float)):
            raise QABridgeError(
                f"getObjectCount() returned unexpected type: {type(result).__name__}. "
                f"Expected a number, got: {result!r}"
            )
        return int(result)

    async def get_object_position(self, object_id: str) -> dict[str, float] | None:
        """Get the world-space position of a named object.

        Args:
            object_id: The object identifier as defined in the WorldContract.

        Returns:
            Dictionary with keys 'x', 'y', 'z' (float values in world units),
            or None if the object was not found in the scene.

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If evaluation fails or returns invalid data.
        """
        safe_id = json.dumps(object_id)  # JSON-safe string escaping
        result = await self._evaluate(
            f"window.__qa.getObjectPosition({safe_id})"
        )

        if result is None:
            return None

        if not isinstance(result, dict):
            raise QABridgeError(
                f"getObjectPosition({object_id!r}) returned unexpected type: "
                f"{type(result).__name__}. Expected object with x/y/z or null."
            )

        # Validate required keys
        for key in ("x", "y", "z"):
            if key not in result:
                raise QABridgeError(
                    f"getObjectPosition({object_id!r}) response missing '{key}' key. "
                    f"Got keys: {list(result.keys())}"
                )
            if not isinstance(result[key], (int, float)):
                raise QABridgeError(
                    f"getObjectPosition({object_id!r}) has non-numeric '{key}': "
                    f"{result[key]!r}"
                )

        return {
            "x": float(result["x"]),
            "y": float(result["y"]),
            "z": float(result["z"]),
        }

    async def get_lighting(self) -> list[dict[str, Any]]:
        """Get the current lighting configuration of the scene.

        Returns:
            List of light descriptors, each containing:
            - type (str): Light type (e.g., "directional", "point", "ambient")
            - position (dict): {x, y, z} world-space position
            - color (str): Hex color string (e.g., "#ffffff")
            - intensity (float): Light intensity value

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If evaluation fails or returns invalid data.
        """
        result = await self._evaluate("window.__qa.getLighting()")

        if result is None:
            return []

        if not isinstance(result, list):
            raise QABridgeError(
                f"getLighting() returned unexpected type: {type(result).__name__}. "
                f"Expected an array of light descriptors."
            )

        lights: list[dict[str, Any]] = []
        for i, light in enumerate(result):
            if not isinstance(light, dict):
                raise QABridgeError(
                    f"getLighting()[{i}] is not an object: {light!r}"
                )
            lights.append(light)

        return lights

    async def trigger_interaction(
        self, object_id: str, action: str
    ) -> dict[str, Any]:
        """Trigger an interaction on a named object and return the result.

        Supported actions depend on the object's WorldContract interaction
        bindings (e.g., "click", "grab", "release", "push").

        This method awaits the JavaScript Promise returned by
        triggerInteraction, which waits for physics to settle.

        Args:
            object_id: The object identifier as defined in the WorldContract.
            action: The interaction action to trigger.

        Returns:
            Dictionary with keys:
            - success (bool): Whether the interaction completed successfully.
            - state (dict): The resulting object state after interaction.

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If evaluation fails, times out, or returns invalid data.
        """
        safe_id = json.dumps(object_id)
        safe_action = json.dumps(action)
        # triggerInteraction returns a Promise — use await in the JS expression
        result = await self._evaluate_async(
            f"window.__qa.triggerInteraction({safe_id}, {safe_action})"
        )

        if not isinstance(result, dict):
            raise QABridgeError(
                f"triggerInteraction({object_id!r}, {action!r}) returned "
                f"unexpected type: {type(result).__name__}. "
                f"Expected object with success/state."
            )

        if "success" not in result:
            raise QABridgeError(
                f"triggerInteraction({object_id!r}, {action!r}) response "
                f"missing 'success' key. Got keys: {list(result.keys())}"
            )

        return result

    async def get_scene_graph(self) -> list[dict[str, Any]]:
        """Get the full scene inventory for WorldContract comparison.

        Returns:
            List of scene node descriptors, each containing:
            - objectId (str): The object identifier
            - meshCount (int): Number of meshes in the object
            - position (dict): {x, y, z} world-space position

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If evaluation fails or returns invalid data.
        """
        result = await self._evaluate("window.__qa.getSceneGraph()")

        if result is None:
            return []

        if not isinstance(result, list):
            raise QABridgeError(
                f"getSceneGraph() returned unexpected type: {type(result).__name__}. "
                f"Expected an array of scene nodes."
            )

        nodes: list[dict[str, Any]] = []
        for i, node in enumerate(result):
            if not isinstance(node, dict):
                raise QABridgeError(
                    f"getSceneGraph()[{i}] is not an object: {node!r}"
                )
            nodes.append(node)

        return nodes

    async def capture_frame(self) -> str:
        """Capture the current frame as a base64-encoded PNG.

        Requires preserveDrawingBuffer=true on the renderer (set by
        deterministic render configuration).

        Returns:
            Base64-encoded PNG string of the current frame.

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If capture fails or returns invalid data.
        """
        # captureFrame returns a Promise
        result = await self._evaluate_async("window.__qa.captureFrame()")

        if not isinstance(result, str):
            raise QABridgeError(
                f"captureFrame() returned unexpected type: {type(result).__name__}. "
                f"Expected a base64 string."
            )

        if not result:
            raise QABridgeError(
                "captureFrame() returned an empty string. The renderer may not "
                "have preserveDrawingBuffer enabled, or the canvas is empty."
            )

        return result

    async def get_renderer_info(self) -> dict[str, Any]:
        """Get current renderer configuration for determinism verification.

        Returns:
            Dictionary with keys:
            - antialias (bool): Whether antialiasing is enabled
            - preserveDrawingBuffer (bool): Whether draw buffer is preserved
            - seed (int): The fixed random seed for shader noise

        Raises:
            QAHarnessUnavailableError: If window.__qa is not available.
            QABridgeError: If evaluation fails or returns invalid data.
        """
        result = await self._evaluate("window.__qa.getRendererInfo()")

        if not isinstance(result, dict):
            raise QABridgeError(
                f"getRendererInfo() returned unexpected type: {type(result).__name__}. "
                f"Expected object with antialias/preserveDrawingBuffer/seed."
            )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _evaluate(self, js_expression: str) -> Any:
        """Execute a synchronous JavaScript expression via page.evaluate.

        Wraps the expression in a sync arrow function, checks __qa availability,
        and provides descriptive error messages on failure.

        Args:
            js_expression: The JavaScript expression to evaluate (sync).

        Returns:
            The deserialized result from the browser.

        Raises:
            QAHarnessUnavailableError: If window.__qa is unavailable.
            QABridgeError: On timeout or evaluation failure.
        """
        wrapper = f"() => {{ return {js_expression}; }}"
        return await self._run_evaluate(wrapper)

    async def _evaluate_async(self, js_expression: str) -> Any:
        """Execute an async JavaScript expression via page.evaluate.

        Wraps the expression in an async arrow function with await, checks
        __qa availability, and provides descriptive error messages on failure.

        Args:
            js_expression: The JavaScript expression to evaluate (returns Promise).

        Returns:
            The deserialized result from the browser.

        Raises:
            QAHarnessUnavailableError: If window.__qa is unavailable.
            QABridgeError: On timeout or evaluation failure.
        """
        wrapper = f"async () => {{ return await {js_expression}; }}"
        return await self._run_evaluate(wrapper)

    async def _run_evaluate(self, wrapper: str) -> Any:
        """Core evaluate implementation with __qa check and error handling.

        Args:
            wrapper: Complete JavaScript function string to evaluate.

        Returns:
            The deserialized result from the browser.

        Raises:
            QAHarnessUnavailableError: If window.__qa is unavailable.
            QABridgeError: On timeout or evaluation failure.
        """
        # First verify window.__qa is available
        try:
            qa_available = await self._page.evaluate(
                "() => typeof window.__qa !== 'undefined'",
                timeout=self._timeout_ms,
            )
        except Exception as exc:
            raise QABridgeError(
                f"Failed to check QA harness availability: {exc}. "
                f"Ensure the page is loaded and responsive."
            ) from exc

        if not qa_available:
            raise QAHarnessUnavailableError(
                "window.__qa is not available on this page. "
                "Ensure the viewer URL includes the ?qa=1 query parameter. "
                "The QA harness is only injected when ?qa=1 is present "
                "(e.g., http://localhost:8000/?v=16&qa=1)."
            )

        # Execute the actual expression
        try:
            result = await self._page.evaluate(wrapper, timeout=self._timeout_ms)
        except Exception as exc:
            error_str = str(exc).lower()

            if "timeout" in error_str:
                raise QABridgeError(
                    f"QA bridge evaluate timed out after {self._timeout_ms}ms. "
                    f"The scene may be loading, physics may be settling, or the "
                    f"operation is too slow. Consider increasing timeout_ms. "
                    f"Error: {exc}"
                ) from exc
            else:
                raise QABridgeError(
                    f"QA bridge evaluate failed: {exc}"
                ) from exc

        return result
