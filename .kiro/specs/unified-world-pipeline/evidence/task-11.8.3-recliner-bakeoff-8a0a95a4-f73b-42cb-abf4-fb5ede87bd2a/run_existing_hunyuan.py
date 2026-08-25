"""Run the already-integrated local Hunyuan3D generator for Task 11.8.3.

This is a bounded, sequential invocation against two pre-existing image lanes.
It starts no pipeline/release session and performs no model installation,
download, integration, or capability preflight.
"""
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.stages.hunyuan3d_v2_generator import Hunyuan3DV2Generator

OUT = Path(__file__).resolve().parent
LANES = [
    ("raw-crop", OUT / "lane-raw-crop-neutral.png"),
    ("qwen-historical-difference", OUT / "lane-qwen-historical-difference-neutral.png"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main() -> None:
    client = ComfyUIClient(base_url="http://127.0.0.1:8188", timeout_s=900)
    generator = Hunyuan3DV2Generator(client=client, output_dir=OUT)
    records = []
    for lane, image_path in LANES:
        started = datetime.now(timezone.utc)
        result = await generator.generate(
            object_png=image_path,
            mask_id=f"recliner-{lane}",
            steps=50,
            cfg=7.0,
            octree_resolution=384,
            stall_timeout_s=900,
        )
        ended = datetime.now(timezone.utc)
        record = {
            "lane": lane,
            "started_at_utc": started.isoformat(),
            "ended_at_utc": ended.isoformat(),
            "elapsed_seconds": (ended - started).total_seconds(),
            "input_path": str(image_path),
            "input_sha256": sha256(image_path),
            "result": None,
        }
        if result is not None:
            mesh_path = Path(result.mesh_path)
            record["result"] = {
                "mesh_path": str(mesh_path),
                "mesh_sha256": sha256(mesh_path),
                "generation_method": result.generation_method,
                "generation_time_s": result.generation_time_s,
                "face_count": result.face_count,
                "vertex_count": result.vertex_count,
                "has_texture": result.has_texture,
            }
        records.append(record)
        (OUT / "hunyuan-run-records.json").write_text(
            json.dumps(records, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
