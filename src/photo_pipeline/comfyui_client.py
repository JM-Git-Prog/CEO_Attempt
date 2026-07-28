"""Async HTTP client for ComfyUI workflow submission and result retrieval.

Provides a reusable client class for all photo pipeline GPU stages that
interact with ComfyUI on localhost:8188. Handles health checks, workflow
submission, polling for completion, VRAM OOM recovery, and output retrieval.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

from src.photo_pipeline.workflows import load_workflow

logger = logging.getLogger(__name__)

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")


class ComfyUIError(Exception):
    """Base exception for ComfyUI client errors."""


class ComfyUITimeoutError(ComfyUIError):
    """Raised when a workflow exceeds its allotted execution time."""


class ComfyUIExecutionError(ComfyUIError):
    """Raised when ComfyUI reports an execution-level failure."""


class ComfyUIVRAMError(ComfyUIError):
    """Raised when ComfyUI reports a VRAM out-of-memory condition."""


class ComfyUIClient:
    """Async HTTP client for ComfyUI workflow submission and result retrieval.

    Parameters
    ----------
    base_url : str
        ComfyUI server base URL (default from COMFYUI_URL env or localhost:8188).
    timeout_s : int
        Default timeout in seconds for workflow completion polling.
    poll_interval_s : float
        Seconds between history polls while waiting for completion.
    """

    def __init__(
        self,
        base_url: str = COMFYUI_URL,
        timeout_s: int = 300,
        poll_interval_s: float = 0.75,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self._unavailable_nodes: set[str] = set()

    async def health_check(self) -> bool:
        """Check if ComfyUI is reachable by hitting /system_stats.

        Returns
        -------
        bool
            True if the server responds with HTTP 200, False otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                return response.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    def has_node(self, class_type: str) -> bool:
        """Check whether a ComfyUI node class_type is believed to be available.

        Returns False if a prior submission already failed with a
        'missing_node_type' error for this class_type.
        """
        return class_type not in self._unavailable_nodes

    def check_workflow_nodes(self, workflow: dict[str, Any]) -> str | None:
        """Scan a workflow dict for node class_types known to be unavailable.

        Parameters
        ----------
        workflow : dict
            ComfyUI workflow graph (node id → node definition mapping).

        Returns
        -------
        str | None
            The first unavailable class_type found, or None if all are available.
        """
        for node_def in workflow.values():
            if isinstance(node_def, dict):
                class_type = node_def.get("class_type")
                if class_type and class_type in self._unavailable_nodes:
                    return class_type
        return None

    async def submit_workflow(
        self,
        workflow: dict[str, Any],
        *,
        placeholders: dict[str, str] | None = None,
        client_id: str = "photo-pipeline",
        timeout_s: int | None = None,
    ) -> str:
        """Submit a workflow JSON to ComfyUI and return the prompt_id.

        Performs placeholder substitution on the serialized workflow JSON
        before submission if placeholders are provided.

        Parameters
        ----------
        workflow : dict
            ComfyUI workflow graph (node dict).
        placeholders : dict, optional
            Key-value pairs for placeholder substitution in the workflow JSON.
            Keys should match PLACEHOLDER markers in workflow templates.
        client_id : str
            Client identifier sent to ComfyUI for tracking.
        timeout_s : int, optional
            Override default timeout for this submission.

        Returns
        -------
        str
            The prompt_id assigned by ComfyUI.

        Raises
        ------
        ComfyUIError
            If ComfyUI rejects the workflow or returns no prompt_id.
        ComfyUIVRAMError
            If ComfyUI returns a VRAM OOM error (triggers retry logic).
        """
        effective_timeout = timeout_s or self.timeout_s

        # Apply placeholder substitution if provided
        if placeholders:
            workflow = self._substitute_placeholders(workflow, placeholders)

        # Fast-fail if any node class_type is already known to be missing
        missing = self.check_workflow_nodes(workflow)
        if missing:
            raise ComfyUIError(
                f"Skipped submission: node type '{missing}' is unavailable "
                f"(cached from prior missing_node_type error)"
            )

        return await self._submit_with_oom_retry(
            workflow, client_id, effective_timeout
        )

    async def wait_for_completion(
        self,
        prompt_id: str,
        timeout_s: int | None = None,
    ) -> dict[str, Any]:
        """Poll /history/{prompt_id} until workflow completes or times out.

        Parameters
        ----------
        prompt_id : str
            The prompt_id returned from submit_workflow.
        timeout_s : int, optional
            Override default timeout for polling.

        Returns
        -------
        dict
            The history entry for the completed prompt (outputs, status, etc.).

        Raises
        ------
        ComfyUITimeoutError
            If completion is not reached within the timeout.
        ComfyUIExecutionError
            If ComfyUI reports the execution as failed.
        """
        effective_timeout = timeout_s or self.timeout_s
        started = time.monotonic()

        async with httpx.AsyncClient(timeout=30.0) as client:
            while time.monotonic() - started < effective_timeout:
                await asyncio.sleep(self.poll_interval_s)
                response = await client.get(
                    f"{self.base_url}/history/{prompt_id}"
                )
                response.raise_for_status()
                entry = response.json().get(prompt_id)
                if not entry:
                    continue

                status = entry.get("status", {})

                # Check for execution error
                if status.get("status_str") == "error":
                    messages = status.get("messages", [])
                    error_text = str(messages) if messages else str(status)
                    # Detect VRAM OOM in error messages
                    if _is_oom_error(error_text):
                        raise ComfyUIVRAMError(
                            f"VRAM out of memory: {error_text[:500]}"
                        )
                    raise ComfyUIExecutionError(
                        f"ComfyUI execution failed: {error_text[:500]}"
                    )

                # Check if outputs are available (success)
                outputs = entry.get("outputs", {})
                if outputs:
                    return entry

                # Check explicit completion without outputs
                if status.get("completed"):
                    return entry

        raise ComfyUITimeoutError(
            f"ComfyUI did not complete prompt {prompt_id} within "
            f"{effective_timeout} seconds"
        )

    async def get_output_image(
        self,
        prompt_id: str,
        output_dir: Path,
        filename: str = "output.png",
        node_id: str | None = None,
    ) -> Path:
        """Retrieve an output image from a completed workflow.

        Parameters
        ----------
        prompt_id : str
            Completed prompt_id.
        output_dir : Path
            Directory to save the retrieved image.
        filename : str
            Desired output filename.
        node_id : str, optional
            Specific node to retrieve from. If None, takes the first image
            found in any output node.

        Returns
        -------
        Path
            Path to the saved output image.

        Raises
        ------
        ComfyUIError
            If no image output is found in the workflow results.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get history to find image outputs
            response = await client.get(
                f"{self.base_url}/history/{prompt_id}"
            )
            response.raise_for_status()
            entry = response.json().get(prompt_id)
            if not entry:
                raise ComfyUIError(
                    f"No history entry found for prompt {prompt_id}"
                )

            outputs = entry.get("outputs", {})
            image_info = self._find_image_output(outputs, node_id)
            if not image_info:
                raise ComfyUIError(
                    f"No image output found for prompt {prompt_id}"
                    + (f" node {node_id}" if node_id else "")
                )

            # Download the image via /view endpoint
            result = await client.get(
                f"{self.base_url}/view",
                params={
                    "filename": image_info["filename"],
                    "subfolder": image_info.get("subfolder", ""),
                    "type": image_info.get("type", "output"),
                },
            )
            result.raise_for_status()
            output_path.write_bytes(result.content)
            return output_path

    async def get_output_mesh(
        self,
        prompt_id: str,
        output_dir: Path,
        filename: str = "output.glb",
        node_id: str | None = None,
    ) -> Path:
        """Retrieve an output mesh (GLB) from a completed workflow.

        Parameters
        ----------
        prompt_id : str
            Completed prompt_id.
        output_dir : Path
            Directory to save the retrieved mesh.
        filename : str
            Desired output filename.
        node_id : str, optional
            Specific node to retrieve from. If None, takes the first mesh
            found in any output node.

        Returns
        -------
        Path
            Path to the saved output mesh.

        Raises
        ------
        ComfyUIError
            If no mesh output is found in the workflow results.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get history to find mesh outputs
            response = await client.get(
                f"{self.base_url}/history/{prompt_id}"
            )
            response.raise_for_status()
            entry = response.json().get(prompt_id)
            if not entry:
                raise ComfyUIError(
                    f"No history entry found for prompt {prompt_id}"
                )

            outputs = entry.get("outputs", {})
            mesh_info = self._find_mesh_output(outputs, node_id)
            if not mesh_info:
                raise ComfyUIError(
                    f"No mesh output found for prompt {prompt_id}"
                    + (f" node {node_id}" if node_id else "")
                )

            # Download the mesh via /view endpoint
            result = await client.get(
                f"{self.base_url}/view",
                params={
                    "filename": mesh_info["filename"],
                    "subfolder": mesh_info.get("subfolder", ""),
                    "type": mesh_info.get("type", "output"),
                },
            )
            result.raise_for_status()
            output_path.write_bytes(result.content)
            return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _submit_with_oom_retry(
        self,
        workflow: dict[str, Any],
        client_id: str,
        timeout_s: int,
    ) -> str:
        """Submit workflow with a single OOM retry.

        On VRAM OOM: calls /free to release VRAM, waits 2 seconds, retries once.
        """
        try:
            return await self._post_prompt(workflow, client_id)
        except ComfyUIVRAMError:
            logger.warning("VRAM OOM on submit — freeing memory and retrying")
            await self._free_vram()
            await asyncio.sleep(2.0)
            return await self._post_prompt(workflow, client_id)

    async def _post_prompt(
        self,
        workflow: dict[str, Any],
        client_id: str,
    ) -> str:
        """Post workflow to /prompt and return the prompt_id."""
        timeout = httpx.Timeout(30.0, read=60.0, write=30.0, pool=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            )

            if response.status_code != 200:
                error_text = response.text[:500]
                if _is_oom_error(error_text):
                    raise ComfyUIVRAMError(f"VRAM OOM on submit: {error_text}")

                # Detect missing node types and cache them for fast-fail
                if response.status_code == 400:
                    missing_type = _extract_missing_node_type(
                        error_text, response
                    )
                    if missing_type:
                        self._unavailable_nodes.add(missing_type)
                        logger.info(
                            "Cached unavailable node type: %s "
                            "(%d total cached)",
                            missing_type,
                            len(self._unavailable_nodes),
                        )

                raise ComfyUIError(
                    f"ComfyUI rejected workflow ({response.status_code}): "
                    f"{error_text}"
                )

            data = response.json()
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise ComfyUIError("ComfyUI returned no prompt_id")
            return prompt_id

    async def _free_vram(self) -> None:
        """Call /free endpoint to release VRAM for OOM recovery."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/free",
                    json={"unload_models": True, "free_memory": True},
                )
                if response.status_code == 200:
                    logger.info("VRAM freed successfully via /free endpoint")
                else:
                    logger.warning(
                        "VRAM free request returned %d", response.status_code
                    )
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Failed to call /free endpoint: %s", exc)

    def _substitute_placeholders(
        self,
        workflow: dict[str, Any],
        placeholders: dict[str, str],
    ) -> dict[str, Any]:
        """Recursively substitute PLACEHOLDER markers in workflow values.

        Walks the workflow dict/list structure and replaces string values
        that match placeholder keys with their corresponding values.
        """
        import json

        serialized = json.dumps(workflow)
        for key, value in placeholders.items():
            serialized = serialized.replace(key, value)
        return json.loads(serialized)

    def _find_image_output(
        self,
        outputs: dict[str, Any],
        node_id: str | None,
    ) -> dict[str, str] | None:
        """Find the first image output in workflow outputs."""
        if node_id and node_id in outputs:
            images = outputs[node_id].get("images", [])
            if images:
                return images[0]
            return None

        # Search all output nodes for images
        for node_outputs in outputs.values():
            images = node_outputs.get("images", [])
            if images:
                return images[0]
        return None

    def _find_mesh_output(
        self,
        outputs: dict[str, Any],
        node_id: str | None,
    ) -> dict[str, str] | None:
        """Find the first mesh/3D output in workflow outputs."""
        if node_id and node_id in outputs:
            # Check for meshes (gltf/glb files) or generic files
            for key in ("meshes", "gltffiles", "files"):
                items = outputs[node_id].get(key, [])
                if items:
                    return items[0]
            return None

        # Search all output nodes
        for node_outputs in outputs.values():
            for key in ("meshes", "gltffiles", "files"):
                items = node_outputs.get(key, [])
                if items:
                    return items[0]
        return None


def _is_oom_error(error_text: str) -> bool:
    """Detect VRAM out-of-memory conditions in error messages."""
    oom_indicators = (
        "out of memory",
        "CUDA out of memory",
        "OOM",
        "torch.cuda.OutOfMemoryError",
        "CUBLAS_STATUS_ALLOC_FAILED",
        "cuDNN error",
    )
    lower = error_text.lower()
    return any(indicator.lower() in lower for indicator in oom_indicators)


def _extract_missing_node_type(
    error_text: str, response: httpx.Response
) -> str | None:
    """Extract the missing node class_type from a ComfyUI 400 error.

    ComfyUI returns errors like:
      {"error": {"type": "missing_node_type", "message": "...",
                 "details": "...", "extra_info": {"class_type": "SAM2Segmentation"}}}
    or embeds class_type info in the message/details text.

    Returns the class_type string if found, else None.
    """
    import json
    import re

    # Try parsing the structured JSON response
    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError):
        data = None

    if isinstance(data, dict):
        error_info = data.get("error", {})
        if isinstance(error_info, dict):
            # Direct type check
            if error_info.get("type") == "missing_node_type":
                # Try extra_info.class_type first
                extra = error_info.get("extra_info", {})
                if isinstance(extra, dict) and extra.get("class_type"):
                    return extra["class_type"]
                # Try details or message for the class name
                for field in ("details", "message"):
                    text = error_info.get(field, "")
                    if text:
                        match = re.search(r"'([^']+)'", text)
                        if match:
                            return match.group(1)

        # Also check node_errors for missing types
        node_errors = data.get("node_errors", {})
        if isinstance(node_errors, dict):
            for _node_id, node_err in node_errors.items():
                if isinstance(node_err, dict):
                    class_type = node_err.get("class_type")
                    errors = node_err.get("errors", [])
                    if class_type and errors:
                        for err in errors:
                            if isinstance(err, dict) and "missing" in str(
                                err.get("message", "")
                            ).lower():
                                return class_type

    # Fallback: regex on raw text for common patterns
    if "missing_node_type" in error_text.lower():
        match = re.search(r'"class_type"\s*:\s*"([^"]+)"', error_text)
        if match:
            return match.group(1)

    return None
