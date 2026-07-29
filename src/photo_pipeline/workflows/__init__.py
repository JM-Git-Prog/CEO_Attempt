"""ComfyUI workflow template loader.

Provides parameterized workflow JSON templates for all GPU inference stages.
Templates contain PLACEHOLDER markers that are substituted at runtime by the
ComfyUI client before submission to localhost:8188/prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_WORKFLOW_DIR = Path(__file__).parent

# Valid workflow names mapped to their JSON files
AVAILABLE_WORKFLOWS: dict[str, str] = {
    "sam_segment": "sam_segment.json",
    "flux_inpaint": "flux_inpaint.json",
    "moge2_depth": "moge2_depth.json",
    "depth_anything3": "depth_anything3.json",
    "hunyuan3d_gen": "hunyuan3d_gen.json",
    "trellis2_gen": "trellis2_gen.json",
    "unique3d_gen": "unique3d_gen.json",
    "triposr_gen": "triposr_gen.json",
    "audio_impact": "audio_impact.json",
}


def load_workflow(name: str) -> dict[str, Any]:
    """Load a ComfyUI workflow JSON template by name.

    Parameters
    ----------
    name : str
        Workflow identifier. One of: sam_segment, flux_inpaint, moge2_depth,
        hunyuan3d_gen, unique3d_gen, triposr_gen, audio_impact.

    Returns
    -------
    dict
        Parsed JSON workflow ready for placeholder substitution and submission
        to the ComfyUI /prompt endpoint.

    Raises
    ------
    ValueError
        If the workflow name is not recognized.
    FileNotFoundError
        If the workflow JSON file is missing from disk.
    """
    if name not in AVAILABLE_WORKFLOWS:
        available = ", ".join(sorted(AVAILABLE_WORKFLOWS.keys()))
        raise ValueError(
            f"Unknown workflow '{name}'. Available workflows: {available}"
        )

    workflow_path = _WORKFLOW_DIR / AVAILABLE_WORKFLOWS[name]

    if not workflow_path.exists():
        raise FileNotFoundError(
            f"Workflow template not found: {workflow_path}"
        )

    with open(workflow_path, "r", encoding="utf-8") as f:
        return json.load(f)
