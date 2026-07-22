"""Run Blender headlessly to assemble a scene from session data.

Usage from the pipeline:
    from src.assembler.blender_runner import assemble_blender_scene
    result = assemble_blender_scene(session_dir)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Find Blender executable
_BLENDER_PATHS = [
    os.getenv("BLENDER_PATH", ""),
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender\blender.exe",
    "blender",  # Try PATH
]

SCRIPT_PATH = Path(__file__).parent / "blender_scene.py"


def find_blender() -> str | None:
    """Find the Blender executable."""
    for path in _BLENDER_PATHS:
        if not path:
            continue
        if Path(path).exists():
            return str(path)
        # Try as a command in PATH
        found = shutil.which(path)
        if found:
            return found
    return None


def assemble_blender_scene(
    session_dir: Path,
    *,
    timeout: float = 120.0,
    render_blockout: bool = True,
    export_gltf: bool = True,
) -> dict:
    """Run Blender headlessly to build scene, render blockout, and export glTF.
    
    Returns:
        {"success": bool, "blend_path": str, "blockout_path": str, "gltf_path": str, "error": str}
    """
    blender = find_blender()
    if not blender:
        return {
            "success": False,
            "error": "Blender not found. Install from https://blender.org or set BLENDER_PATH env var.",
        }

    session_dir = Path(session_dir)
    if not (session_dir / "session.json").exists():
        return {"success": False, "error": f"No session.json in {session_dir}"}

    cmd = [
        blender,
        "--background",          # No GUI
        "--factory-startup",     # Clean state
        "--python", str(SCRIPT_PATH),
        "--",
        str(session_dir),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(session_dir.parent.parent),
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Blender timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": f"Blender executable not found at: {blender}"}

    output = {
        "success": result.returncode == 0,
        "stdout": result.stdout[-2000:] if result.stdout else "",
        "stderr": result.stderr[-1000:] if result.stderr else "",
    }

    if result.returncode == 0:
        blend_path = session_dir / "scene.blend"
        blockout_path = session_dir / "blockout_blender.png"
        gltf_path = session_dir / "scene.glb"
        output["blend_path"] = str(blend_path) if blend_path.exists() else None
        output["blockout_path"] = str(blockout_path) if blockout_path.exists() else None
        output["gltf_path"] = str(gltf_path) if gltf_path.exists() else None
    else:
        output["error"] = result.stderr[-500:] if result.stderr else "Blender exited with error"

    return output


if __name__ == "__main__":
    """Quick test: run on the most recent session."""
    import sys
    
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        output_dir = Path("output")
        sessions = sorted(
            (d for d in output_dir.iterdir() if d.is_dir() and (d / "session.json").exists()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not sessions:
            print("No sessions found")
            sys.exit(1)
        target = sessions[0]
    
    print(f"Assembling Blender scene for: {target.name}")
    result = assemble_blender_scene(target)
    print(f"Result: {result}")
