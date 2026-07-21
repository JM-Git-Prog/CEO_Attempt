# The Living Room — GLM 5.2 Application Research Bundle

- Generated: 2026-07-20T21:17:56.052477+00:00
- Branch: `v7_Ollamma_GLM`
- Commit: `73b5d04909296699557b7a531c12e37024fee194`
- Scope: tracked application source, entry points, dependency manifests, README, release checklist, and UI-versioning policy.
- Excluded: `.git`, `.kirograph`, MCP settings, environment files, generated output/sessions, model files, binaries, caches, and user data.

## File manifest

- `README.md` — 2770 bytes — SHA-256 `38489ab6a67a1e25e502a4868be164ff8f7ad041a68436b7ec0015e4fc0ae3f2`
- `pyproject.toml` — 673 bytes — SHA-256 `99e2e9b3c27c7db18a973f76cc6efec25712405e076b32480e52ddb80aea5b81`
- `run.py` — 182 bytes — SHA-256 `10e2887c69b2559d698cd175872813168bab8af1b5ba00a25c06c7cde6d8ba63`
- `build_demo.py` — 1862 bytes — SHA-256 `c7d5f45fe8edacf984973afc03c3af0387c2782e193293cacb613a414257a43f`
- `.kiro/release-checklist.md` — 9392 bytes — SHA-256 `05c3ce550ee17b91c61ea91119f8fe920b208ab0eff5a499bfbe83abe2ecb4a9`
- `.kiro/steering/ui-versioning.md` — 1286 bytes — SHA-256 `630811d0b02cf5b45c68fbc2b3e127a4caabb1cdd9d14e15db8ffe971ccb049f`
- `src/__init__.py` — 58 bytes — SHA-256 `d567fec9ce884ebb913d215cb73efd36020da66f778c48ef9252bea1e027e03b`
- `src/assembler/__init__.py` — 0 bytes — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/assembler/godot_project.py` — 17123 bytes — SHA-256 `4500a1fe1db009f8bcfa0941187a443002732de0270be48d06e04efd2276dfb8`
- `src/asset_factory/__init__.py` — 0 bytes — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/asset_factory/mesh_generator.py` — 3285 bytes — SHA-256 `02b7e8687b671a0cd36d45e91f6fbf1c296dcf0e142bbf68454ba22f75c5a5a5`
- `src/canon_image/__init__.py` — 0 bytes — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/canon_image/generator.py` — 24308 bytes — SHA-256 `6f6ee39f00eebad7574c37e5d555126cecf8c3974f93f6e1f179836a2e90ccc4`
- `src/floor_plan/__init__.py` — 144 bytes — SHA-256 `183f8d4476bf9c1146a18f0cec591b4ab1ab6b46aa8da585b0d59b8a1e405662`
- `src/floor_plan/builder.py` — 2751 bytes — SHA-256 `5da2e5650e8cca0e329962054e4bc4837a263a912677b790041aa61a12fac76a`
- `src/floor_plan/models.py` — 1757 bytes — SHA-256 `8bfb91c8b9badd1849cc23360bde30669425f4ec4a56622c4fba48bfb3834fc4`
- `src/floor_plan/renderer.py` — 11265 bytes — SHA-256 `95adf1bbf37378d3d90d43d4d8cf190498b3509a3a290294a8f80659af722e64`
- `src/floor_plan/validator.py` — 13388 bytes — SHA-256 `ae9ca591d184e17b647a7c03dee736c97506e5fd66b14e24e6b1f6e957fc0fc2`
- `src/models.py` — 6766 bytes — SHA-256 `ad9dba0f3074804a1ee72f74b178abe8dbd3a5c36742d4473c96bf118536e6f6`
- `src/orchestrator/__init__.py` — 0 bytes — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/orchestrator/interpreter.py` — 573 bytes — SHA-256 `a4aea6b8402bd53f354f93dfd59922bd59e9bb23db3ef4b29c518fa203feb212`
- `src/orchestrator/llm.py` — 6364 bytes — SHA-256 `c89cb2a0d3f0a198d5b73bb0b33e49534f378de22c320e2a1859f647adfef049`
- `src/orchestrator/mock_llm.py` — 10458 bytes — SHA-256 `5ed97dce4315583f28f5fd1d91b0cb644c35a8ebfe6a3a531307267cd929ff25`
- `src/orchestrator/prompts.py` — 5205 bytes — SHA-256 `692282f3c5617ccbe9326365d4ddafba46ef17b2cfc66ac755530f2803c5ff0f`
- `src/pipeline.py` — 11776 bytes — SHA-256 `02864204054b13ec15e25dc374ed2b21788196eda5c809627af1f31f85096f1d`
- `src/scene_graph/__init__.py` — 0 bytes — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/scene_graph/builder.py` — 8167 bytes — SHA-256 `438e272b8bd3c028645ab8b676e42e5161b0ebaafb058bc7147dc664ac5a964d`
- `src/scene_graph/refiner.py` — 5502 bytes — SHA-256 `03e13941454ac0da51dae2ab2afaf1f66a86dc46069241f07436786690c256cd`
- `src/web/__init__.py` — 0 bytes — SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/web/app.py` — 20004 bytes — SHA-256 `83ff65df836242b92ad0b272aa7f130cb4fa9e139e50048602b81b860b83db6f`
- `src/web/event_log.py` — 1794 bytes — SHA-256 `ca92f30ad121ed91eae32dbdc19298a412745ac4cebc924607f7519bb72f40ef`
- `src/web/templates.py` — 5057 bytes — SHA-256 `e2e9e1d24eb4a429ad7dab61b131ae80c512353c8163f6b94a9607b6e2f7e862`
- `src/workflow_provenance.py` — 9891 bytes — SHA-256 `1a0b95821979215ef81c8f3613d8b8161b697075c14282f8c912ad432685b434`
- `src/web/static/app.js` — 27645 bytes — SHA-256 `f11559d829fd63de41df16c8f2c11c93bc38a7df1b1ddfe382ac85b634978ecb`
- `src/web/static/styles.css` — 10983 bytes — SHA-256 `affc1fe69dec6fd77c6f9806c0ca9f2658a79fc3a669cf5aa0d998e7533f48de`

## Full application text

### `README.md`

```text
# The Living Room

**Describe any interior. Walk into it.**

A prototype that takes a text description of an interior space and produces a walkable 3D world with physics and lighting — as a runnable Godot 4 project.

## What This Does

```
"A 1950s diner counter with four chrome stools, warm pendant lamp, rain on the window"
    → AI interprets → generates canon image → user approves
    → Builds: architectural shell + objects with physics + designed lighting
    → Output: Complete Godot 4 project you can walk through
```

## Quick Start

```bash
pip install -e .
pip install scipy

# Run the full pipeline (generates a Godot project)
python build_demo.py

# OR run the web UI
python run.py
# Open http://localhost:8000
```

## Architecture

```
User Description
    → Orchestrator (LLM interprets → SceneConcept)
    → Canon Image Generator (FLUX/mock → photorealistic image)
    → Scene Graph Builder (spatial JSON: positions, physics, lights)
    → Asset Factory (procedural .glb meshes via trimesh)
    → Godot Assembler (complete project: physics, lighting, FPS controller)
    → Playable World
```

## What Gets Generated

| Component | Details |
|-----------|---------|
| **Room** | 7m × 5m × 3.2m with floor, ceiling, 4 walls |
| **Objects** | Counter (static), 4 stools (rigid, 8kg, toppable), pie case, mug, napkin dispenser |
| **Lighting** | Warm pendant (point, 3.5 energy, 2800K) + cool directional window light |
| **Physics** | Every object has mass, collision shape, friction. Stools topple. Mug is grabbable. |
| **Controls** | WASD move, mouse look, E to grab, walk-into to push |
| **Door** | Swinging kitchen door (rigid body, 15kg) |

## Connecting a Real LLM

```bash
export OLLAMA_URL=http://localhost:11434
export LLM_MODEL=llama3.1
```

## Connecting Real Image Generation

```bash
export COMFYUI_URL=http://localhost:8188
export COMFYUI_ENABLED=1
```

## Project Structure

```
src/
├── models.py              # Core data models
├── pipeline.py            # End-to-end orchestration
├── orchestrator/          # LLM scene interpretation
├── canon_image/           # Image generation
├── scene_graph/           # Spatial layout planning
├── asset_factory/         # 3D mesh generation
├── assembler/             # Godot project builder
└── web/                   # FastAPI chat UI
```

## Design Principles

- 100% open source stack
- Works fully offline with mock LLM (no API keys needed for demo)
- Physics-first: every object has a body, mass, and collision
- Lighting designed from the canon image, not defaulted
- Scene graph is the contract between AI and 3D builder

```

### `pyproject.toml`

```toml
[project]
name = "living-room"
version = "0.1.0"
description = "The Living Room - Describe any interior, walk into it."
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "httpx>=0.27.0",
    "pydantic>=2.9.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.9",
    "websockets>=12.0",
    "trimesh>=4.4.0",
    "numpy>=1.26.0",
    "Pillow>=10.0.0",
    "scipy>=1.12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.6.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py311"

```

### `run.py`

```python
"""Run The Living Room web server. Usage: python run.py"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.web.app:app", host="0.0.0.0", port=8000, reload=True)

```

### `build_demo.py`

```python
"""
Demo script - runs the full pipeline. Produces a Godot project from a description.
Usage: python build_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.pipeline import WorldBuilder

DEMO_DESCRIPTION = """A small 1950s diner. Chrome counter with four red stools. 
One warm pendant lamp hanging low over the counter. Checkered black and white linoleum floor.
Rain streaking the storefront window. A swinging door to the kitchen on the west wall.
Cream tile wainscoting, pressed tin ceiling. A glass pie case at the end of the counter.
Coffee mug and chrome napkin dispenser on the counter."""


async def main():
    print("=" * 60)
    print("THE LIVING ROOM - Full Pipeline Demo")
    print("=" * 60)
    print(f"\nDescription: {DEMO_DESCRIPTION.strip()[:100]}...\n")

    builder = WorldBuilder(session_id="demo_diner")
    project_path = await builder.build_full(DEMO_DESCRIPTION)

    print(f"\n{'=' * 60}\nBUILD COMPLETE\n{'=' * 60}")
    print(f"\nGodot Project: {project_path}\n")
    print("Generated files:")
    for f in sorted(project_path.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(project_path)}  ({f.stat().st_size:,} bytes)")

    print(f"\nTo run: godot --path {project_path}")
    print("Controls: WASD move, Mouse look, E grab, walk into objects to push\n")

    if builder.session.scene_graph:
        sg = builder.session.scene_graph
        print(f"Scene: {sg.room.width}m x {sg.room.depth}m x {sg.room.height}m")
        print(f"Objects: {len(sg.objects)}, Lights: {len(sg.lights)}, Doors: {len(sg.doors)}")
        for obj in sg.objects:
            print(f"  - {obj.name} ({obj.physics.body_type.value}, {obj.physics.mass_kg}kg)")


if __name__ == "__main__":
    asyncio.run(main())

```

### `.kiro/release-checklist.md`

```text
# Canonical Release Pass

Every release starts with a brand-new empty session. Never restore an old session as release evidence.

## Step 1 — Canonical prompt

```text
Create a compact rectangular 1950s American diner interior exactly 6 meters wide, 4 meters deep, and 2.8 meters high.

The approved composition must contain exactly one fixed 4.2-meter-long Formica counter centered parallel to the north wall. Give it rounded polished-chrome edge trim and a pale mint-green front.

Place exactly four individual red-vinyl-and-chrome swivel stools in a straight, evenly spaced row along the south side of the counter. Each stool must be a separate object. Leave a clear circulation aisle behind the stools.

Install one standard-width swinging kitchen door on the west wall near the northwest corner. Center one large storefront window on the south wall. Keep both openings unobstructed.

Hang exactly three individual polished-chrome pendant lights in an evenly spaced row directly above the counter. Use a glossy black-and-cream checkerboard linoleum floor, cream ceramic tile wainscoting, pale mint-green upper walls, and a lightly aged pressed-tin ceiling.

Set the scene after closing on a rainy evening. Warm amber light from the three pendants should illuminate the counter and red stools. Cool blue-gray rainy light should enter through the storefront window. The atmosphere should feel cinematic, nostalgic, intimate, realistic, and professionally photographed.

Place the canon camera at normal eye height in the southeast corner, looking diagonally northwest across all four stools toward the counter and kitchen door. Use a natural rectilinear architectural-photography lens with a 55-degree field of view.

The final camera view must clearly show the complete counter, all four separate stools, all three pendant lights, the kitchen door, and part of the rainy storefront window.

Do not add people, booths, tables, extra stools, extra lights, extra doors, extra windows, signs, readable text, or unrelated furniture. Do not treat the floor, walls, ceiling, doors, or windows as furniture objects. Preserve the requested object counts exactly.
```

## Required inspection

Inspect Brief, Plan, Blockout, Canon, World, and Compare when a world revision is needed. Validate the page, API routes, and static JavaScript. If any defect appears, record it, delete that test session, fix it, and restart from another empty session.

## Failure log

- 2026-07-20 — Headless Edge V7 responsive validation found the composer extended 18px below a 1440×500 viewport when the chat pane was persisted at its minimum width. Added a V7-only compact-height layout for intro, messages, and composer; no release session had been created.
- 2026-07-20 — User reported that resizing the V6 page could move chat outside the visible area and that the image preview pane could not be resized. Root cause: a fixed 72px header assumption, fixed 100vh workspace math, an abrupt stacked breakpoint with fixed pane heights, and no pane-resize control. V6 remains unchanged; the responsive, accessible splitter correction advances to V7.
- 2026-07-20 — User session `b68ba004` reported a V5 Canon regression: encoded-blockout partial denoising preserved geometry but retained labels, guide edges, flat surfaces, and a painted-blockout appearance. The user session is preserved. V5 remains pinned to that historical workflow; the photoreal full-generation correction advances to V6.
- 2026-07-20 — V6 session `37a43c24` passed Plan and Blockout geometry inspection, but its plan-stage snapshot omitted `interface_version` and `workflow_profile_id`. Fixed plan payload provenance fields. Session discarded before Canon and cannot serve as release evidence.

- 2026-07-20 — Session `b1437cfb` rejected at Canon: output drifted from approved blockout/material brief because the conditioned FLUX workflow sampled from an empty latent; candidate fix switched to the encoded blockout latent with partial denoising and enriched prompt details. Session discarded before release evidence.
- 2026-07-20 — Session `1d19a2a6` rejected at Plan/Blockout/Canon inspection: “center one large storefront window” was normalized to offset `-2.1m`, and the 3D Blockout omitted all opening geometry. Fixed centered-south wording recognition, minimum large-window width, and explicit door/window rendering. Session discarded before World.
- 2026-07-20 — Session `0622d48f` rejected at Canon: geometry, camera, counts, door, and window passed, but Blockout-like floor/walls/ceiling remained instead of checkerboard linoleum, cream tile, mint paint, and pressed tin. Session reserved only for denoise/prompt probing, then discarded.

## Clean pass log

- 2026-07-20 — Final release-evidence session `0500f42f` passed from a brand-new empty V7 state through Brief, Plan, Blockout, Canon, and World. Plan/Blockout passed exact 6m × 4m × 2.8m dimensions, one 4.2m counter, four stools, three pendants, one west door, one centered south window, clear aisle intent, and southeast 55-degree camera. Canon passed local vision QA with exact counts, required openings/materials/lighting, no extras, and confidence 1.0. World passed eight scene objects, three lights, one door, one window, nine meshes, Godot project, download, four immutable snapshots, two Canon manifests, V3–V7 routes, and responsive Edge checks at seven viewport sizes. The splitter passed pointer clamps, keyboard controls, reset, and fresh-session Three.js resizing. Compare was not applicable.

- 2026-07-20 — Final release-evidence session `0e7252d6` passed from a brand-new empty V6 state on the exact retained-profile-isolated code through Brief, Plan, Blockout, Canon, and World. Plan/Blockout passed exact dimensions, one 4.2m counter, four stools, three pendants, west door, centered south window, clear aisle, and southeast 55-degree camera. Canon passed local visual QA with exact counts/openings, geometry 8/10, finish quality 9/10, all specified finishes, and no defects. World passed eight scene objects, three lights, one door, one window, nine meshes, Godot project, download, page/static/API routes, and immutable manifest checks. Compare was not applicable.

- 2026-07-20 — Session `86c40bc8` passed from a brand-new empty V6 state through Brief, Plan, Blockout, Canon, and World. Plan/Blockout passed exact 6m × 4m × 2.8m dimensions, one 4.2m counter, four stools, three pendants, west door, centered south window, and the 55-degree southeast camera. Canon passed local visual QA with exact counts/openings, geometry 8/10, finish quality 9/10, every specified finish visible, and no defects. World passed scene, nine mesh, Godot project, download, retained-version page, static JavaScript, readiness, workflow API, and immutable provenance checks. Four full-state snapshots and prepared/completed generation manifests contain the pinned V6 profile, exact graph/seed, and input/output hashes. Compare was not applicable because no World revision was required.

- 2026-07-20 — Session `46452b46` passed from empty state through Brief, Plan, Blockout, Canon, and World on V4. Canon passed exact counts, geometry, camera, and finish checks. World passed scene/mesh/download routes and rendered visibly in the V4 viewer. Compare was not applicable because no World revision was required.
- 2026-07-20 — Session `71462fa9` passed from empty state through Brief, Plan, Blockout, Canon, and World on logging-enabled V5. Canon passed exact counts, geometry, camera, and finishes. World passed scene/mesh/download routes plus deterministic V5 DOM/WebGL checks. Compare was not applicable. Its log trail covers lifecycle, process, test, `awaiting_description`, `awaiting_plan_approval`, `awaiting_approval`, and `ready`.

## Workflow provenance

- Immutable profile catalog: `GET /api/workflow/profiles`.
- Per-session mutable index: `GET /api/session/{session_id}/workflow` and `output/{session_id}/workflow_manifest.json`.
- Immutable full-state records: `output/{session_id}/workflow/snapshot_NNNN_{state}.json`.
- Immutable Canon lifecycle records: prepared plus completed/failed/skipped manifests containing the pinned profile, complete inputs, exact submitted graph and random seed, provider attempts, model files, artifact hashes, dimensions, and errors.
- V3 is pinned to `v3-legacy@f982288`; V4 to `v4-reference-full@5069761`; V5 to `v5-reference-partial@964da06`; V6 to `v6-reference-full-r1`; V7 to `v7-reference-full-r1`. The unreleased V5 full-generation probe remains cataloged as `v5-reference-full-r2` for provenance but is not active.

## Revision event logs

- Append-only files: `output/logs/v3.jsonl`, `output/logs/v4.jsonl`, `output/logs/v5.jsonl`, `output/logs/v6.jsonl`, and `output/logs/v7.jsonl`.
- Events: actionable clicks, stage/work transitions, session lifecycle, session API operations, and validation tests.
- Fields: UTC timestamp, interface version, session ID when available, event type, action, and sanitized details.
- Session API records include response status, resulting pipeline state, and latest progress message.
- User-entered prompt and revision-feedback text are intentionally not logged.
- Click history before this instrumentation was installed cannot be reconstructed; logging applies from this point forward.

```

### `.kiro/steering/ui-versioning.md`

```text
# UI Versioning and Commit Policy

For every user-visible page or interface change:

1. Increment the interface query version (`?v=N`).
2. Keep the preceding version accessible and behaviorally stable.
3. Make the newest version the default when no `v` is supplied.
4. Show clear links for switching between retained versions.
5. Validate the page, relevant API routes, and static JavaScript before completion.
6. Before committing, create a brand-new empty session ID and run the canonical demo prompt from Step 1.
7. Inspect every affected stage (Brief, Plan, Blockout, Canon, World, and Compare as applicable).
8. If any bug appears, record it, fix it, discard that test session, and restart with another new empty session ID.
9. Never use a restored or previous-version session as evidence for a release pass.
10. Commit only after one complete clean zero-state pass.
11. Stage only relevant files and use commit titles in the form `feat(web): release vN interface` unless the change is strictly a fix.
12. After the commit, provide the clean-version URL, fresh session URL, exact canonical prompt, and commit hash.

Never silently overwrite the latest released interface without advancing its version. Never commit a UI version before its zero-state loop passes.

```

### `src/__init__.py`

```python
# The Living Room - Describe any interior, walk into it.

```

### `src/assembler/__init__.py`

```python

```

### `src/assembler/godot_project.py`

```python
"""
Godot Scene Assembler - Generates a complete, runnable Godot 4 project.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from src.models import DoorSpec, LightType, PhysicsBody, SceneGraph, SceneLight, SceneObject


def assemble_godot_project(scene: SceneGraph, output_dir: Path, mesh_paths: dict[str, Path]) -> Path:
    """Main entry point: assemble a complete Godot project."""
    builder = GodotProjectBuilder(scene, output_dir, mesh_paths)
    return builder.build()


def _safe_name(name: str) -> str:
    return name.replace(" ", "_").replace("-", "_").replace(".", "_")


def _hex_to_floats(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return tuple(round(int(hex_color[i:i+2], 16) / 255.0, 3) for i in (0, 2, 4))
    return (0.5, 0.5, 0.5)


class GodotProjectBuilder:
    def __init__(self, scene: SceneGraph, output_dir: Path, mesh_paths: dict[str, Path]):
        self.scene = scene
        self.project_dir = output_dir / "godot_project"
        self.mesh_paths = mesh_paths

    def build(self) -> Path:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self._copy_assets()
        self._write_project_godot()
        self._write_player_script()
        self._write_player_scene()
        self._write_main_scene()
        return self.project_dir

    def _copy_assets(self):
        assets_dir = self.project_dir / "assets" / "meshes"
        assets_dir.mkdir(parents=True, exist_ok=True)
        for obj_id, mesh_path in self.mesh_paths.items():
            if mesh_path.exists():
                shutil.copy2(mesh_path, assets_dir / mesh_path.name)

    def _write_project_godot(self):
        content = f'''config_version=5

[application]

config/name="The Living Room"
config/description="Generated world - {self.scene.name}"
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.3", "Forward Plus")

[display]

window/size/viewport_width=1280
window/size/viewport_height=720

[input]

move_forward={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":87,"physical_keycode":0,"key_label":0,"unicode":119,"location":0,"echo":false,"script":null)]
}}
move_backward={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":83,"physical_keycode":0,"key_label":0,"unicode":115,"location":0,"echo":false,"script":null)]
}}
move_left={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":65,"physical_keycode":0,"key_label":0,"unicode":97,"location":0,"echo":false,"script":null)]
}}
move_right={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":68,"physical_keycode":0,"key_label":0,"unicode":100,"location":0,"echo":false,"script":null)]
}}
interact={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":69,"physical_keycode":0,"key_label":0,"unicode":101,"location":0,"echo":false,"script":null)]
}}

[physics]

3d/default_gravity=9.8

[rendering]

renderer/rendering_method="forward_plus"
environment/defaults/default_clear_color=Color(0.1, 0.1, 0.15, 1)
'''
        (self.project_dir / "project.godot").write_text(content)

    def _write_player_scene(self):
        content = '''[gd_scene load_steps=2 format=3 uid="uid://player_scene"]

[ext_resource type="Script" path="res://player.gd" id="1"]

[sub_resource type="CapsuleShape3D" id="1"]
radius = 0.3
height = 1.8

[node name="Player" type="CharacterBody3D"]
script = ExtResource("1")

[node name="CollisionShape" type="CollisionShape3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.9, 0)
shape = SubResource("1")

[node name="Head" type="Node3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1.6, 0)

[node name="Camera3D" type="Camera3D" parent="Head"]
current = true
fov = 75.0

[node name="InteractRay" type="RayCast3D" parent="Head"]
target_position = Vector3(0, 0, -3)
enabled = true

[node name="GrabPoint" type="Marker3D" parent="Head"]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, -1.5)
'''
        (self.project_dir / "player.tscn").write_text(content)

    def _write_player_script(self):
        script = '''extends CharacterBody3D

const SPEED = 4.0
const MOUSE_SENSITIVITY = 0.003
const PUSH_FORCE = 5.0

var gravity = ProjectSettings.get_setting("physics/3d/default_gravity")
var grabbed_object: RigidBody3D = null
var head: Node3D
var interact_ray: RayCast3D
var grab_point: Marker3D

func _ready():
\thead = $Head
\tinteract_ray = $Head/InteractRay
\tgrab_point = $Head/GrabPoint
\tInput.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)

func _unhandled_input(event):
\tif event is InputEventMouseMotion:
\t\trotate_y(-event.relative.x * MOUSE_SENSITIVITY)
\t\thead.rotate_x(-event.relative.y * MOUSE_SENSITIVITY)
\t\thead.rotation.x = clamp(head.rotation.x, -PI/2, PI/2)
\tif event.is_action_pressed("interact"):
\t\t_toggle_grab()
\tif event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
\t\tInput.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)

func _toggle_grab():
\tif grabbed_object:
\t\tgrabbed_object = null
\telse:
\t\tif interact_ray.is_colliding():
\t\t\tvar collider = interact_ray.get_collider()
\t\t\tif collider is RigidBody3D:
\t\t\t\tgrabbed_object = collider

func _physics_process(delta):
\tif not is_on_floor():
\t\tvelocity.y -= gravity * delta
\tvar input_dir = Input.get_vector("move_left", "move_right", "move_forward", "move_backward")
\tvar direction = (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
\tif direction:
\t\tvelocity.x = direction.x * SPEED
\t\tvelocity.z = direction.z * SPEED
\telse:
\t\tvelocity.x = move_toward(velocity.x, 0, SPEED * delta * 10)
\t\tvelocity.z = move_toward(velocity.z, 0, SPEED * delta * 10)
\tmove_and_slide()
\tfor i in get_slide_collision_count():
\t\tvar collision = get_slide_collision(i)
\t\tvar collider = collision.get_collider()
\t\tif collider is RigidBody3D:
\t\t\tcollider.apply_central_impulse(-collision.get_normal() * PUSH_FORCE * delta)
\tif grabbed_object:
\t\tvar move_dir = grab_point.global_position - grabbed_object.global_position
\t\tgrabbed_object.linear_velocity = move_dir * 10.0
'''
        (self.project_dir / "player.gd").write_text(script)

    def _write_main_scene(self):
        """Write the main.tscn with room shell, objects, lights, player."""
        lines = []
        ext_res = []
        sub_res = []
        ext_id = 0
        sub_id = 0

        # External resources: meshes
        mesh_ext_map = {}
        for obj_id, mesh_path in self.mesh_paths.items():
            ext_id += 1
            ext_res.append(f'[ext_resource type="PackedScene" path="res://assets/meshes/{mesh_path.name}" id="{ext_id}"]')
            mesh_ext_map[obj_id] = ext_id

        # Player scene
        ext_id += 1
        player_ext_id = ext_id
        ext_res.append(f'[ext_resource type="PackedScene" path="res://player.tscn" id="{ext_id}"]')

        # Sub resources: collision shapes, materials, meshes for room shell
        h = self.scene.room.height
        w = self.scene.room.width
        d = self.scene.room.depth

        # Floor shape + mesh + material
        sub_id += 1; floor_shape = sub_id
        sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; floor_mesh = sub_id
        sub_res.append(f'[sub_resource type="BoxMesh" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; floor_mat = sub_id
        fr, fg, fb = _hex_to_floats(self.scene.room.floor_material.base_color)
        sub_res.append(f'[sub_resource type="StandardMaterial3D" id="{sub_id}"]\nalbedo_color = Color({fr}, {fg}, {fb}, 1)\nroughness = {self.scene.room.floor_material.roughness}')

        # Ceiling
        sub_id += 1; ceil_shape = sub_id
        sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; ceil_mesh = sub_id
        sub_res.append(f'[sub_resource type="BoxMesh" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; ceil_mat = sub_id
        cr, cg, cb = _hex_to_floats(self.scene.room.ceiling_material.base_color)
        sub_res.append(f'[sub_resource type="StandardMaterial3D" id="{sub_id}"]\nalbedo_color = Color({cr}, {cg}, {cb}, 1)\nroughness = {self.scene.room.ceiling_material.roughness}')

        # Wall material
        sub_id += 1; wall_mat = sub_id
        wr, wg, wb = _hex_to_floats(self.scene.room.wall_material.base_color)
        sub_res.append(f'[sub_resource type="StandardMaterial3D" id="{sub_id}"]\nalbedo_color = Color({wr}, {wg}, {wb}, 1)\nroughness = {self.scene.room.wall_material.roughness}')

        # Wall meshes and shapes
        wall_data = {}
        for wname, size in [("north", f"{w}, {h}, 0.2"), ("south", f"{w}, {h}, 0.2"),
                            ("east", f"0.2, {h}, {d}"), ("west", f"0.2, {h}, {d}")]:
            sub_id += 1
            wall_data[wname] = {"shape": sub_id}
            sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({size})')
            sub_id += 1
            wall_data[wname]["mesh"] = sub_id
            sub_res.append(f'[sub_resource type="BoxMesh" id="{sub_id}"]\nsize = Vector3({size})')

        # Object collision shapes
        obj_shapes = {}
        for obj in self.scene.objects:
            sub_id += 1
            obj_shapes[obj.id] = sub_id
            if obj.primitive_shape == "cylinder":
                r = min(obj.dimensions.x, obj.dimensions.z) / 2
                sub_res.append(f'[sub_resource type="CylinderShape3D" id="{sub_id}"]\nradius = {r}\nheight = {obj.dimensions.y}')
            else:
                sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({obj.dimensions.x}, {obj.dimensions.y}, {obj.dimensions.z})')

        # Door shapes
        door_shapes = {}
        for door in self.scene.doors:
            sub_id += 1
            door_shapes[door.id] = sub_id
            sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({door.width}, {door.height}, 0.04)')

        # Environment
        sub_id += 1; env_id = sub_id
        ar, ag, ab = _hex_to_floats(self.scene.ambient_color)
        sub_res.append(f'[sub_resource type="Environment" id="{sub_id}"]\nbackground_mode = 1\nbackground_color = Color({ar}, {ag}, {ab}, 1)\nambient_light_source = 2\nambient_light_color = Color({ar}, {ag}, {ab}, 1)\nambient_light_energy = {self.scene.ambient_energy}\ntonemap_mode = 2\nssao_enabled = true\nglow_enabled = true')

        # --- Nodes ---
        nodes = []
        nodes.append('[node name="World" type="Node3D"]')

        # Environment
        nodes.append(f'\n[node name="Environment" type="WorldEnvironment" parent="."]\nenvironment = SubResource("{env_id}")')

        # Floor
        nodes.append(f'\n[node name="Floor" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.05, 0)')
        nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="Floor"]\nmesh = SubResource("{floor_mesh}")\nsurface_material_override/0 = SubResource("{floor_mat}")')
        nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="Floor"]\nshape = SubResource("{floor_shape}")')

        # Ceiling
        nodes.append(f'\n[node name="Ceiling" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, {h + 0.05}, 0)')
        nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="Ceiling"]\nmesh = SubResource("{ceil_mesh}")\nsurface_material_override/0 = SubResource("{ceil_mat}")')
        nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="Ceiling"]\nshape = SubResource("{ceil_shape}")')

        # Walls
        half_w, half_d = w / 2, d / 2
        wall_pos = {"north": f"0, {h/2}, {half_d+0.1}", "south": f"0, {h/2}, {-(half_d+0.1)}",
                    "east": f"{half_w+0.1}, {h/2}, 0", "west": f"{-(half_w+0.1)}, {h/2}, 0"}
        for wname, pos in wall_pos.items():
            nodes.append(f'\n[node name="Wall_{wname}" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {pos})')
            nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="Wall_{wname}"]\nmesh = SubResource("{wall_data[wname]["mesh"]}")\nsurface_material_override/0 = SubResource("{wall_mat}")')
            nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="Wall_{wname}"]\nshape = SubResource("{wall_data[wname]["shape"]}")')

        # Objects
        for obj in self.scene.objects:
            body = "StaticBody3D" if obj.physics.body_type == PhysicsBody.STATIC else "RigidBody3D"
            px, pz = obj.position.x, obj.position.z
            py = obj.position.y + obj.dimensions.y / 2
            name = _safe_name(obj.name)
            ry = math.radians(obj.rotation.y)

            if abs(obj.rotation.y) > 0.1:
                c, s = math.cos(ry), math.sin(ry)
                t = f"Transform3D({c:.4f}, 0, {s:.4f}, 0, 1, 0, {-s:.4f}, 0, {c:.4f}, {px}, {py}, {pz})"
            else:
                t = f"Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {px}, {py}, {pz})"

            node_str = f'\n[node name="{name}" type="{body}" parent="."]\ntransform = {t}'
            if body == "RigidBody3D":
                node_str += f"\nmass = {obj.physics.mass_kg}"
            nodes.append(node_str)

            if obj.id in mesh_ext_map:
                nodes.append(f'\n[node name="Visual" parent="{name}" instance=ExtResource("{mesh_ext_map[obj.id]}")]')
            if obj.id in obj_shapes:
                nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="{name}"]\nshape = SubResource("{obj_shapes[obj.id]}")')

        # Doors
        for door in self.scene.doors:
            name = _safe_name("Door_" + door.id)
            py = door.height / 2
            nodes.append(f'\n[node name="{name}" type="RigidBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {door.position.x}, {py}, {door.position.z})\nmass = {door.physics.mass_kg}')
            if door.id in mesh_ext_map:
                nodes.append(f'\n[node name="Visual" parent="{name}" instance=ExtResource("{mesh_ext_map[door.id]}")]')
            if door.id in door_shapes:
                nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="{name}"]\nshape = SubResource("{door_shapes[door.id]}")')

        # Lights
        for light in self.scene.lights:
            r, g, b = _hex_to_floats(light.color)
            px, py, pz = light.position.x, light.position.y, light.position.z
            name = _safe_name(light.name)

            if light.light_type == LightType.POINT:
                nodes.append(f'\n[node name="{name}" type="OmniLight3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {px}, {py}, {pz})\nlight_color = Color({r}, {g}, {b}, 1)\nlight_energy = {light.intensity}\nomni_range = {light.range_meters}\nshadow_enabled = {"true" if light.cast_shadows else "false"}')
            elif light.light_type == LightType.DIRECTIONAL:
                nodes.append(f'\n[node name="{name}" type="DirectionalLight3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {px}, {py}, {pz})\nlight_color = Color({r}, {g}, {b}, 1)\nlight_energy = {light.intensity}\nshadow_enabled = {"true" if light.cast_shadows else "false"}')

        # Player
        nodes.append(f'\n[node name="Player" parent="." instance=ExtResource("{player_ext_id}")]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.9, {half_d - 0.5})')

        # Write file
        total = len(ext_res) + len(sub_res) + 2
        out = f'[gd_scene load_steps={total} format=3 uid="uid://main_scene"]\n\n'
        out += "\n".join(ext_res) + "\n\n"
        out += "\n\n".join(sub_res) + "\n\n"
        out += "\n".join(nodes) + "\n"
        (self.project_dir / "main.tscn").write_text(out)

```

### `src/asset_factory/__init__.py`

```python

```

### `src/asset_factory/mesh_generator.py`

```python
"""
Asset Factory - Generates 3D meshes for scene objects using trimesh.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from src.models import SceneGraph, SceneObject


def generate_all_meshes(scene: SceneGraph, output_dir: Path) -> dict[str, Path]:
    """Generate meshes for all objects in the scene graph."""
    meshes_dir = output_dir / "meshes"
    meshes_dir.mkdir(parents=True, exist_ok=True)

    mesh_paths: dict[str, Path] = {}

    for obj in scene.objects:
        mesh = _generate_object_mesh(obj)
        path = meshes_dir / f"{obj.id}.glb"
        mesh.export(str(path))
        mesh_paths[obj.id] = path

    for door in scene.doors:
        mesh = trimesh.creation.box(extents=[door.width, door.height, 0.04])
        mesh.visual = trimesh.visual.ColorVisuals(
            mesh=mesh, face_colors=np.tile([100, 80, 60, 255], (len(mesh.faces), 1))
        )
        path = meshes_dir / f"{door.id}.glb"
        mesh.export(str(path))
        mesh_paths[door.id] = path

    return mesh_paths


def _generate_object_mesh(obj: SceneObject) -> trimesh.Trimesh:
    """Generate a mesh based on the object's shape and dimensions."""
    shape = obj.primitive_shape or "box"
    dx, dy, dz = obj.dimensions.x, obj.dimensions.y, obj.dimensions.z

    if shape == "cylinder" and "stool" in obj.id:
        mesh = _generate_stool_mesh(min(dx, dz) / 2, dy)
    elif shape == "box":
        mesh = trimesh.creation.box(extents=[dx, dy, dz])
    elif shape == "cylinder":
        mesh = trimesh.creation.cylinder(radius=min(dx, dz) / 2, height=dy)
    elif shape == "sphere":
        mesh = trimesh.creation.icosphere(radius=max(dx, dy, dz) / 2)
    else:
        mesh = trimesh.creation.box(extents=[dx, dy, dz])

    color = _hex_to_rgba(obj.material.base_color)
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh, face_colors=np.tile(color, (len(mesh.faces), 1))
    )
    return mesh


def _generate_stool_mesh(seat_radius: float, height: float) -> trimesh.Trimesh:
    """Generate a diner stool: base disc + stem + seat cushion."""
    # Base
    base = trimesh.creation.cylinder(radius=seat_radius * 0.8, height=0.03)
    base.apply_translation([0, 0.015, 0])
    base.visual = trimesh.visual.ColorVisuals(
        mesh=base, face_colors=np.tile([180, 180, 180, 255], (len(base.faces), 1))
    )
    # Stem
    stem = trimesh.creation.cylinder(radius=0.025, height=height - 0.1)
    stem.apply_translation([0, (height - 0.1) / 2 + 0.03, 0])
    stem.visual = trimesh.visual.ColorVisuals(
        mesh=stem, face_colors=np.tile([190, 190, 190, 255], (len(stem.faces), 1))
    )
    # Seat
    seat = trimesh.creation.cylinder(radius=seat_radius, height=0.07)
    seat.apply_translation([0, height - 0.035, 0])
    seat.visual = trimesh.visual.ColorVisuals(
        mesh=seat, face_colors=np.tile([192, 57, 43, 255], (len(seat.faces), 1))
    )
    return trimesh.util.concatenate([base, stem, seat])


def _hex_to_rgba(hex_color: str) -> list[int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return [int(hex_color[i:i+2], 16) for i in (0, 2, 4)] + [255]
    return [128, 128, 128, 255]

```

### `src/canon_image/__init__.py`

```python

```

### `src/canon_image/generator.py`

```python
"""Canon image generation through local ComfyUI, API fallback, or mock mode."""

from __future__ import annotations

import asyncio
import base64
import os
import random
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from src.models import SceneConcept
from src.workflow_provenance import (
    artifact_metadata,
    profile_by_id,
    profile_for,
    write_generation_manifest,
)

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")
COMFYUI_ENABLED = os.getenv("COMFYUI_ENABLED", "1").lower() in {"1", "true", "yes"}
COMFYUI_TIMEOUT = int(os.getenv("COMFYUI_TIMEOUT", "300"))
IMAGE_API_URL = os.getenv("IMAGE_API_URL", "").rstrip("/")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

FLUX_MODEL = "flux-2-klein-base-4b-fp8.safetensors"
FLUX_CLIP = "qwen_3_4b.safetensors"
FLUX_VAE = "flux2-vae.safetensors"
_LAST_PROVIDER: dict[str, str] = {}


@dataclass(frozen=True)
class CanonGenerationResult:
    image_path: Path
    provider: str
    manifests: tuple[Path, ...]


def get_image_provider(session_id: str) -> str:
    return _LAST_PROVIDER.get(session_id, "pending")


def _profile_from_context(workflow_context: dict | None) -> dict:
    context = workflow_context or {}
    if context.get("workflow_profile"):
        profile = profile_by_id(context["workflow_profile"]["id"])
        if context["workflow_profile"] != profile:
            raise ValueError("Workflow context profile differs from its immutable contract")
    elif context.get("workflow_profile_id"):
        profile = profile_by_id(context["workflow_profile_id"])
    else:
        profile = profile_for(int(context.get("interface_version", 6)))
    if context.get("workflow_profile_id") not in {None, "", profile["id"]}:
        raise ValueError("Workflow profile ID does not match the pinned profile")
    return profile


def _generation_prompt(
    concept: SceneConcept, profile: dict, *, mode: str = "conditioned"
) -> str:
    canon = profile["stages"]["canon"]
    policy = canon.get("base_prompt", canon["prompt"]) if mode == "base" else canon["prompt"]
    if policy == "concept.image_prompt":
        return concept.image_prompt
    if policy == "enriched_concept_and_plan":
        if profile["id"] == "v5-reference-partial@964da06":
            return (
                "MANDATORY VISIBLE FINISH TRANSFORMATION: apply every specified floor, wall, "
                "ceiling, furniture, and fixture material; do not retain gray blockout surfaces. "
                f"{concept.image_prompt} Architecture and finishes: {concept.architecture_notes}. "
                f"Required visible objects: {'; '.join(concept.key_objects)}. "
                f"Exact palette: {concept.palette}. Lighting: {concept.lighting_notes}. "
                "Preserve every stated count exactly."
            )
        return (
            "MANDATORY VISIBLE FINISH TRANSFORMATION: replace every blockout surface with the "
            "specified finished material; render a polished photorealistic interior, never a "
            "colored block model. "
            f"{concept.image_prompt} Architecture and finishes: {concept.architecture_notes}. "
            f"Required visible objects: {'; '.join(concept.key_objects)}. "
            f"Exact palette: {concept.palette}. Lighting: {concept.lighting_notes}. "
            "Preserve every stated count exactly. Remove all blockout labels, guide lines, "
            "debug edges, flat shading, and placeholder geometry from the final photograph."
        )
    raise ValueError(f"Unsupported Canon prompt policy: {policy}")


def _generation_manifest(
    concept: SceneConcept,
    session_id: str,
    prompt: str,
    workflow_context: dict | None,
    workflow: dict | None,
    blockout_path: Path | None = None,
    uploaded_image_name: str | None = None,
) -> dict:
    context = workflow_context or {}
    profile = _profile_from_context(context)
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "prepared",
        "session_id": session_id,
        "interface_version": profile["interface_version"],
        "workflow_profile": profile,
        "workflow_profile_id": profile["id"],
        "models": {
            "diffusion": FLUX_MODEL,
            "text_encoder": FLUX_CLIP,
            "vae": FLUX_VAE,
        },
        "inputs": {
            "user_description": context.get("user_description", ""),
            "scene_concept": concept,
            "floor_plan": context.get("floor_plan"),
            "plan_revision": context.get("plan_revision"),
            "generation_prompt": prompt,
            "blockout": artifact_metadata(blockout_path) if blockout_path else None,
            "uploaded_image_name": uploaded_image_name,
        },
        "workflow_graph": workflow,
        "provider_attempts": [],
        "output": None,
    }


def _save_generation(
    output_dir: Path, attempt: int, mode: str, manifest: dict
) -> Path:
    return write_generation_manifest(output_dir, attempt, mode, manifest)


async def check_comfyui() -> dict:
    """Report whether the exact FLUX.2 stack required by the app is available."""
    if not COMFYUI_ENABLED:
        return {"ready": False, "enabled": False, "reason": "disabled"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            stats, models, encoders, vaes = await asyncio.gather(
                client.get(f"{COMFYUI_URL}/system_stats"),
                client.get(f"{COMFYUI_URL}/models/diffusion_models"),
                client.get(f"{COMFYUI_URL}/models/text_encoders"),
                client.get(f"{COMFYUI_URL}/models/vae"),
            )
        for response in (stats, models, encoders, vaes):
            response.raise_for_status()
        missing = [name for name, available in (
            (FLUX_MODEL, models.json()), (FLUX_CLIP, encoders.json()), (FLUX_VAE, vaes.json())
        ) if name not in available]
        device = (stats.json().get("devices") or [{}])[0].get("name", "unknown GPU")
        return {"ready": not missing, "enabled": True, "model": "FLUX.2 Klein 4B FP8", "device": device, "missing": missing}
    except Exception as exc:
        return {"ready": False, "enabled": True, "reason": str(exc)}


def _generate_mock(prompt: str, output_path: Path) -> Path:
    """Create an unmistakably labelled fallback image."""
    width, height = 1024, 768
    image = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        tone = int(18 + 28 * y / height)
        draw.line((0, y, width, y), fill=(tone, tone + 4, tone + 12))
    floor_y = 500
    for y in range(floor_y, height, 48):
        for x in range(0, width, 48):
            color = "#d0cbc0" if ((x // 48 + y // 48) % 2) else "#25262a"
            draw.rectangle((x, y, x + 48, y + 48), fill=color)
    draw.rectangle((120, 360, 900, 510), fill="#594c3c", outline="#d4b78d", width=4)
    for x in (260, 410, 560, 710):
        draw.ellipse((x - 30, 455, x + 30, 485), fill="#b93c36")
        draw.line((x, 480, x, 620), fill="#c4c7ca", width=6)
    draw.rectangle((24, 22, 235, 62), fill="#a03d3d")
    draw.text((38, 34), "MOCK FALLBACK", fill="white")
    draw.text((24, 82), prompt[:145], fill="#c4cad4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")
    return output_path


def _flux_workflow(prompt: str) -> dict:
    positive = (
        f"{prompt}. Photorealistic interior architectural photography, coherent room layout, "
        "eye-level rectilinear lens, realistic materials, physically plausible designed lighting, "
        "clear furniture silhouettes, no people."
    )
    negative = "panorama, 360 view, equirectangular, fisheye, warped walls, text, watermark, blurry, low quality"
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 1024, "height": 768, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": secrets.randbits(63), "steps": 20, "cfg": 5.0, "sampler_name": "euler", "scheduler": "simple", "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "living_room/canon"}},
    }


async def generate_canon_image(
    concept: SceneConcept,
    session_id: str,
    attempt: int = 1,
    workflow_context: dict | None = None,
) -> CanonGenerationResult:
    """Generate a text-guided Canon and retain immutable lifecycle manifests."""
    output_path = OUTPUT_DIR / session_id / f"canon_v{attempt}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = _profile_from_context(workflow_context)
    prompt = _generation_prompt(concept, profile, mode="base")
    mock_only = profile["stages"]["canon"].get("provider_policy") == "mock_only"
    workflow = None if mock_only else _flux_workflow(prompt)
    manifest = _generation_manifest(
        concept, session_id, prompt, workflow_context, workflow
    )
    manifests = [
        _save_generation(output_path.parent, attempt, "base_prepared", manifest)
    ]

    if COMFYUI_ENABLED and not mock_only:
        try:
            result = await _generate_with_comfyui(
                prompt, output_path, session_id, workflow
            )
            provider = "FLUX.2 Klein · ComfyUI"
            _LAST_PROVIDER[session_id] = provider
            manifest["provider_attempts"].append(
                {"provider": provider, "status": "completed"}
            )
            manifest.update(
                status="completed",
                finalized_at=datetime.now(timezone.utc).isoformat(),
                output=artifact_metadata(result),
            )
            manifests.append(
                _save_generation(output_path.parent, attempt, "base_completed", manifest)
            )
            return CanonGenerationResult(result, provider, tuple(manifests))
        except Exception as exc:
            manifest["provider_attempts"].append(
                {"provider": "ComfyUI", "status": "failed", "error": str(exc)}
            )
            print(f"ComfyUI generation failed: {exc}")
    elif not mock_only:
        manifest["provider_attempts"].append(
            {"provider": "ComfyUI", "status": "skipped", "reason": "disabled"}
        )

    if IMAGE_API_URL and not mock_only:
        try:
            result = await _generate_with_api(prompt, output_path)
            provider = "Image API"
            _LAST_PROVIDER[session_id] = provider
            manifest["provider_attempts"].append(
                {"provider": provider, "status": "completed"}
            )
            manifest.update(
                status="completed",
                finalized_at=datetime.now(timezone.utc).isoformat(),
                output=artifact_metadata(result),
            )
            manifests.append(
                _save_generation(output_path.parent, attempt, "base_completed", manifest)
            )
            return CanonGenerationResult(result, provider, tuple(manifests))
        except Exception as exc:
            manifest["provider_attempts"].append(
                {"provider": "Image API", "status": "failed", "error": str(exc)}
            )
            print(f"Image API generation failed: {exc}")

    provider = "Mock fallback"
    _LAST_PROVIDER[session_id] = provider
    result = _generate_mock(prompt, output_path)
    manifest["provider_attempts"].append(
        {"provider": provider, "status": "completed"}
    )
    manifest.update(
        status="completed",
        finalized_at=datetime.now(timezone.utc).isoformat(),
        output=artifact_metadata(result),
    )
    manifests.append(
        _save_generation(output_path.parent, attempt, "base_completed", manifest)
    )
    return CanonGenerationResult(result, provider, tuple(manifests))


async def _generate_with_comfyui(
    prompt: str,
    output_path: Path,
    session_id: str,
    workflow: dict | None = None,
) -> Path:
    submitted_workflow = workflow or _flux_workflow(prompt)
    timeout = httpx.Timeout(30, read=COMFYUI_TIMEOUT, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await _run_comfy_workflow(
            client, submitted_workflow, output_path, session_id
        )


async def _generate_with_api(prompt: str, output_path: Path) -> Path:
    headers = {"Authorization": f"Bearer {IMAGE_API_KEY}"} if IMAGE_API_KEY else {}
    async with httpx.AsyncClient(timeout=COMFYUI_TIMEOUT) as client:
        response = await client.post(f"{IMAGE_API_URL}/images/generations", headers=headers, json={"prompt": prompt, "n": 1, "size": "1024x768"})
        response.raise_for_status()
        item = response.json()["data"][0]
        if item.get("b64_json"):
            output_path.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            image_response = await client.get(item["url"])
            image_response.raise_for_status()
            output_path.write_bytes(image_response.content)
        else:
            raise RuntimeError("Image API returned no image data")
    return output_path


def _conditioned_flux_workflow(
    prompt: str, image_name: str, profile: dict
) -> dict:
    """Build the exact profile-pinned FLUX.2 reference graph."""
    positive = (
        f"{prompt}. Transform the supplied blockout into a photorealistic interior photograph. "
        "STRICTLY preserve camera position, lens perspective, room proportions, wall openings, "
        "object count, placement, scale, and silhouettes. Change only materials, textures, "
        "lighting, atmosphere, and rendering quality. No people."
    )
    negative = (
        "changed layout, changed camera, moved furniture, added furniture, missing furniture, "
        "warped walls, fisheye, panorama, text, watermark, illustration, low quality"
    )
    if profile["interface_version"] >= 6 or profile["id"] == "v5-reference-full-r2":
        negative = (
            "changed layout, changed camera, moved furniture, added furniture, missing furniture, "
            "warped walls, fisheye, panorama, text, watermark, labels, guide lines, debug edges, "
            "blockout render, flat shading, placeholder materials, illustration, low quality"
        )
    canon = profile["stages"]["canon"]
    latent_mode = canon.get("latent")
    sigma_schedule = canon.get("sigma_schedule")
    latent_input = ["11", 0] if latent_mode == "empty" else ["7", 0]
    sigma_input = ["12", 0]
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "megapixels": 0.8, "resolution_steps": 16}},
        "6": {"class_type": "GetImageSize", "inputs": {"image": ["5", 0]}},
        "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "9": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["8", 0], "latent": ["7", 0]}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "12": {"class_type": "Flux2Scheduler", "inputs": {"steps": 20, "width": ["6", 0], "height": ["6", 1]}},
        "13": {"class_type": "RandomNoise", "inputs": {"noise_seed": secrets.randbits(63)}},
        "14": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "15": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["9", 0], "negative": ["10", 0], "cfg": 3.5}},
        "16": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["13", 0], "guider": ["15", 0], "sampler": ["14", 0], "sigmas": sigma_input, "latent_image": latent_input}},
        "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 1], "vae": ["3", 0]}},
        "18": {"class_type": "SaveImage", "inputs": {"images": ["17", 0], "filename_prefix": "living_room/conditioned_canon"}},
    }
    if latent_mode == "empty":
        workflow["11"] = {
            "class_type": "EmptyFlux2LatentImage",
            "inputs": {"width": ["6", 0], "height": ["6", 1], "batch_size": 1},
        }
    elif latent_mode != "encoded_blockout":
        raise ValueError(f"Unsupported conditioned latent mode: {latent_mode}")
    if sigma_schedule == "partial_after_step_4":
        workflow["19"] = {
            "class_type": "SplitSigmas",
            "inputs": {"sigmas": ["12", 0], "step": 4},
        }
        workflow["16"]["inputs"]["sigmas"] = ["19", 1]
    elif sigma_schedule != "full":
        raise ValueError(f"Unsupported sigma schedule: {sigma_schedule}")
    return workflow


async def generate_conditioned_canon(
    concept: SceneConcept,
    blockout_path: Path,
    session_id: str,
    attempt: int = 1,
    workflow_context: dict | None = None,
) -> CanonGenerationResult:
    """Generate a profile-pinned Canon from the approved camera blockout."""
    profile = _profile_from_context(workflow_context)
    canon = profile["stages"]["canon"]
    if canon.get("conditioning") == "none":
        return await generate_canon_image(
            concept, session_id, attempt, workflow_context=workflow_context
        )

    output_path = OUTPUT_DIR / session_id / f"canon_v{attempt}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = _generation_prompt(concept, profile)
    manifest = _generation_manifest(
        concept,
        session_id,
        prompt,
        workflow_context,
        None,
        blockout_path=blockout_path,
    )
    manifests: list[Path] = []

    if COMFYUI_ENABLED:
        try:
            timeout = httpx.Timeout(30, read=COMFYUI_TIMEOUT, write=30, pool=30)
            async with httpx.AsyncClient(timeout=timeout) as client:
                with blockout_path.open("rb") as image_file:
                    upload = await client.post(
                        f"{COMFYUI_URL}/upload/image",
                        files={"image": (blockout_path.name, image_file, "image/png")},
                        data={"overwrite": "true"},
                    )
                upload.raise_for_status()
                uploaded = upload.json()
                image_name = "/".join(
                    part
                    for part in (
                        uploaded.get("subfolder", ""),
                        uploaded.get("name", blockout_path.name),
                    )
                    if part
                )
                workflow = _conditioned_flux_workflow(prompt, image_name, profile)
                manifest["inputs"]["uploaded_image_name"] = image_name
                manifest["workflow_graph"] = workflow
                manifests.append(
                    _save_generation(
                        output_path.parent, attempt, "conditioned_prepared", manifest
                    )
                )
                result = await _run_comfy_workflow(
                    client, workflow, output_path, session_id
                )
            provider = "FLUX.2 Klein · blockout conditioned"
            _LAST_PROVIDER[session_id] = provider
            manifest["provider_attempts"].append(
                {"provider": provider, "status": "completed"}
            )
            manifest.update(
                status="completed",
                finalized_at=datetime.now(timezone.utc).isoformat(),
                output=artifact_metadata(result),
            )
            manifests.append(
                _save_generation(
                    output_path.parent, attempt, "conditioned_completed", manifest
                )
            )
            return CanonGenerationResult(result, provider, tuple(manifests))
        except Exception as exc:
            manifest["provider_attempts"].append(
                {"provider": "ComfyUI conditioned", "status": "failed", "error": str(exc)}
            )
            manifest.update(
                status="failed", finalized_at=datetime.now(timezone.utc).isoformat()
            )
            manifests.append(
                _save_generation(
                    output_path.parent, attempt, "conditioned_failed", manifest
                )
            )
            print(f"Conditioned ComfyUI generation failed: {exc}")
    else:
        manifest["provider_attempts"].append(
            {"provider": "ComfyUI conditioned", "status": "skipped", "reason": "disabled"}
        )
        manifest.update(
            status="skipped", finalized_at=datetime.now(timezone.utc).isoformat()
        )
        manifests.append(
            _save_generation(output_path.parent, attempt, "conditioned_skipped", manifest)
        )

    fallback = await generate_canon_image(
        concept, session_id, attempt, workflow_context=workflow_context
    )
    return CanonGenerationResult(
        fallback.image_path,
        fallback.provider,
        tuple(manifests) + fallback.manifests,
    )


async def _run_comfy_workflow(
    client: httpx.AsyncClient,
    workflow: dict,
    output_path: Path,
    session_id: str,
) -> Path:
    response = await client.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow, "client_id": f"living-room-{session_id}"},
    )
    if response.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow ({response.status_code}): {response.text[:500]}")
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI returned no prompt id")
    started = time.monotonic()
    while time.monotonic() - started < COMFYUI_TIMEOUT:
        await asyncio.sleep(0.75)
        history = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
        history.raise_for_status()
        entry = history.json().get(prompt_id)
        if not entry:
            continue
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise RuntimeError(f"ComfyUI execution failed: {status}")
        for output in entry.get("outputs", {}).values():
            for image in output.get("images", []):
                result = await client.get(f"{COMFYUI_URL}/view", params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                result.raise_for_status()
                output_path.write_bytes(result.content)
                return output_path
        if status.get("completed"):
            raise RuntimeError("ComfyUI completed without an image")
    raise TimeoutError(f"ComfyUI did not finish within {COMFYUI_TIMEOUT} seconds")

```

### `src/floor_plan/__init__.py`

```python
"""Authoritative floor-plan planning and deterministic rendering."""

from src.floor_plan.models import FloorPlan

__all__ = ["FloorPlan"]

```

### `src/floor_plan/builder.py`

```python
"""Generate a metric floor plan with the existing local orchestration LLM."""

from __future__ import annotations

import json

from src.floor_plan.models import FloorPlan
from src.floor_plan.validator import normalize_floor_plan
from src.models import SceneConcept
from src.orchestrator.llm import generate_json

PLAN_SYSTEM = """You are an expert interior space planner. Return one valid JSON object only.
The plan is authoritative geometry for a single rectangular room. Coordinates use X/Z in
meters with room center at 0,0; north is +Z. Include significant furniture, built-ins, doors,
windows, and a deliberate eye-level camera. Keep at least 0.8m circulation where practical.
Every item ID must be stable snake_case. Create one item per physical instance: four stools
means stool_1 through stool_4, never one combined stool footprint. Items contain furniture,
built-ins, and freestanding fixtures only. Put doors/windows only in openings; never put floors,
walls, ceilings, doors, or windows in items. Compact rooms should normally be 4-8m wide and
3-6m deep unless the user requests larger. The camera and target must be different points;
camera eye height should be about 1.6m. Ceiling fixtures use elevation = room height - item height.
Schema: {"name":string,"room":{"width":number,"depth":number,"height":number},
"items":[{"id":string,"name":string,"category":"furniture|fixture|architectural|decor",
"x":number,"z":number,"width":number,"depth":number,"height":number,"elevation":number,
"rotation_deg":number,"fixed":boolean,"clearance_m":number,"description":string}],
"openings":[{"id":string,"kind":"door|window","wall":"north|south|east|west",
"offset":number,"width":number,"height":number,"sill_height":number}],
"camera":{"x":number,"y":number,"z":number,"target_x":number,"target_y":number,
"target_z":number,"fov_deg":number},"circulation_notes":[string],"design_notes":[string]}"""


async def build_floor_plan(
    description: str,
    concept: SceneConcept,
    current: FloorPlan | None = None,
    feedback: str = "",
) -> tuple[FloorPlan, list[str]]:
    """Create or revise a plan, then normalize all authored geometry."""
    context = {
        "description": description,
        "concept": concept.model_dump(mode="json"),
    }
    if current:
        context["current_plan"] = current.model_dump(mode="json")
        context["revision_requirement"] = feedback
    instruction = "Revise the current plan while preserving unaffected IDs." if current else "Create the first practical plan."
    raw = await generate_json(PLAN_SYSTEM, f"{instruction}\n{json.dumps(context)}")
    plan = FloorPlan.model_validate(raw)
    return normalize_floor_plan(plan, description)

```

### `src/floor_plan/models.py`

```python
"""Typed contract for the approved spatial plan."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanRoom(BaseModel):
    width: float = Field(ge=2.5, le=30.0)
    depth: float = Field(ge=2.5, le=30.0)
    height: float = Field(default=2.8, ge=2.1, le=8.0)


class PlanItem(BaseModel):
    id: str
    name: str
    category: Literal["furniture", "fixture", "architectural", "decor"]
    x: float
    z: float
    width: float = Field(gt=0.02, le=20.0)
    depth: float = Field(gt=0.02, le=20.0)
    height: float = Field(gt=0.02, le=8.0)
    elevation: float = Field(default=0.0, ge=0.0, le=8.0)
    rotation_deg: float = 0.0
    fixed: bool = False
    clearance_m: float = Field(default=0.75, ge=0.0, le=3.0)
    description: str = ""


class PlanOpening(BaseModel):
    id: str
    kind: Literal["door", "window"]
    wall: Literal["north", "south", "east", "west"]
    offset: float = 0.0
    width: float = Field(default=0.9, gt=0.2, le=8.0)
    height: float = Field(default=2.1, gt=0.2, le=5.0)
    sill_height: float = Field(default=0.0, ge=0.0, le=4.0)


class PlanCamera(BaseModel):
    x: float
    y: float = Field(default=1.6, ge=0.2, le=5.0)
    z: float
    target_x: float = 0.0
    target_y: float = 1.1
    target_z: float = 0.0
    fov_deg: float = Field(default=55.0, ge=30.0, le=90.0)


class FloorPlan(BaseModel):
    name: str
    room: PlanRoom
    items: list[PlanItem] = Field(default_factory=list)
    openings: list[PlanOpening] = Field(default_factory=list)
    camera: PlanCamera
    circulation_notes: list[str] = Field(default_factory=list)
    design_notes: list[str] = Field(default_factory=list)

```

### `src/floor_plan/renderer.py`

```python
"""Render an authoritative plan as SVG and a camera-matched 3D blockout PNG."""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.floor_plan.models import FloorPlan, PlanItem

COLORS = {
    "furniture": "#d89552",
    "fixture": "#5fa7a1",
    "architectural": "#8d7cc2",
    "decor": "#6d83a8",
}


def render_floor_plan_svg(plan: FloorPlan, path: Path) -> Path:
    width, height, pad = 1000, 760, 86
    scale = min((width - 2 * pad) / plan.room.width, (height - 2 * pad) / plan.room.depth)
    ox, oy = width / 2, height / 2

    def point(x: float, z: float) -> tuple[float, float]:
        return ox + x * scale, oy - z * scale

    rw, rd = plan.room.width * scale, plan.room.depth * scale
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1017"/>',
        '<style>text{font-family:Segoe UI,Arial;fill:#dce5ef}.label{font-size:13px}.dim{font-size:15px;fill:#8e9aaa}.note{font-size:12px;fill:#697586}</style>',
        f'<rect x="{ox-rw/2:.1f}" y="{oy-rd/2:.1f}" width="{rw:.1f}" height="{rd:.1f}" fill="#111a24" stroke="#e7edf5" stroke-width="7"/>',
        f'<text x="{pad}" y="34" class="dim">{html.escape(plan.name)} · {plan.room.width:.1f}m × {plan.room.depth:.1f}m × {plan.room.height:.1f}m</text>',
        f'<text x="{ox:.1f}" y="{oy-rd/2-22:.1f}" text-anchor="middle" class="dim">NORTH · {plan.room.width:.1f}m</text>',
        f'<text x="{ox-rw/2-28:.1f}" y="{oy:.1f}" transform="rotate(-90 {ox-rw/2-28:.1f} {oy:.1f})" text-anchor="middle" class="dim">{plan.room.depth:.1f}m</text>',
    ]
    for item in plan.items:
        x, y = point(item.x, item.z)
        item_w, item_d = item.width * scale, item.depth * scale
        label = html.escape(_floor_label(item))
        full_label = html.escape(item.name)
        label_class = "label tiny" if min(item_w, item_d) < 58 else "label"
        parts.append(
            f'<g transform="translate({x:.1f} {y:.1f}) rotate({-item.rotation_deg:.1f})">'
            f'<title>{full_label}</title>'
            f'<rect x="{-item_w/2:.1f}" y="{-item_d/2:.1f}" width="{item_w:.1f}" height="{item_d:.1f}" rx="4" '
            f'fill="{COLORS[item.category]}" fill-opacity=".72" stroke="#f3f6fa" stroke-opacity=".65"/>'
            f'<text class="{label_class}" text-anchor="middle" dominant-baseline="middle">{label}</text></g>'
        )
    for opening in plan.openings:
        color = "#66d6a6" if opening.kind == "door" else "#69b9ff"
        half = opening.width * scale / 2
        if opening.wall in {"north", "south"}:
            _, y = point(0, plan.room.depth / 2 if opening.wall == "north" else -plan.room.depth / 2)
            x, _ = point(opening.offset, 0)
            parts.append(f'<line x1="{x-half:.1f}" y1="{y:.1f}" x2="{x+half:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="10"/>')
        else:
            x, _ = point(plan.room.width / 2 if opening.wall == "east" else -plan.room.width / 2, 0)
            _, y = point(0, opening.offset)
            parts.append(f'<line x1="{x:.1f}" y1="{y-half:.1f}" x2="{x:.1f}" y2="{y+half:.1f}" stroke="{color}" stroke-width="10"/>')
    cx, cy = point(plan.camera.x, plan.camera.z)
    tx, ty = point(plan.camera.target_x, plan.camera.target_z)
    parts.extend([
        f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="#ffcb70" stroke-width="3" stroke-dasharray="8 6"/>',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="#ffcb70"/><text x="{cx+16:.1f}" y="{cy-12:.1f}" class="label">CANON CAMERA</text>',
        '<text x="86" y="730" class="note">AMBER furniture · TEAL fixed fixtures · GREEN doors · BLUE windows · dashed line canon view</text>',
        '</svg>',
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path


def render_blockout(plan: FloorPlan, path: Path, concept=None) -> Path:
    canvas = Image.new("RGB", (1024, 768), "#111720")
    draw = ImageDraw.Draw(canvas)
    _draw_gradient(draw)
    camera = np.array([plan.camera.x, plan.camera.y, plan.camera.z], dtype=float)
    target = np.array([plan.camera.target_x, plan.camera.target_y, plan.camera.target_z], dtype=float)
    forward = target - camera
    forward /= max(np.linalg.norm(forward), 1e-6)
    right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
    right /= max(np.linalg.norm(right), 1e-6)
    up = np.cross(right, forward)
    focal = 512 / math.tan(math.radians(plan.camera.fov_deg) / 2)

    def project(vertex: tuple[float, float, float]) -> tuple[float, float, float] | None:
        relative = np.array(vertex) - camera
        depth = float(np.dot(relative, forward))
        if depth <= 0.08:
            return None
        return 512 + float(np.dot(relative, right)) * focal / depth, 384 - float(np.dot(relative, up)) * focal / depth, depth

    _draw_room(draw, plan, project, concept)
    items = sorted(plan.items, key=lambda item: -_distance(item, camera))
    for item in items:
        _draw_item(draw, item, project)
    draw.rectangle((18, 18, 520, 62), fill="#080c12dd", outline="#3d4858")
    draw.text((32, 30), f"APPROVED BLOCKOUT · {plan.name}", fill="#e8edf4")
    draw.text((20, 730), "Geometry and camera are locked; canon generation may change only appearance and lighting.", fill="#9ea9b7")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "PNG")
    return path


def _draw_gradient(draw: ImageDraw.ImageDraw) -> None:
    for y in range(768):
        value = int(13 + y * 15 / 768)
        draw.line((0, y, 1024, y), fill=(value, value + 5, value + 12))


def _draw_room(draw: ImageDraw.ImageDraw, plan: FloorPlan, project, concept=None) -> None:
    w, d, h = plan.room.width / 2, plan.room.depth / 2, plan.room.height
    floor = [project((-w, 0, -d)), project((w, 0, -d)), project((w, 0, d)), project((-w, 0, d))]
    concept_text = " " if concept is None else f"{concept.architecture_notes} {concept.image_prompt}".lower()
    if "checkerboard" in concept_text:
        tile = 0.5
        x_steps, z_steps = math.ceil(plan.room.width / tile), math.ceil(plan.room.depth / tile)
        for x_index in range(x_steps):
            for z_index in range(z_steps):
                x0, x1 = -w + x_index * tile, min(w, -w + (x_index + 1) * tile)
                z0, z1 = -d + z_index * tile, min(d, -d + (z_index + 1) * tile)
                corners = [project((x0, 0, z0)), project((x1, 0, z0)), project((x1, 0, z1)), project((x0, 0, z1))]
                if all(corners):
                    color = "#ded8c8" if (x_index + z_index) % 2 else "#1b1d20"
                    draw.polygon([(point[0], point[1]) for point in corners], fill=color, outline="#555b62")
    elif all(floor):
        draw.polygon([(p[0], p[1]) for p in floor], fill="#343b43", outline="#8d98a6")
    if all(floor):
        draw.line([(point[0], point[1]) for point in floor] + [(floor[0][0], floor[0][1])], fill="#8d98a6", width=3)
    edges = [
        ((-w, 0, -d), (-w, h, -d)), ((w, 0, -d), (w, h, -d)),
        ((-w, 0, d), (-w, h, d)), ((w, 0, d), (w, h, d)),
        ((-w, h, -d), (w, h, -d)), ((w, h, -d), (w, h, d)),
        ((w, h, d), (-w, h, d)), ((-w, h, d), (-w, h, -d)),
    ]
    for start, end in edges:
        a, b = project(start), project(end)
        if a and b:
            draw.line((a[0], a[1], b[0], b[1]), fill="#778493", width=3)
    for opening in plan.openings:
        low, high = opening.sill_height, opening.sill_height + opening.height
        half = opening.width / 2
        if opening.wall == "north":
            vertices = [(opening.offset-half, low, d), (opening.offset+half, low, d), (opening.offset+half, high, d), (opening.offset-half, high, d)]
        elif opening.wall == "south":
            vertices = [(opening.offset+half, low, -d), (opening.offset-half, low, -d), (opening.offset-half, high, -d), (opening.offset+half, high, -d)]
        elif opening.wall == "east":
            vertices = [(w, low, opening.offset-half), (w, low, opening.offset+half), (w, high, opening.offset+half), (w, high, opening.offset-half)]
        else:
            vertices = [(-w, low, opening.offset+half), (-w, low, opening.offset-half), (-w, high, opening.offset-half), (-w, high, opening.offset+half)]
        projected = [project(vertex) for vertex in vertices]
        if all(projected):
            points = [(point[0], point[1]) for point in projected]
            fill = "#183a4d" if opening.kind == "window" else "#244236"
            outline = "#69b9ff" if opening.kind == "window" else "#66d6a6"
            draw.polygon(points, fill=fill, outline=outline)
            draw.line(points + [points[0]], fill=outline, width=5)
            label = "WINDOW" if opening.kind == "window" else "DOOR"
            anchor_x = sum(point[0] for point in points) / 4
            anchor_y = sum(point[1] for point in points) / 4
            draw.text((anchor_x - 24, anchor_y - 7), label, fill="#eef7ff")


def _distance(item: PlanItem, camera: np.ndarray) -> float:
    return float(np.linalg.norm(np.array([item.x, item.elevation + item.height / 2, item.z]) - camera))


def _draw_item(draw: ImageDraw.ImageDraw, item: PlanItem, project) -> None:
    angle = math.radians(item.rotation_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    local = [(-item.width/2, -item.depth/2), (item.width/2, -item.depth/2), (item.width/2, item.depth/2), (-item.width/2, item.depth/2)]
    base = [(item.x + x*cos_a - z*sin_a, item.elevation, item.z + x*sin_a + z*cos_a) for x, z in local]
    top = [(x, item.elevation + item.height, z) for x, _, z in base]
    vertices = base + top
    projected = [project(vertex) for vertex in vertices]
    if not all(projected):
        return
    faces = [
        ([4, 5, 6, 7], "#dba25f"), ([0, 1, 5, 4], "#8b6846"),
        ([1, 2, 6, 5], "#a77b4d"), ([2, 3, 7, 6], "#765b42"),
        ([3, 0, 4, 7], "#947052"),
    ]
    ranked = []
    for indices, color in faces:
        depth = sum(projected[index][2] for index in indices) / len(indices)
        ranked.append((depth, indices, color))
    for _, indices, color in sorted(ranked, reverse=True):
        points = [(projected[index][0], projected[index][1]) for index in indices]
        draw.polygon(points, fill=color, outline="#f0d1a4")
    anchor = projected[4]
    draw.text((anchor[0] + 4, anchor[1] - 14), item.name[:24], fill="#f2f4f7")


def _floor_label(item: PlanItem) -> str:
    text = f"{item.id} {item.name}".lower()
    suffix = re.search(r"(\d+)$", item.id)
    number = suffix.group(1) if suffix else ""
    if "stool" in text:
        return f"S{number}" if number else "STOOL"
    if "pendant" in text or "light" in text:
        return f"P{number}" if number else "LIGHT"
    if "counter" in text:
        return f"COUNTER · {item.width:.1f}m"
    label = item.name.upper()
    return label if len(label) <= 18 else f"{label[:17]}…"

```

### `src/floor_plan/validator.py`

```python
"""Deterministic bounds and circulation checks for model-authored plans."""

from __future__ import annotations

import math
import re

from src.floor_plan.models import FloorPlan


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_id(value: str, fallback: str) -> str:
    clean = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return clean or fallback


def normalize_floor_plan(source: FloorPlan, description: str = "") -> tuple[FloorPlan, list[str]]:
    """Return a safe copy and honor explicit metric/spatial user constraints."""
    plan = source.model_copy(deep=True)
    warnings: list[str] = []
    _apply_explicit_dimensions(plan, description, warnings)
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    opening_ids = {opening.id.lower() for opening in plan.openings}
    surfaces = {"floor", "flooring", "wall", "walls", "ceiling", "door", "doors", "window", "windows"}
    kept = []
    for item in plan.items:
        words = set(re.findall(r"[a-z]+", f"{item.id} {item.name}".lower()))
        if item.id.lower() in opening_ids or words & surfaces:
            continue
        else:
            kept.append(item)
    plan.items = kept
    plan.items = _expand_grouped_items(plan.items, warnings)
    seen: set[str] = set()
    for index, item in enumerate(plan.items):
        item.id = _safe_id(item.id, f"item_{index + 1}")
        if item.id in seen:
            item.id = f"{item.id}_{index + 1}"
        seen.add(item.id)
        item.width = min(item.width, plan.room.width)
        item.depth = min(item.depth, plan.room.depth)
        old = (item.x, item.z)
        item.x = _clamp(item.x, -half_w + item.width / 2, half_w - item.width / 2)
        item.z = _clamp(item.z, -half_d + item.depth / 2, half_d - item.depth / 2)
        item.rotation_deg %= 360
        words = set(re.findall(r"[a-z]+", f"{item.id} {item.name}".lower()))
        ceiling_fixture = bool(words & {"pendant", "chandelier", "ceiling", "hanging"})
        item.elevation = max(0.0, plan.room.height - item.height) if ceiling_fixture else 0.0
        if words & {"stool", "stools", "chair", "chairs", "table", "tables", "ottoman"}:
            item.fixed = False
        if old != (item.x, item.z):
            pass
    for index, opening in enumerate(plan.openings):
        opening.id = _safe_id(opening.id, f"opening_{index + 1}")
        wall_length = plan.room.width if opening.wall in {"north", "south"} else plan.room.depth
        opening.width = min(opening.width, wall_length - 0.2)
        opening.offset = _clamp(opening.offset, -wall_length / 2 + opening.width / 2, wall_length / 2 - opening.width / 2)
        if opening.kind == "door":
            opening.sill_height = 0.0
        else:
            opening.sill_height = _clamp(opening.sill_height, 0.0, plan.room.height - 0.2)
            opening.height = min(opening.height, plan.room.height - opening.sill_height)
    _apply_description_layout(plan, description, warnings)
    _distribute_repeated_items(plan, warnings)
    plan.camera.x = _clamp(plan.camera.x, -half_w + 0.2, half_w - 0.2)
    plan.camera.z = _clamp(plan.camera.z, -half_d + 0.2, half_d - 0.2)
    plan.camera.y = _clamp(plan.camera.y, 1.2, plan.room.height - 0.2)
    _place_camera_clear(plan, warnings)
    view_length = math.sqrt(
        (plan.camera.target_x - plan.camera.x) ** 2
        + (plan.camera.target_y - plan.camera.y) ** 2
        + (plan.camera.target_z - plan.camera.z) ** 2
    )
    horizontal_view = math.hypot(plan.camera.target_x - plan.camera.x, plan.camera.target_z - plan.camera.z)
    if view_length < 0.5 or horizontal_view < 1.0:
        plan.camera.target_x = 0.0
        plan.camera.target_y = min(1.2, plan.room.height / 2)
        plan.camera.target_z = 0.0
    warnings.extend(_overlap_warnings(plan))
    return plan, warnings


def _overlap_warnings(plan: FloorPlan) -> list[str]:
    warnings: list[str] = []
    for index, left in enumerate(plan.items):
        for right in plan.items[index + 1:]:
            dx = abs(left.x - right.x)
            dz = abs(left.z - right.z)
            overlap_x = dx < (left.width + right.width) / 2 - 0.03
            overlap_z = dz < (left.depth + right.depth) / 2 - 0.03
            vertical_overlap = left.elevation < right.elevation + right.height - 0.03 and right.elevation < left.elevation + left.height - 0.03
            if overlap_x and overlap_z and vertical_overlap and not (left.fixed and right.fixed):
                warnings.append(f"Check overlap: {left.name} / {right.name}")
    for item in plan.items:
        if not math.isfinite(item.x + item.z + item.width + item.depth):
            warnings.append(f"Invalid numeric value on {item.name}")
    return warnings[:12]


_COUNT_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_REPEATABLE = {"stools", "chairs", "lamps", "lights", "pendants", "tables"}


def _expand_grouped_items(items, warnings):
    expanded = []
    for item in items:
        words = re.findall(r"[a-z0-9]+", item.name.lower())
        first = words[0] if words else ""
        count = int(first) if first.isdigit() else _COUNT_WORDS.get(first, 1)
        if count <= 1 or count > 8 or not set(words) & _REPEATABLE:
            expanded.append(item)
            continue
        angle = math.radians(item.rotation_deg)
        along_x = item.width >= item.depth
        span = item.width if along_x else item.depth
        spacing = span / count
        footprint = max(0.12, min(spacing * 0.72, item.depth if along_x else item.width))
        base_id = re.sub(r"_(stools|chairs|lamps|lights|pendants|tables)$", lambda match: "_" + match.group(1).rstrip("s"), item.id)
        base_name = " ".join(item.name.split()[1:]).rstrip("s")
        for index in range(count):
            clone = item.model_copy(deep=True)
            offset = -span / 2 + spacing * (index + 0.5)
            local_x, local_z = (offset, 0.0) if along_x else (0.0, offset)
            clone.x = item.x + local_x * math.cos(angle) - local_z * math.sin(angle)
            clone.z = item.z + local_x * math.sin(angle) + local_z * math.cos(angle)
            clone.width = footprint
            clone.depth = footprint
            clone.id = f"{base_id}_{index + 1}"
            clone.name = f"{base_name} {index + 1}"
            expanded.append(clone)
    return expanded


def _distribute_repeated_items(plan: FloorPlan, warnings: list[str]) -> None:
    groups: dict[str, list] = {}
    for item in plan.items:
        key = re.sub(r"_\d+$", "", item.id)
        groups.setdefault(key, []).append(item)
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    for key, group in groups.items():
        if len(group) < 2:
            continue
        candidates = [item for item in plan.items if item not in group and item.fixed and item.elevation == 0]
        anchor = max(candidates, key=lambda item: item.width * item.depth, default=None)
        sample = group[0]
        ceiling_group = all(item.elevation > 0 for item in group)
        if anchor and anchor.width >= anchor.depth:
            available = max(sample.width, anchor.width - sample.width)
            spacing = min(max(sample.width + 0.25, 0.65), available / max(1, len(group) - 1))
            center = anchor.x
            if ceiling_group:
                z = anchor.z
            else:
                direction = -1 if anchor.z >= 0 else 1
                z = anchor.z + direction * (anchor.depth / 2 + sample.depth / 2 + 0.35)
            for index, item in enumerate(group):
                item.x = _clamp(center + (index - (len(group) - 1) / 2) * spacing, -half_w + item.width / 2, half_w - item.width / 2)
                item.z = _clamp(z, -half_d + item.depth / 2, half_d - item.depth / 2)
        elif anchor:
            available = max(sample.depth, anchor.depth - sample.depth)
            spacing = min(max(sample.depth + 0.25, 0.65), available / max(1, len(group) - 1))
            center = anchor.z
            if ceiling_group:
                x = anchor.x
            else:
                direction = -1 if anchor.x >= 0 else 1
                x = anchor.x + direction * (anchor.width / 2 + sample.width / 2 + 0.35)
            for index, item in enumerate(group):
                item.x = _clamp(x, -half_w + item.width / 2, half_w - item.width / 2)
                item.z = _clamp(center + (index - (len(group) - 1) / 2) * spacing, -half_d + item.depth / 2, half_d - item.depth / 2)
        else:
            spacing = max(sample.width * 1.7, 0.75)
            for index, item in enumerate(group):
                item.x = _clamp((index - (len(group) - 1) / 2) * spacing, -half_w + item.width / 2, half_w - item.width / 2)


def _place_camera_clear(plan: FloorPlan, warnings: list[str]) -> None:
    camera_x, camera_z = plan.camera.x, plan.camera.z
    blocked = any(
        abs(camera_x - item.x) < item.width / 2 + 0.25
        and abs(camera_z - item.z) < item.depth / 2 + 0.25
        and item.elevation < 0.3
        for item in plan.items
    )
    if not blocked:
        return
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    candidates = [
        (-half_w + 0.45, -half_d + 0.45),
        (half_w - 0.45, -half_d + 0.45),
        (-half_w + 0.45, half_d - 0.45),
        (half_w - 0.45, half_d - 0.45),
    ]
    def clearance(candidate):
        distances = [
            (candidate[0] - item.x) ** 2 + (candidate[1] - item.z) ** 2
            for item in plan.items if item.elevation < plan.camera.y
        ]
        return min(distances) if distances else 999.0
    plan.camera.x, plan.camera.z = max(candidates, key=clearance)
    plan.camera.target_x = 0.0
    plan.camera.target_y = min(1.2, plan.room.height / 2)
    plan.camera.target_z = 0.0


def _apply_explicit_dimensions(plan: FloorPlan, description: str, warnings: list[str]) -> None:
    text = description.lower().replace("metres", "meters")
    pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\s*wide.{0,80}?"
        r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\s*deep.{0,80}?"
        r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\s*(?:high|tall)",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return
    width, depth, height = (float(value) for value in match.groups())
    plan.room.width = _clamp(width, 2.5, 30.0)
    plan.room.depth = _clamp(depth, 2.5, 30.0)
    plan.room.height = _clamp(height, 2.1, 8.0)


def _apply_description_layout(plan: FloorPlan, description: str, warnings: list[str]) -> None:
    text = description.lower()
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    counter = next((item for item in plan.items if "counter" in f"{item.id} {item.name}".lower()), None)
    if counter:
        counter.fixed = True
        if re.search(r"counter.{0,180}north wall|north wall.{0,180}counter", text, re.DOTALL):
            counter.rotation_deg = 0.0
            counter.x = 0.0
            counter.z = half_d - counter.depth / 2 - 0.25
        elif re.search(r"counter.{0,180}south wall|south wall.{0,180}counter", text, re.DOTALL):
            counter.rotation_deg = 0.0
            counter.x = 0.0
            counter.z = -half_d + counter.depth / 2 + 0.25
    for opening in plan.openings:
        if opening.kind == "door":
            if "door on the west wall" in text or "west-wall" in text:
                opening.wall = "west"
            if "northwest corner" in text and opening.wall in {"west", "east"}:
                opening.offset = half_d - opening.width / 2 - 0.2
            elif "southwest corner" in text and opening.wall in {"west", "east"}:
                opening.offset = -half_d + opening.width / 2 + 0.2
        elif opening.kind == "window":
            centered_south = bool(
                re.search(r"center(?:ed)?\s+(?:one\s+)?(?:large\s+)?(?:storefront\s+)?window\s+on\s+the\s+south\s+wall", text)
                or re.search(r"(?:storefront\s+)?window.{0,60}center(?:ed)?.{0,40}south\s+wall", text)
                or "south-wall storefront window" in text
            )
            if centered_south:
                opening.wall = "south"
                opening.offset = 0.0
                if "large" in text and "storefront window" in text:
                    opening.width = min(max(opening.width, plan.room.width * 0.6), plan.room.width - 0.4)
    corners = {
        "southeast corner": (half_w - 0.45, -half_d + 0.45),
        "southwest corner": (-half_w + 0.45, -half_d + 0.45),
        "northeast corner": (half_w - 0.45, half_d - 0.45),
        "northwest corner": (-half_w + 0.45, half_d - 0.45),
    }
    for phrase, (x, z) in corners.items():
        if f"camera at normal eye height in the {phrase}" in text or f"camera in the {phrase}" in text:
            plan.camera.x, plan.camera.z = x, z
            plan.camera.y = 1.6
            plan.camera.target_x = counter.x if counter else 0.0
            plan.camera.target_y = min(1.2, plan.room.height / 2)
            plan.camera.target_z = counter.z if counter else 0.0
            break

```

### `src/models.py`

```python
"""
Core data models for The Living Room.
These are the contracts between every component in the pipeline.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.floor_plan.models import FloorPlan


# --- Scene Concept (output of Orchestrator) ---


class SceneConcept(BaseModel):
    """The AI's interpretation of the user's description."""

    era: str = Field(description="Time period / style era")
    mood: str = Field(description="Emotional tone: warm, cold, moody, bright, etc.")
    palette: str = Field(description="Dominant color palette description")
    architecture_notes: str = Field(description="Brief on walls, floor, ceiling style")
    key_objects: list[str] = Field(description="List of main objects in the scene")
    lighting_notes: str = Field(description="Brief on lighting mood and sources")
    image_prompt: str = Field(description="Optimized prompt for photorealistic image generation")


# --- Scene Graph (spatial layout for 3D construction) ---


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class PhysicsBody(str, Enum):
    STATIC = "static"
    RIGID = "rigid"
    KINEMATIC = "kinematic"


class PhysicsProps(BaseModel):
    body_type: PhysicsBody = PhysicsBody.STATIC
    mass_kg: float = 1.0
    friction: float = 0.5
    restitution: float = 0.1
    can_topple: bool = False


class MaterialProps(BaseModel):
    base_color: str = Field(default="#808080", description="Hex color or material name")
    metallic: float = Field(default=0.0, ge=0.0, le=1.0)
    roughness: float = Field(default=0.8, ge=0.0, le=1.0)
    emission_color: Optional[str] = None
    emission_strength: float = 0.0


class SceneObject(BaseModel):
    id: str
    name: str
    object_type: str = Field(description="Category: furniture, fixture, architectural, decor")
    position: Vec3
    rotation: Vec3 = Field(default_factory=Vec3)
    scale: Vec3 = Field(default_factory=lambda: Vec3(x=1.0, y=1.0, z=1.0))
    dimensions: Vec3 = Field(description="Bounding box size in meters")
    physics: PhysicsProps = Field(default_factory=PhysicsProps)
    material: MaterialProps = Field(default_factory=MaterialProps)
    mesh_type: str = Field(
        default="primitive",
        description="'primitive' for procedural gen, 'generated' for AI reconstruction",
    )
    primitive_shape: Optional[str] = Field(
        default=None, description="box, cylinder, sphere, plane, capsule"
    )
    description: str = Field(default="", description="Visual description for mesh generation")


class LightType(str, Enum):
    POINT = "point"
    SPOT = "spot"
    DIRECTIONAL = "directional"
    AREA = "area"


class SceneLight(BaseModel):
    id: str
    name: str
    light_type: LightType
    position: Vec3
    direction: Vec3 = Field(default_factory=lambda: Vec3(x=0, y=-1, z=0))
    color: str = Field(description="Hex color")
    color_temperature_k: int = Field(default=4000, description="Color temp in Kelvin")
    intensity: float = Field(default=1.0, description="Energy/intensity value")
    range_meters: float = Field(default=5.0, description="Effective radius")
    spot_angle_deg: float = Field(default=45.0, description="Spot cone angle")
    cast_shadows: bool = True


class RoomShell(BaseModel):
    width: float = Field(description="X dimension in meters")
    depth: float = Field(description="Z dimension in meters")
    height: float = Field(description="Y dimension in meters")
    floor_material: MaterialProps = Field(default_factory=MaterialProps)
    wall_material: MaterialProps = Field(default_factory=MaterialProps)
    ceiling_material: MaterialProps = Field(default_factory=MaterialProps)


class DoorSpec(BaseModel):
    id: str
    position: Vec3
    wall: str = Field(description="north, south, east, west")
    width: float = 0.9
    height: float = 2.1
    swing_direction: str = "inward"
    physics: PhysicsProps = Field(
        default_factory=lambda: PhysicsProps(body_type=PhysicsBody.RIGID, mass_kg=15.0)
    )


class WindowSpec(BaseModel):
    id: str
    position: Vec3
    wall: str
    width: float = 1.2
    height: float = 1.0
    sill_height: float = 0.9


class SceneGraph(BaseModel):
    """Complete spatial description of the world to be built."""

    name: str
    description: str
    room: RoomShell
    objects: list[SceneObject] = Field(default_factory=list)
    lights: list[SceneLight] = Field(default_factory=list)
    doors: list[DoorSpec] = Field(default_factory=list)
    windows: list[WindowSpec] = Field(default_factory=list)
    ambient_color: str = Field(default="#1a1a2e", description="Global ambient light color")
    ambient_energy: float = Field(default=0.3, description="Global ambient intensity")


# --- Pipeline State ---


class PipelineState(str, Enum):
    AWAITING_DESCRIPTION = "awaiting_description"
    GENERATING_CONCEPT = "generating_concept"
    GENERATING_PLAN = "generating_plan"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    GENERATING_IMAGE = "generating_image"
    AWAITING_APPROVAL = "awaiting_approval"
    BUILDING_SCENE_GRAPH = "building_scene_graph"
    GENERATING_ASSETS = "generating_assets"
    ASSEMBLING_WORLD = "assembling_world"
    REFINING_WORLD = "refining_world"
    READY = "ready"
    ERROR = "error"


class WorldSession(BaseModel):
    """Tracks the state and revision memory of a world-building session."""

    session_id: str
    interface_version: int = 7
    workflow_profile_id: str = ""
    workflow_profile: dict = Field(default_factory=dict)
    workflow_snapshot_count: int = 0
    workflow_records: list[str] = Field(default_factory=list)
    generation_manifests: list[str] = Field(default_factory=list)
    state: PipelineState = PipelineState.AWAITING_DESCRIPTION
    user_description: str = ""
    scene_concept: Optional[SceneConcept] = None
    floor_plan: Optional[FloorPlan] = None
    floor_plan_path: Optional[str] = None
    blockout_path: Optional[str] = None
    floor_plan_approved: bool = False
    canon_image_path: Optional[str] = None
    canon_provider: Optional[str] = None
    scene_graph: Optional[SceneGraph] = None
    output_path: Optional[str] = None
    plan_revision: int = 0
    plan_warnings: list[str] = Field(default_factory=list)
    world_revision: int = 0
    render_paths: list[str] = Field(default_factory=list)
    revision_history: list[dict] = Field(default_factory=list)
    error: Optional[str] = None
    progress_messages: list[str] = Field(default_factory=list)

```

### `src/orchestrator/__init__.py`

```python

```

### `src/orchestrator/interpreter.py`

```python
"""
Scene Interpreter - Takes user description, produces SceneConcept.
"""

from __future__ import annotations

from src.models import SceneConcept
from src.orchestrator.llm import generate_json
from src.orchestrator.prompts import SCENE_INTERPRETER_SYSTEM


async def interpret_description(user_description: str) -> SceneConcept:
    """Take a plain-language description and return a structured SceneConcept."""
    data = await generate_json(
        system=SCENE_INTERPRETER_SYSTEM,
        user=user_description,
    )
    return SceneConcept(**data)

```

### `src/orchestrator/llm.py`

```python
"""
LLM interface - supports Ollama (local) and any OpenAI-compatible API.
Designed to work with whatever is available.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OPENAI_API_URL = os.getenv("OPENAI_API_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))


class LLMError(Exception):
    pass


async def _call_ollama(
    system: str, user: str, model: str, *, json_mode: bool = False
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": 0.15 if json_mode else 0.7,
            "num_predict": 8192,
            "num_ctx": 16384,
        },
    }
    if json_mode:
        payload["format"] = "json"
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        if response.status_code != 200:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text}")
        return response.json()["message"]["content"]


async def _call_openai_compatible(
    system: str, user: str, model: str, *, json_mode: bool = False
) -> str:
    headers = {"Content-Type": "application/json"}
    if OPENAI_API_KEY:
        headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.15 if json_mode else 0.7,
        "max_tokens": 8192,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        response = await client.post(
            f"{OPENAI_API_URL}/v1/chat/completions", headers=headers, json=payload
        )
        if response.status_code != 200:
            raise LLMError(f"API returned {response.status_code}: {response.text}")
        return response.json()["choices"][0]["message"]["content"]


async def generate(
    system: str,
    user: str,
    model: Optional[str] = None,
    *,
    json_mode: bool = False,
) -> str:
    """Generate a response, preferring local Ollama and retaining mock fallback."""
    model = model or LLM_MODEL
    if OLLAMA_URL:
        try:
            return await _call_ollama(system, user, model, json_mode=json_mode)
        except (httpx.HTTPError, LLMError):
            pass
    if OPENAI_API_URL:
        try:
            return await _call_openai_compatible(
                system, user, model, json_mode=json_mode
            )
        except (httpx.HTTPError, LLMError):
            pass
    from src.orchestrator.mock_llm import mock_generate
    return mock_generate(system, user)


def _parse_json(raw: str) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise LLMError("LLM JSON response must be an object")
    return value


async def generate_json(
    system: str, user: str, model: Optional[str] = None
) -> dict:
    """Generate a JSON object using provider JSON mode and one repair retry."""
    raw = ""
    parse_error: json.JSONDecodeError | None = None
    for attempt in range(2):
        retry_note = ""
        if attempt:
            retry_note = (
                "\n\nYour previous response was malformed or incomplete. "
                "Return the complete object as compact valid JSON only."
            )
        raw = await generate(
            system, user + retry_note, model, json_mode=True
        )
        try:
            return _parse_json(raw)
        except json.JSONDecodeError as exc:
            parse_error = exc
    raise LLMError(
        f"LLM returned invalid JSON after retry: {parse_error}\nRaw output:\n{raw[:500]}"
    )


async def generate_vision_json(
    system: str,
    user: str,
    image_paths: list[str | os.PathLike[str]],
    model: Optional[str] = None,
) -> dict:
    """Generate strict JSON from one or more images using local Ollama vision."""
    import base64
    from pathlib import Path

    vision_model = model or os.getenv("VISION_MODEL", "qwen2.5vl:7b")
    images = [base64.b64encode(Path(path).read_bytes()).decode("ascii") for path in image_paths]
    raw = ""
    last_error: json.JSONDecodeError | None = None
    for attempt in range(2):
        prompt = user
        if attempt:
            prompt += "\nYour prior response was malformed. Return one complete compact JSON object only."
        payload = {
            "model": vision_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt, "images": images},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 8192, "num_ctx": 24576},
        }
        async with httpx.AsyncClient(timeout=max(LLM_TIMEOUT, 300)) as client:
            response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        if response.status_code != 200:
            raise LLMError(f"Vision model returned {response.status_code}: {response.text[:500]}")
        raw = response.json()["message"]["content"]
        try:
            return _parse_json(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise LLMError(f"Vision model returned invalid JSON: {last_error}\n{raw[:500]}")

```

### `src/orchestrator/mock_llm.py`

```python
"""
Mock LLM responses for development and demo mode.
Produces a complete, realistic 1950s diner scene when no live LLM is available.
"""

from __future__ import annotations

import json

MOCK_SCENE_CONCEPT = {
    "era": "1950s",
    "mood": "warm and nostalgic, rainy evening atmosphere",
    "palette": "chrome silver, red vinyl, cream tile, warm amber light, cool blue-gray from outside",
    "architecture_notes": "Cream ceramic tile wainscoting on lower walls, painted plaster upper walls in soft cream. Black and white checkered linoleum floor. Pressed tin ceiling tiles painted cream. Chrome trim throughout.",
    "key_objects": [
        "formica counter with chrome edge trim",
        "chrome diner stool with red vinyl seat",
        "chrome diner stool with red vinyl seat",
        "chrome diner stool with red vinyl seat",
        "chrome diner stool with red vinyl seat",
        "industrial pendant lamp",
        "pie display case with glass doors",
        "chrome napkin dispenser on counter",
        "coffee mug",
    ],
    "lighting_notes": "Primary: warm industrial pendant lamp over counter (~3000K). Secondary: cool blue-gray ambient light from rain-streaked storefront window. Strong warm/cool contrast. Deep shadows in corners.",
    "image_prompt": "Interior photograph of a 1950s American diner counter at evening. Four chrome stools with red vinyl seats line a formica counter with chrome edge trim. A single industrial pendant lamp hangs low over the counter, casting warm amber light. Through the large storefront window, rain streaks the glass and cool blue-gray evening light filters in. Checkered black and white linoleum floor, cream tile wainscoting, pressed tin ceiling. A glass pie case sits at one end. Photorealistic, moody, cinematic lighting, shot on 35mm film.",
}

MOCK_SCENE_GRAPH = {
    "name": "fifties_diner_counter",
    "description": "A moody 1950s diner counter scene with warm pendant lighting and rainy evening atmosphere",
    "room": {
        "width": 7.0,
        "depth": 5.0,
        "height": 3.2,
        "floor_material": {"base_color": "#2a2a2a", "metallic": 0.1, "roughness": 0.4},
        "wall_material": {"base_color": "#f5f0e8", "metallic": 0.0, "roughness": 0.85},
        "ceiling_material": {"base_color": "#ede8dc", "metallic": 0.2, "roughness": 0.6},
    },
    "objects": [
        {
            "id": "counter_01",
            "name": "Diner Counter",
            "object_type": "furniture",
            "position": {"x": 0.0, "y": 0.0, "z": -0.5},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 4.5, "y": 1.05, "z": 0.65},
            "physics": {"body_type": "static", "mass_kg": 200.0, "friction": 0.6, "restitution": 0.05, "can_topple": False},
            "material": {"base_color": "#d4c5a9", "metallic": 0.3, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "box",
            "description": "Formica countertop with chrome edge trim",
        },
        {
            "id": "stool_01",
            "name": "Diner Stool 1",
            "object_type": "furniture",
            "position": {"x": -1.2, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": 10.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "stool_02",
            "name": "Diner Stool 2",
            "object_type": "furniture",
            "position": {"x": -0.4, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": -5.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "stool_03",
            "name": "Diner Stool 3",
            "object_type": "furniture",
            "position": {"x": 0.4, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "stool_04",
            "name": "Diner Stool 4",
            "object_type": "furniture",
            "position": {"x": 1.2, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": 15.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "pie_case_01",
            "name": "Pie Display Case",
            "object_type": "fixture",
            "position": {"x": 2.8, "y": 0.0, "z": -0.5},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.7, "y": 1.2, "z": 0.5},
            "physics": {"body_type": "static", "mass_kg": 50.0, "friction": 0.5, "restitution": 0.05, "can_topple": False},
            "material": {"base_color": "#e8e8e8", "metallic": 0.4, "roughness": 0.2},
            "mesh_type": "primitive",
            "primitive_shape": "box",
            "description": "Glass and chrome pie display case",
        },
        {
            "id": "mug_01",
            "name": "Coffee Mug",
            "object_type": "decor",
            "position": {"x": -0.8, "y": 1.05, "z": -0.4},
            "rotation": {"x": 0.0, "y": 35.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.09, "y": 0.1, "z": 0.09},
            "physics": {"body_type": "rigid", "mass_kg": 0.35, "friction": 0.6, "restitution": 0.05, "can_topple": True},
            "material": {"base_color": "#f0f0f0", "metallic": 0.1, "roughness": 0.7},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "White ceramic diner coffee mug",
        },
        {
            "id": "napkin_dispenser_01",
            "name": "Napkin Dispenser",
            "object_type": "decor",
            "position": {"x": 0.6, "y": 1.05, "z": -0.6},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.14, "y": 0.15, "z": 0.08},
            "physics": {"body_type": "rigid", "mass_kg": 1.2, "friction": 0.5, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0c0c0", "metallic": 0.9, "roughness": 0.15},
            "mesh_type": "primitive",
            "primitive_shape": "box",
            "description": "Chrome napkin dispenser, rectangular, reflective",
        },
    ],
    "lights": [
        {
            "id": "pendant_01",
            "name": "Pendant Lamp",
            "light_type": "point",
            "position": {"x": 0.0, "y": 2.6, "z": 0.0},
            "direction": {"x": 0.0, "y": -1.0, "z": 0.0},
            "color": "#ffb347",
            "color_temperature_k": 2800,
            "intensity": 3.5,
            "range_meters": 5.0,
            "spot_angle_deg": 45.0,
            "cast_shadows": True,
        },
        {
            "id": "window_ambient",
            "name": "Window Ambient Light",
            "light_type": "directional",
            "position": {"x": 0.0, "y": 2.0, "z": 2.5},
            "direction": {"x": 0.0, "y": -0.3, "z": -0.7},
            "color": "#7ba3c4",
            "color_temperature_k": 7500,
            "intensity": 0.8,
            "range_meters": 10.0,
            "spot_angle_deg": 90.0,
            "cast_shadows": True,
        },
    ],
    "doors": [
        {
            "id": "kitchen_door",
            "position": {"x": -3.2, "y": 0.0, "z": -1.0},
            "wall": "west",
            "width": 0.9,
            "height": 2.1,
            "swing_direction": "inward",
        }
    ],
    "windows": [
        {
            "id": "storefront_window",
            "position": {"x": 0.0, "y": 0.0, "z": 2.5},
            "wall": "north",
            "width": 3.0,
            "height": 2.0,
            "sill_height": 0.3,
        }
    ],
    "ambient_color": "#1a1a2e",
    "ambient_energy": 0.15,
}


def mock_generate(system: str, user: str) -> str:
    """Produce mock responses based on what the system prompt is asking for."""
    lower = system.lower()
    if "spatial planner" in lower or ("scene graph" in lower and "room" in lower):
        return json.dumps(MOCK_SCENE_GRAPH, indent=2)
    elif "creative director" in lower or ("scene concept" in lower and "image_prompt" in lower):
        return json.dumps(MOCK_SCENE_CONCEPT, indent=2)
    elif "image_prompt" in lower or "regeneration" in lower:
        return MOCK_SCENE_CONCEPT["image_prompt"]
    else:
        return json.dumps(MOCK_SCENE_CONCEPT, indent=2)

```

### `src/orchestrator/prompts.py`

```python
"""
System prompts and prompt templates for the orchestrator LLM.
"""

SCENE_INTERPRETER_SYSTEM = """You are the creative director for The Living Room, a system that builds 
walkable 3D worlds from text descriptions. Your job is to take a user's plain-language description 
of an interior space and produce a complete, detailed scene concept.

You must output valid JSON with exactly this structure:
{
  "era": "the time period or style (e.g. '1950s', 'victorian', 'modern minimalist')",
  "mood": "emotional tone (e.g. 'warm and nostalgic', 'cold and clinical', 'moody noir')",
  "palette": "dominant colors (e.g. 'chrome, red vinyl, cream, warm amber')",
  "architecture_notes": "brief description of walls, floor, ceiling treatment and style",
  "key_objects": ["list", "of", "every", "significant", "object", "in", "the", "scene"],
  "lighting_notes": "description of all light sources, their warmth, direction, and mood",
  "image_prompt": "A detailed, optimized prompt for a photorealistic image generator. Should be 2-4 sentences describing the scene as a photograph. Include camera angle, lighting quality, atmosphere, and specific visual details. Start with 'Interior photograph of...'"
}

Rules:
- Infer details the user didn't specify. A "1950s diner" implies chrome, vinyl, linoleum, warm lighting.
- The image_prompt must be rich enough to produce a photorealistic result without ambiguity.
- key_objects should include EVERY object that would be visible — furniture, fixtures, small items, architectural features.
- Always include at least one light source in the scene.
- Be specific about materials: not "a counter" but "a formica counter with chrome edge trim".
- Output ONLY the JSON. No markdown, no explanation, no preamble."""

SCENE_GRAPH_SYSTEM = """You are the spatial planner for The Living Room. Given a scene concept 
(era, mood, objects, lighting), you produce a precise 3D scene graph as JSON.

You must output valid JSON with this structure:
{
  "name": "scene_name_snake_case",
  "description": "One sentence description",
  "room": {
    "width": <float meters>,
    "depth": <float meters>,
    "height": <float meters>,
    "floor_material": {"base_color": "#hex", "metallic": 0.0, "roughness": 0.8},
    "wall_material": {"base_color": "#hex", "metallic": 0.0, "roughness": 0.9},
    "ceiling_material": {"base_color": "#hex", "metallic": 0.0, "roughness": 0.95}
  },
  "objects": [
    {
      "id": "unique_id",
      "name": "Human Readable Name",
      "object_type": "furniture|fixture|architectural|decor",
      "position": {"x": 0.0, "y": 0.0, "z": 0.0},
      "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
      "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
      "dimensions": {"x": <width>, "y": <height>, "z": <depth>},
      "physics": {
        "body_type": "static|rigid|kinematic",
        "mass_kg": <float>,
        "friction": 0.5,
        "restitution": 0.1,
        "can_topple": false
      },
      "material": {"base_color": "#hex", "metallic": 0.0, "roughness": 0.5},
      "mesh_type": "primitive",
      "primitive_shape": "box|cylinder|sphere|capsule",
      "description": "Visual description for texture/mesh generation"
    }
  ],
  "lights": [
    {
      "id": "light_id",
      "name": "Light Name",
      "light_type": "point|spot|directional",
      "position": {"x": 0.0, "y": 2.5, "z": 0.0},
      "direction": {"x": 0.0, "y": -1.0, "z": 0.0},
      "color": "#hex",
      "color_temperature_k": 3000,
      "intensity": 2.0,
      "range_meters": 5.0,
      "spot_angle_deg": 45.0,
      "cast_shadows": true
    }
  ],
  "doors": [
    {
      "id": "door_id",
      "position": {"x": 0.0, "y": 0.0, "z": 0.0},
      "wall": "north|south|east|west",
      "width": 0.9,
      "height": 2.1,
      "swing_direction": "inward|outward"
    }
  ],
  "windows": [
    {
      "id": "window_id",
      "position": {"x": 0.0, "y": 0.0, "z": 0.0},
      "wall": "north|south|east|west",
      "width": 1.2,
      "height": 1.0,
      "sill_height": 0.9
    }
  ],
  "ambient_color": "#1a1a2e",
  "ambient_energy": 0.3
}

SPATIAL RULES:
- Y is UP. Floor is at y=0. Objects sit ON the floor (position.y = 0 for floor-standing items).
- Position is the CENTER BOTTOM of the object (feet on floor).
- Room origin (0,0,0) is the center of the floor.
- Walls are at: North = +Z, South = -Z, East = +X, West = -X
- Objects must not overlap. Leave clearance for walkways (min 0.8m).
- Doors must be on a wall and must not be blocked by furniture.
- Lights near ceiling should have y close to room height.
- Use realistic dimensions: a stool is ~0.4m wide, ~0.75m tall. A counter is ~1.0m tall, ~0.6m deep.

PHYSICS RULES:
- Heavy furniture (counters, cabinets): static body, mass irrelevant
- Movable furniture (stools, chairs): rigid body, realistic mass (5-15 kg)
- Small items (glasses, plates): rigid body, low mass (0.2-1 kg), can_topple=true
- Doors: rigid body with hinge (mass 10-20 kg)
- Fixtures (lamps, signs): static body, attached to ceiling/wall

Output ONLY valid JSON. No markdown, no comments, no explanation."""

```

### `src/pipeline.py`

```python
"""
The Living Room Pipeline - End-to-end world building.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from src.models import PipelineState, SceneConcept, SceneGraph, WorldSession
from src.orchestrator.interpreter import interpret_description
from src.canon_image.generator import generate_canon_image, generate_conditioned_canon
from src.floor_plan.builder import build_floor_plan
from src.floor_plan.renderer import render_blockout, render_floor_plan_svg
from src.scene_graph.builder import build_scene_graph
from src.asset_factory.mesh_generator import generate_all_meshes
from src.assembler.godot_project import assemble_godot_project
from src.workflow_provenance import (
    historical_profile_for,
    normalize_interface_version,
    profile_by_id,
    profile_for,
    snapshot_session,
)

OUTPUT_BASE = Path("output")


def _infer_legacy_interface_version(session_id: str) -> int:
    """Infer pre-provenance sessions from their earliest revision-log event."""
    earliest: tuple[str, int] | None = None
    for version in (3, 4, 5, 6, 7):
        log_path = OUTPUT_BASE / "logs" / f"v{version}.jsonl"
        if not log_path.exists():
            continue
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if f'"session_id":"{session_id}"' not in line:
                    continue
                try:
                    timestamp = str(json.loads(line).get("timestamp", ""))
                except json.JSONDecodeError:
                    continue
                candidate = (timestamp, version)
                if timestamp and (earliest is None or candidate < earliest):
                    earliest = candidate
    return earliest[1] if earliest else 7


class WorldBuilder:
    """Orchestrates the full world-building pipeline."""

    def __init__(self, session_id: Optional[str] = None, interface_version: int = 7):
        resolved_id = session_id or str(uuid.uuid4())[:8]
        self.output_dir = OUTPUT_BASE / resolved_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        session_path = self.output_dir / "session.json"
        if session_id and session_path.exists():
            payload = json.loads(session_path.read_text(encoding="utf-8"))
            version = normalize_interface_version(
                payload.get("interface_version") or _infer_legacy_interface_version(resolved_id)
            )
            profile_id = payload.get("workflow_profile_id")
            if payload.get("workflow_profile"):
                profile = profile_by_id(payload["workflow_profile"]["id"])
                if payload["workflow_profile"] != profile:
                    raise ValueError("Persisted workflow profile differs from its immutable contract")
            elif profile_id:
                profile = profile_by_id(profile_id)
            else:
                profile = historical_profile_for(version)
            payload.update(
                interface_version=version,
                workflow_profile_id=profile["id"],
                workflow_profile=profile,
            )
            self.session = WorldSession.model_validate(payload)
        else:
            version = normalize_interface_version(interface_version)
            profile = profile_for(version)
            self.session = WorldSession(
                session_id=resolved_id,
                interface_version=version,
                workflow_profile_id=profile["id"],
                workflow_profile=profile,
            )

    def save_session(self) -> None:
        """Persist resumable state plus an immutable workflow input/output snapshot."""
        snapshot_session(self.session, self.output_dir)
        (self.output_dir / "session.json").write_text(
            self.session.model_dump_json(indent=2), encoding="utf-8"
        )

    def _progress(self, msg: str):
        self.session.progress_messages.append(msg)
        print(f"[{self.session.session_id}] {msg}")

    async def step_interpret(self, description: str) -> SceneConcept:
        self.session.state = PipelineState.GENERATING_CONCEPT
        self.session.user_description = description
        self._progress("Interpreting your description...")
        concept = await interpret_description(description)
        self.session.scene_concept = concept
        self._progress(f"Scene concept ready: {concept.era}, {concept.mood}")
        return concept

    async def step_build_floor_plan(self, feedback: str = ""):
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        self.session.state = PipelineState.GENERATING_PLAN
        self._progress("Planning room dimensions, fixtures, furniture, circulation, and canon camera...")
        current = self.session.floor_plan if feedback else None
        plan, warnings = await build_floor_plan(
            self.session.user_description,
            self.session.scene_concept,
            current=current,
            feedback=feedback,
        )
        self.session.floor_plan = plan
        self.session.plan_revision += 1
        self.session.plan_warnings = warnings
        version = self.session.plan_revision
        json_path = self.output_dir / f"floor_plan_v{version}.json"
        svg_path = self.output_dir / f"floor_plan_v{version}.svg"
        blockout_path = self.output_dir / f"blockout_v{version}.png"
        json_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        render_floor_plan_svg(plan, svg_path)
        render_blockout(plan, blockout_path, self.session.scene_concept)
        self.session.floor_plan_path = str(svg_path)
        self.session.blockout_path = str(blockout_path)
        self.session.floor_plan_approved = False
        self._progress(f"Plan v{version} ready with {len(plan.items)} placed items and {len(plan.openings)} openings")
        return plan

    async def step_generate_image(self, attempt: int = 1) -> Path:
        self.session.state = PipelineState.GENERATING_IMAGE
        self._progress("Generating plan-conditioned canon image...")
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        workflow_context = {
            "interface_version": self.session.interface_version,
            "workflow_profile_id": self.session.workflow_profile_id,
            "workflow_profile": self.session.workflow_profile,
            "user_description": self.session.user_description,
            "floor_plan": self.session.floor_plan,
            "plan_revision": self.session.plan_revision,
        }
        if self.session.floor_plan_approved and self.session.blockout_path:
            generation = await generate_conditioned_canon(
                self.session.scene_concept,
                Path(self.session.blockout_path),
                self.session.session_id,
                attempt,
                workflow_context=workflow_context,
            )
        else:
            generation = await generate_canon_image(
                self.session.scene_concept,
                self.session.session_id,
                attempt,
                workflow_context=workflow_context,
            )
        image_path = generation.image_path
        self.session.canon_image_path = str(image_path)
        self.session.canon_provider = generation.provider
        for manifest in generation.manifests:
            manifest_path = str(manifest)
            if manifest_path not in self.session.generation_manifests:
                self.session.generation_manifests.append(manifest_path)
        self._progress(f"Canon image generated: {image_path.name}")
        return image_path

    async def step_build_scene_graph(self) -> SceneGraph:
        self.session.state = PipelineState.BUILDING_SCENE_GRAPH
        self._progress("Building spatial layout...")
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        scene = await build_scene_graph(self.session.scene_concept, self.session.floor_plan)
        self.session.scene_graph = scene
        self._progress(f"Scene graph ready: {len(scene.objects)} objects, {len(scene.lights)} lights, {len(scene.doors)} doors")
        return scene

    async def step_refine_world(self, feedback: str, render_path: Path) -> dict:
        """Compare a captured world render to the canon and apply one visual revision."""
        from src.scene_graph.refiner import refine_scene_graph

        if not self.session.scene_graph or not self.session.scene_concept:
            raise RuntimeError("Build a world before revising it")
        if not self.session.canon_image_path:
            raise RuntimeError("No canon image is available for comparison")
        self.session.state = PipelineState.REFINING_WORLD
        self._progress(f"Comparing world to canon: {feedback}")
        revised, report = await refine_scene_graph(
            self.session.scene_graph,
            self.session.scene_concept,
            Path(self.session.canon_image_path),
            render_path,
            feedback,
            self.session.floor_plan,
        )
        self.session.scene_graph = revised
        self.session.world_revision += 1
        self.session.render_paths.append(str(render_path))
        record = {"revision": self.session.world_revision, "feedback": feedback, **report}
        self.session.revision_history.append(record)
        (self.output_dir / f"scene_graph_v{self.session.world_revision}.json").write_text(
            revised.model_dump_json(indent=2), encoding="utf-8"
        )
        (self.output_dir / "revision_history.json").write_text(
            __import__("json").dumps(self.session.revision_history, indent=2), encoding="utf-8"
        )
        self._progress(f"World revision {self.session.world_revision} planned: {report['summary']}")
        return report

    def step_generate_assets(self) -> dict[str, Path]:
        self.session.state = PipelineState.GENERATING_ASSETS
        self._progress("Generating 3D assets...")
        if not self.session.scene_graph:
            raise RuntimeError("No scene graph")
        mesh_paths = generate_all_meshes(self.session.scene_graph, self.output_dir)
        self._progress(f"Generated {len(mesh_paths)} mesh assets")
        return mesh_paths

    def step_assemble(self, mesh_paths: dict[str, Path]) -> Path:
        self.session.state = PipelineState.ASSEMBLING_WORLD
        self._progress("Assembling Godot project...")
        if not self.session.scene_graph:
            raise RuntimeError("No scene graph")
        project_path = assemble_godot_project(self.session.scene_graph, self.output_dir, mesh_paths)
        self.session.output_path = str(project_path)
        self.session.state = PipelineState.READY
        self._progress(f"World ready at: {project_path}")
        return project_path

    async def build_full(self, description: str) -> Path:
        """Run the entire pipeline end-to-end."""
        try:
            await self.step_interpret(description)
            await self.step_build_floor_plan()
            self.session.floor_plan_approved = True
            await self.step_generate_image()
            await self.step_build_scene_graph()
            mesh_paths = self.step_generate_assets()
            return self.step_assemble(mesh_paths)
        except Exception as e:
            self.session.state = PipelineState.ERROR
            self.session.error = str(e)
            raise

```

### `src/scene_graph/__init__.py`

```python

```

### `src/scene_graph/builder.py`

```python
"""
Scene Graph Builder - Takes a SceneConcept and produces a complete SceneGraph.
"""

from __future__ import annotations

import sys

from src.floor_plan.models import FloorPlan
from src.models import (
    DoorSpec, MaterialProps, PhysicsBody, PhysicsProps,
    RoomShell, SceneGraph, SceneLight, SceneObject, Vec3, WindowSpec, SceneConcept,
)
from src.orchestrator.llm import generate_json
from src.orchestrator.prompts import SCENE_GRAPH_SYSTEM


async def build_scene_graph(concept: SceneConcept, floor_plan: FloorPlan | None = None) -> SceneGraph:
    """Generate appearance/physics while preserving approved plan geometry."""
    plan_context = floor_plan.model_dump_json() if floor_plan else "No approved plan supplied"
    user_prompt = f"""Build a scene graph for this space:

Era: {concept.era}
Mood: {concept.mood}
Palette: {concept.palette}
Architecture: {concept.architecture_notes}
Objects: {', '.join(concept.key_objects)}
Lighting: {concept.lighting_notes}

APPROVED FLOOR PLAN (authoritative): {plan_context}
Use every floor-plan item ID exactly. Room dimensions, item X/Z positions, footprints,
heights, rotations, doors, and windows must not change. Add materials, physics, and lighting."""

    data = await generate_json(system=SCENE_GRAPH_SYSTEM, user=user_prompt)
    scene = _parse_scene_graph(data)
    if floor_plan:
        _apply_plan_constraints(scene, floor_plan)
    _validate_scene(scene)
    return scene


def _parse_scene_graph(data: dict) -> SceneGraph:
    """Parse raw JSON dict into a validated SceneGraph model."""
    room = RoomShell(
        width=data["room"]["width"],
        depth=data["room"]["depth"],
        height=data["room"]["height"],
        floor_material=MaterialProps(**data["room"]["floor_material"]),
        wall_material=MaterialProps(**data["room"]["wall_material"]),
        ceiling_material=MaterialProps(**data["room"]["ceiling_material"]),
    )

    objects = []
    for obj_data in data.get("objects", []):
        obj = SceneObject(
            id=obj_data["id"],
            name=obj_data["name"],
            object_type=obj_data["object_type"],
            position=Vec3(**obj_data["position"]),
            rotation=Vec3(**obj_data.get("rotation", {"x": 0, "y": 0, "z": 0})),
            scale=Vec3(**obj_data.get("scale", {"x": 1, "y": 1, "z": 1})),
            dimensions=Vec3(**obj_data["dimensions"]),
            physics=PhysicsProps(
                body_type=PhysicsBody(obj_data["physics"]["body_type"]),
                mass_kg=obj_data["physics"]["mass_kg"],
                friction=obj_data["physics"].get("friction", 0.5),
                restitution=obj_data["physics"].get("restitution", 0.1),
                can_topple=obj_data["physics"].get("can_topple", False),
            ),
            material=MaterialProps(**obj_data["material"]),
            mesh_type=obj_data.get("mesh_type", "primitive"),
            primitive_shape=obj_data.get("primitive_shape", "box"),
            description=obj_data.get("description", ""),
        )
        objects.append(obj)

    lights = []
    for ld in data.get("lights", []):
        lights.append(SceneLight(
            id=ld["id"], name=ld["name"], light_type=ld["light_type"],
            position=Vec3(**ld["position"]),
            direction=Vec3(**ld.get("direction", {"x": 0, "y": -1, "z": 0})),
            color=ld["color"],
            color_temperature_k=ld.get("color_temperature_k", 4000),
            intensity=ld.get("intensity", 1.0),
            range_meters=ld.get("range_meters", 5.0),
            spot_angle_deg=ld.get("spot_angle_deg", 45.0),
            cast_shadows=ld.get("cast_shadows", True),
        ))

    doors = []
    for dd in data.get("doors", []):
        doors.append(DoorSpec(
            id=dd["id"], position=Vec3(**dd["position"]), wall=dd["wall"],
            width=dd.get("width", 0.9), height=dd.get("height", 2.1),
            swing_direction=dd.get("swing_direction", "inward"),
        ))

    windows = []
    for wd in data.get("windows", []):
        windows.append(WindowSpec(
            id=wd["id"], position=Vec3(**wd["position"]), wall=wd["wall"],
            width=wd.get("width", 1.2), height=wd.get("height", 1.0),
            sill_height=wd.get("sill_height", 0.9),
        ))

    return SceneGraph(
        name=data.get("name", "unnamed_scene"),
        description=data.get("description", ""),
        room=room, objects=objects, lights=lights, doors=doors, windows=windows,
        ambient_color=data.get("ambient_color", "#1a1a2e"),
        ambient_energy=data.get("ambient_energy", 0.3),
    )


def _validate_scene(scene: SceneGraph) -> None:
    """Validate spatial coherence."""
    half_w = scene.room.width / 2
    half_d = scene.room.depth / 2
    errors = []

    for obj in scene.objects:
        if abs(obj.position.x) > half_w + 0.5:
            errors.append(f"{obj.id}: x outside room")
        if abs(obj.position.z) > half_d + 0.5:
            errors.append(f"{obj.id}: z outside room")
        if obj.position.y < -0.1:
            errors.append(f"{obj.id}: below floor")

    if errors:
        print(f"[SceneGraph Validation] {len(errors)} warnings:", file=sys.stderr)
        for e in errors[:5]:
            print(f"  - {e}", file=sys.stderr)


def _apply_plan_constraints(scene: SceneGraph, plan: FloorPlan) -> None:
    """Make approved plan geometry authoritative over LLM-authored scene details."""
    scene.room.width = plan.room.width
    scene.room.depth = plan.room.depth
    scene.room.height = plan.room.height
    authored = {obj.id: obj for obj in scene.objects}
    constrained: list[SceneObject] = []
    palette = {
        "furniture": "#9b7048",
        "fixture": "#6b8582",
        "architectural": "#81769a",
        "decor": "#6f7e94",
    }
    for item in plan.items:
        obj = authored.get(item.id)
        if obj is None:
            obj = SceneObject(
                id=item.id,
                name=item.name,
                object_type=item.category,
                position=Vec3(),
                dimensions=Vec3(x=item.width, y=item.height, z=item.depth),
                physics=PhysicsProps(
                    body_type=PhysicsBody.STATIC if item.fixed else PhysicsBody.RIGID,
                    mass_kg=40.0 if item.fixed else 8.0,
                    can_topple=not item.fixed,
                ),
                material=MaterialProps(base_color=palette[item.category]),
                mesh_type="generated",
                primitive_shape="box",
                description=item.description,
            )
        obj.name = item.name
        obj.object_type = item.category
        obj.position = Vec3(x=item.x, y=item.elevation, z=item.z)
        obj.rotation = Vec3(x=0.0, y=item.rotation_deg, z=0.0)
        obj.scale = Vec3(x=1.0, y=1.0, z=1.0)
        obj.dimensions = Vec3(x=item.width, y=item.height, z=item.depth)
        obj.description = item.description or obj.description
        if item.fixed:
            obj.physics.body_type = PhysicsBody.STATIC
        constrained.append(obj)
    scene.objects = constrained
    scene.doors = []
    scene.windows = []
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    for opening in plan.openings:
        if opening.wall == "north":
            position = Vec3(x=opening.offset, y=0, z=half_d)
        elif opening.wall == "south":
            position = Vec3(x=opening.offset, y=0, z=-half_d)
        elif opening.wall == "east":
            position = Vec3(x=half_w, y=0, z=opening.offset)
        else:
            position = Vec3(x=-half_w, y=0, z=opening.offset)
        if opening.kind == "door":
            scene.doors.append(DoorSpec(id=opening.id, position=position, wall=opening.wall, width=opening.width, height=opening.height))
        else:
            scene.windows.append(WindowSpec(id=opening.id, position=position, wall=opening.wall, width=opening.width, height=opening.height, sill_height=opening.sill_height))

```

### `src/scene_graph/refiner.py`

```python
"""Canon-versus-render visual refinement using plan-safe appearance patches."""

from __future__ import annotations

import json
from pathlib import Path

from src.floor_plan.models import FloorPlan
from src.models import MaterialProps, SceneConcept, SceneGraph
from src.orchestrator.llm import generate_vision_json

REFINER_SYSTEM = """You are the visual quality director for an editable 3D interior.
Image 1 is the approved photoreal canon. Image 2 is the current 3D render. Compare them
and return a SMALL appearance-only JSON patch. Geometry is immutable: never propose room,
position, rotation, scale, dimension, opening, object count, or camera changes.
Return exactly: {"summary":string,"similarity_score":number 0..100,"changes":[string],
"object_materials":[{"id":string,"base_color":"#RRGGBB","metallic":0..1,
"roughness":0..1,"emission_color":"#RRGGBB or null","emission_strength":0..10}],
"room_materials":{"floor":material or null,"wall":material or null,"ceiling":material or null},
"lights":[{"id":string,"color":"#RRGGBB","intensity":number 0..20}],
"ambient_color":"#RRGGBB","ambient_energy":number 0..2}. Use only supplied IDs."""


async def refine_scene_graph(
    scene: SceneGraph,
    concept: SceneConcept,
    canon_path: Path,
    render_path: Path,
    feedback: str,
    floor_plan: FloorPlan | None = None,
) -> tuple[SceneGraph, dict]:
    manifest = {
        "style": {"era": concept.era, "mood": concept.mood, "palette": concept.palette},
        "room_materials": {
            "floor": scene.room.floor_material.model_dump(mode="json"),
            "wall": scene.room.wall_material.model_dump(mode="json"),
            "ceiling": scene.room.ceiling_material.model_dump(mode="json"),
        },
        "objects": [{"id": item.id, "name": item.name, "material": item.material.model_dump(mode="json")} for item in scene.objects],
        "lights": [{"id": item.id, "color": item.color, "intensity": item.intensity} for item in scene.lights],
        "ambient": {"color": scene.ambient_color, "energy": scene.ambient_energy},
        "plan": {"name": floor_plan.name, "room": floor_plan.room.model_dump()} if floor_plan else None,
    }
    prompt = f"User feedback: {feedback}\nCurrent visual manifest: {json.dumps(manifest, separators=(',', ':'))}\nReturn only the compact appearance patch."
    patch = await generate_vision_json(REFINER_SYSTEM, prompt, [str(canon_path), str(render_path)])
    revised = scene.model_copy(deep=True)
    _apply_patch(revised, patch)
    report = {
        "summary": str(patch.get("summary", "World appearance revised from visual feedback")),
        "similarity_score": _clamp(_number(patch.get("similarity_score"), 0), 0, 100),
        "changes": [str(item) for item in patch.get("changes", [])][:20],
    }
    return revised, report


def _apply_patch(scene: SceneGraph, patch: dict) -> None:
    objects = {item.id: item for item in scene.objects}
    for authored in patch.get("object_materials", [])[:64]:
        target = objects.get(str(authored.get("id", "")))
        if target:
            target.material = _material_patch(target.material, authored)
    room_targets = {
        "floor": scene.room.floor_material,
        "wall": scene.room.wall_material,
        "ceiling": scene.room.ceiling_material,
    }
    for key, authored in (patch.get("room_materials") or {}).items():
        if key in room_targets and isinstance(authored, dict):
            updated = _material_patch(room_targets[key], authored)
            if key == "floor":
                scene.room.floor_material = updated
            elif key == "wall":
                scene.room.wall_material = updated
            else:
                scene.room.ceiling_material = updated
    lights = {item.id: item for item in scene.lights}
    for authored in patch.get("lights", [])[:16]:
        target = lights.get(str(authored.get("id", "")))
        if target:
            target.color = _hex(authored.get("color"), target.color)
            target.intensity = _clamp(_number(authored.get("intensity"), target.intensity), 0, 20)
    scene.ambient_color = _hex(patch.get("ambient_color"), scene.ambient_color)
    scene.ambient_energy = _clamp(_number(patch.get("ambient_energy"), scene.ambient_energy), 0, 2)


def _material_patch(original: MaterialProps, authored: dict) -> MaterialProps:
    return MaterialProps(
        base_color=_hex(authored.get("base_color"), original.base_color),
        metallic=_clamp(_number(authored.get("metallic"), original.metallic), 0, 1),
        roughness=_clamp(_number(authored.get("roughness"), original.roughness), 0, 1),
        emission_color=_hex(authored.get("emission_color"), original.emission_color) if authored.get("emission_color") else original.emission_color,
        emission_strength=_clamp(_number(authored.get("emission_strength"), original.emission_strength), 0, 10),
    )


def _hex(value, fallback: str | None) -> str | None:
    text = str(value or "")
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return fallback


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

```

### `src/web/__init__.py`

```python

```

### `src/web/app.py`

```python
"""FastAPI interface for The Living Room."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.canon_image.generator import check_comfyui, get_image_provider
from src.models import PipelineState
from src.orchestrator.llm import LLM_MODEL, OLLAMA_URL
from src.pipeline import WorldBuilder
from src.web.event_log import append_event
from src.web.templates import get_index_html
from src.workflow_provenance import normalize_interface_version, workflow_profiles

app = FastAPI(title="The Living Room", version="0.7.0")
sessions: dict[str, WorldBuilder] = {}
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _request_version(request: Request) -> int:
    return normalize_interface_version(request.headers.get("x-app-version", "7"))


@app.middleware("http")
async def log_session_api(request: Request, call_next):
    """Log backend session-process operations under the calling UI revision."""
    path = request.url.path
    if not path.startswith("/api/session"):
        return await call_next(request)
    version = request.headers.get("x-app-version", "7")
    parts = path.split("/")
    session_id = parts[3] if len(parts) > 3 else None
    route = path.replace(session_id, "{session_id}") if session_id else path
    try:
        response = await call_next(request)
    except Exception:
        await asyncio.to_thread(append_event, OUTPUT_DIR, {
            "app_version": version, "session_id": session_id, "event_type": "process",
            "action": f"{request.method} {route}", "details": {"status": 500},
        })
        raise
    details: dict[str, object] = {"status": response.status_code}
    builder = sessions.get(session_id) if session_id else None
    if builder:
        details["state"] = builder.session.state.value
        if builder.session.progress_messages:
            details["progress"] = builder.session.progress_messages[-1]
    await asyncio.to_thread(append_event, OUTPUT_DIR, {
        "app_version": version, "session_id": session_id, "event_type": "process",
        "action": f"{request.method} {route}", "details": details,
    })
    return response


@app.post("/api/events")
async def record_event(request: Request):
    """Record a sanitized browser lifecycle, process, click, or test event."""
    try:
        record = await asyncio.to_thread(append_event, OUTPUT_DIR, await request.json())
        return {"logged": True, "timestamp": record["timestamp"], "app_version": record["app_version"]}
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


def _restore_builder(session_id: str) -> WorldBuilder | None:
    builder = sessions.get(session_id)
    if builder:
        return builder
    session_path = OUTPUT_DIR / session_id / "session.json"
    if not session_path.exists():
        return None
    builder = WorldBuilder(session_id=session_id)
    sessions[session_id] = builder
    return builder


def _error(builder: WorldBuilder | None, exc: Exception, status_code: int = 500):
    if builder:
        builder.session.state = PipelineState.ERROR
        builder.session.error = str(exc)
        builder.save_session()
    return JSONResponse({"error": str(exc)}, status_code=status_code)


def _plan_payload(builder: WorldBuilder, plan) -> dict:
    session_id = builder.session.session_id
    version = builder.session.plan_revision
    return {
        "session_id": session_id,
        "artifact": "plan",
        "state": builder.session.state.value,
        "concept": builder.session.scene_concept.model_dump(),
        "floor_plan": plan.model_dump(),
        "floor_plan_image": f"/api/session/{session_id}/floor_plan?v={version}",
        "blockout_image": f"/api/session/{session_id}/blockout?v={version}",
        "plan_revision": version,
        "warnings": builder.session.plan_warnings,
        "progress": builder.session.progress_messages,
        "interface_version": builder.session.interface_version,
        "workflow_profile_id": builder.session.workflow_profile_id,
        "workflow_url": f"/api/session/{session_id}/workflow",
    }


def _snapshot_payload(builder: WorldBuilder) -> dict:
    session = builder.session
    common = {
        "session_id": session.session_id,
        "state": session.state.value,
        "user_description": session.user_description,
        "progress": session.progress_messages,
        "interface_version": session.interface_version,
        "workflow_profile_id": session.workflow_profile_id,
        "workflow_url": f"/api/session/{session.session_id}/workflow",
    }
    if session.scene_graph and session.output_path:
        return {
            **common,
            "artifact": "world",
            "scene_graph": session.scene_graph.model_dump(),
            "download_url": f"/api/session/{session.session_id}/download",
        }
    if session.canon_image_path and session.scene_concept:
        attempt = len(list((OUTPUT_DIR / session.session_id).glob("canon_v*.png"))) or 1
        return {
            **common,
            "artifact": "canon",
            "concept": session.scene_concept.model_dump(),
            "canon_image": f"/api/session/{session.session_id}/canon_image?v={attempt}",
            "provider": session.canon_provider or get_image_provider(session.session_id),
            "attempt": attempt,
        }
    if session.floor_plan and session.scene_concept:
        return {**_plan_payload(builder, session.floor_plan), "user_description": session.user_description}
    return {**common, "artifact": "empty"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        version = int(request.query_params.get("v", "7"))
    except ValueError:
        version = 7
    return HTMLResponse(
        get_index_html(version),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/readiness")
async def readiness():
    comfy = await check_comfyui()
    ollama = {"ready": False, "model": LLM_MODEL}
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(f"{OLLAMA_URL.rstrip('/')}/api/tags")
            response.raise_for_status()
        names = [item.get("name", "") for item in response.json().get("models", [])]
        ollama.update(ready=any(name == LLM_MODEL or name.startswith(f"{LLM_MODEL}:") for name in names), available=names)
    except Exception as exc:
        ollama["reason"] = str(exc)
    return {"api": True, "comfyui": comfy, "ollama": ollama, "image_stack": "FLUX.2 Klein 4B FP8", "mesh_stack": "Procedural now · Hunyuan3D next"}


@app.get("/api/workflow/profiles")
async def get_workflow_profiles():
    return {"schema_version": 1, "profiles": workflow_profiles()}


@app.post("/api/session")
async def create_session(request: Request):
    builder = WorldBuilder(interface_version=_request_version(request))
    sessions[builder.session.session_id] = builder
    builder.save_session()
    return {
        "session_id": builder.session.session_id,
        "interface_version": builder.session.interface_version,
        "workflow_profile_id": builder.session.workflow_profile_id,
        "workflow_url": f"/api/session/{builder.session.session_id}/workflow",
    }


@app.get("/api/session/latest/snapshot")
async def latest_session_snapshot():
    if sessions:
        builder = next(reversed(sessions.values()))
        return _snapshot_payload(builder)
    candidates = list(OUTPUT_DIR.glob("*/session.json"))
    if not candidates:
        return JSONResponse({"error": "No active session"}, status_code=404)
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    builder = _restore_builder(latest.parent.name)
    return _snapshot_payload(builder)


@app.get("/api/session/{session_id}/snapshot")
async def session_snapshot(session_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return _snapshot_payload(builder)


@app.get("/api/session/{session_id}/workflow")
async def session_workflow(session_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    manifest_path = builder.output_dir / "workflow_manifest.json"
    if not manifest_path.exists():
        return JSONResponse({"error": "Workflow manifest not found"}, status_code=404)
    return JSONResponse(json.loads(manifest_path.read_text(encoding="utf-8")))


@app.post("/api/session/{session_id}/describe")
async def describe(session_id: str, request: Request):
    builder = _restore_builder(session_id)
    if not builder:
        builder = WorldBuilder(
            session_id=session_id, interface_version=_request_version(request)
        )
        sessions[session_id] = builder
    try:
        description = str((await request.json()).get("description", "")).strip()
        if not description:
            raise ValueError("Describe a room before generating")
        builder.session.error = None
        builder.session.progress_messages.clear()
        await builder.step_interpret(description)
        plan = await builder.step_build_floor_plan()
        builder.session.state = PipelineState.AWAITING_PLAN_APPROVAL
        builder.save_session()
        return _plan_payload(builder, plan)
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/floor_plan")
async def get_floor_plan(session_id: str):
    builder = _restore_builder(session_id)
    path = Path(builder.session.floor_plan_path) if builder and builder.session.floor_plan_path else None
    if not path or not path.exists():
        return JSONResponse({"error": "No floor plan for this session"}, status_code=404)
    return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/api/session/{session_id}/blockout")
async def get_blockout(session_id: str):
    builder = _restore_builder(session_id)
    path = Path(builder.session.blockout_path) if builder and builder.session.blockout_path else None
    if not path or not path.exists():
        return JSONResponse({"error": "No blockout for this session"}, status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/session/{session_id}/revise_plan")
async def revise_plan(session_id: str, request: Request):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.floor_plan:
        return JSONResponse({"error": "Session or plan not found"}, status_code=404)
    try:
        feedback = str((await request.json()).get("feedback", "")).strip()
        if not feedback:
            raise ValueError("Describe what should change in the plan")
        builder.session.error = None
        plan = await builder.step_build_floor_plan(feedback)
        builder.session.state = PipelineState.AWAITING_PLAN_APPROVAL
        builder.save_session()
        return _plan_payload(builder, plan)
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.post("/api/session/{session_id}/approve_plan")
async def approve_plan(session_id: str):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.floor_plan:
        return JSONResponse({"error": "Session or plan not found"}, status_code=404)
    try:
        builder.session.error = None
        builder.session.floor_plan_approved = True
        await builder.step_generate_image(attempt=1)
        builder.session.state = PipelineState.AWAITING_APPROVAL
        builder.save_session()
        return {
            "state": builder.session.state.value,
            "concept": builder.session.scene_concept.model_dump(),
            "canon_image": f"/api/session/{session_id}/canon_image?v=1",
            "provider": builder.session.canon_provider or get_image_provider(session_id),
            "progress": builder.session.progress_messages,
        }
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/canon_image")
async def get_canon_image(session_id: str):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.canon_image_path:
        return JSONResponse({"error": "No canon image for this session"}, status_code=404)
    path = Path(builder.session.canon_image_path)
    if not path.exists():
        return JSONResponse({"error": "Canon image file is missing"}, status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/session/{session_id}/approve")
async def approve_image(session_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    try:
        builder.session.error = None
        await builder.step_build_scene_graph()
        mesh_paths = await asyncio.to_thread(builder.step_generate_assets)
        project_path = await asyncio.to_thread(builder.step_assemble, mesh_paths)
        builder.save_session()
        return {
            "state": builder.session.state.value,
            "progress": builder.session.progress_messages,
            "project_path": str(project_path),
            "download_url": f"/api/session/{session_id}/download",
            "scene_graph": builder.session.scene_graph.model_dump(),
            "mesh_urls": {obj_id: f"/api/session/{session_id}/mesh/{obj_id}" for obj_id in mesh_paths},
        }
    except Exception as exc:
        return _error(builder, exc)


@app.post("/api/session/{session_id}/reject")
async def reject_image(session_id: str, request: Request):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.scene_concept:
        return JSONResponse({"error": "Session or concept not found"}, status_code=404)
    try:
        feedback = str((await request.json()).get("feedback", "")).strip()
        if not feedback:
            raise ValueError("Revision feedback is required")
        concept = builder.session.scene_concept
        revised_prompt = f"{concept.image_prompt}. Revision requirement: {feedback}. Preserve all other approved scene details."
        builder.session.scene_concept = concept.model_copy(update={"image_prompt": revised_prompt})
        attempt = len(list((OUTPUT_DIR / session_id).glob("canon_v*.png"))) + 1
        await builder.step_generate_image(attempt=attempt)
        builder.session.state = PipelineState.AWAITING_APPROVAL
        builder.save_session()
        return {"state": builder.session.state.value, "canon_image": f"/api/session/{session_id}/canon_image?v={attempt}", "provider": builder.session.canon_provider or get_image_provider(session_id), "attempt": attempt, "progress": builder.session.progress_messages}
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.post("/api/session/{session_id}/revise_world")
async def revise_world(session_id: str, request: Request):
    """Capture feedback as session memory, compare render to canon, and rebuild."""
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    try:
        form = await request.form()
        feedback = str(form.get("feedback", "")).strip()
        upload = form.get("render")
        if not feedback:
            raise ValueError("Describe what should change in the world")
        if upload is None or not hasattr(upload, "read"):
            raise ValueError("A current 3D render capture is required")
        content = await upload.read()
        if not content:
            raise ValueError("The 3D render capture was empty")
        revision = builder.session.world_revision + 1
        render_path = builder.output_dir / f"world_render_v{revision}.png"
        render_path.write_bytes(content)
        builder.session.error = None
        report = await builder.step_refine_world(feedback, render_path)
        mesh_paths = await asyncio.to_thread(builder.step_generate_assets)
        project_path = await asyncio.to_thread(builder.step_assemble, mesh_paths)
        builder.save_session()
        return {
            "state": builder.session.state.value,
            "revision": builder.session.world_revision,
            "report": report,
            "scene_graph": builder.session.scene_graph.model_dump(),
            "project_path": str(project_path),
            "download_url": f"/api/session/{session_id}/download?revision={revision}",
            "mesh_urls": {
                obj_id: f"/api/session/{session_id}/mesh/{obj_id}?revision={revision}"
                for obj_id in mesh_paths
            },
            "progress": builder.session.progress_messages,
        }
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/mesh/{obj_id}")
async def get_mesh(session_id: str, obj_id: str):
    mesh_path = OUTPUT_DIR / session_id / "meshes" / f"{obj_id}.glb"
    if not mesh_path.exists():
        return JSONResponse({"error": "Mesh not found"}, status_code=404)
    return FileResponse(mesh_path, media_type="model/gltf-binary")


@app.get("/api/session/{session_id}/scene_data")
async def get_scene_data(session_id: str):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.scene_graph:
        return JSONResponse({"error": "No scene built yet"}, status_code=404)
    return builder.session.scene_graph.model_dump()


@app.get("/api/session/{session_id}/download")
async def download_project(session_id: str):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.output_path:
        return JSONResponse({"error": "No project yet"}, status_code=404)
    zip_path = OUTPUT_DIR / session_id / "project"
    await asyncio.to_thread(shutil.make_archive, str(zip_path), "zip", builder.session.output_path)
    return FileResponse(f"{zip_path}.zip", media_type="application/zip", filename=f"living_room_{session_id}.zip")


@app.get("/api/session/{session_id}/status")
async def get_status(session_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return {"session_id": session_id, "state": builder.session.state.value, "progress": builder.session.progress_messages, "error": builder.session.error, "provider": builder.session.canon_provider or get_image_provider(session_id), "has_image": builder.session.canon_image_path is not None, "has_project": builder.session.output_path is not None, "interface_version": builder.session.interface_version, "workflow_profile_id": builder.session.workflow_profile_id, "workflow_url": f"/api/session/{session_id}/workflow"}

```

### `src/web/event_log.py`

```python
"""Append-only, privacy-conscious interface event logging."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_ALLOWED_TYPES = {"click", "process", "lifecycle", "test"}


def _text(value: object, limit: int) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ")[:limit]


def append_event(output_dir: Path, event: dict) -> dict:
    """Validate and append one event to its interface-version JSONL file."""
    raw_version = _text(event.get("app_version"), 2)
    version = raw_version if re.fullmatch(r"\d{1,2}", raw_version) else "unknown"
    event_type = _text(event.get("event_type"), 24)
    if event_type not in _ALLOWED_TYPES:
        raise ValueError("Unsupported event type")
    raw_session = _text(event.get("session_id"), 40)
    session_id = raw_session if re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", raw_session) else None
    raw_details = event.get("details") if isinstance(event.get("details"), dict) else {}
    details = {
        _text(key, 40): value if isinstance(value, (bool, int, float)) else _text(value, 200)
        for key, value in list(raw_details.items())[:16]
    }
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_version": version,
        "session_id": session_id,
        "event_type": event_type,
        "action": _text(event.get("action"), 120),
        "details": details,
    }
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with _LOCK, (log_dir / f"v{version}.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record

```

### `src/web/templates.py`

```python
"""HTML shell for The Living Room web application."""


def get_index_html(version: int = 7) -> str:
    if version <= 3:
        version = 3
    elif version == 4:
        version = 4
    elif version == 5:
        version = 5
    elif version == 6:
        version = 6
    else:
        version = 7
    refresh_control = '<button class="refresh-output" onclick="refreshOutput()">REFRESH OUTPUT ↻</button>' if version >= 4 else ""
    plan_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'floor\')"' if version >= 4 else ""
    blockout_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'blockout\')"' if version >= 4 else ""
    version_nav = (
        f'<nav class="version-nav" aria-label="Interface version">'
        f'<a class="{"selected" if version == 3 else ""}" href="/?v=3">V3 SIMPLE</a>'
        f'<a class="{"selected" if version == 4 else ""}" href="/?v=4">V4</a>'
        f'<a class="{"selected" if version == 5 else ""}" href="/?v=5">V5</a>'
        f'<a class="{"selected" if version == 6 else ""}" href="/?v=6">V6</a>'
        f'<a class="{"selected" if version == 7 else ""}" href="/?v=7">V7</a></nav>'
    )
    workspace_attr = ' id="workspace"' if version == 7 else ""
    splitter = (
        '<div id="workspaceSplitter" class="workspace-splitter" role="separator" tabindex="0" '
        'aria-label="Resize chat and preview panes" aria-orientation="vertical" '
        'aria-valuemin="25" aria-valuenow="44" aria-valuemax="70" aria-valuetext="44% chat width">'
        '<span aria-hidden="true"></span></div>'
        if version == 7 else ""
    )
    return (
        INDEX_HTML.replace("__VERSION__", str(version))
        .replace("__REFRESH_CONTROL__", refresh_control)
        .replace("__PLAN_STAGE_ATTR__", plan_attr)
        .replace("__BLOCKOUT_STAGE_ATTR__", blockout_attr)
        .replace("__VERSION_NAV__", version_nav)
        .replace("__WORKSPACE_ATTR__", workspace_attr)
        .replace("__WORKSPACE_SPLITTER__", splitter)
    )


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#090b10">
  <title>The Living Room · World Builder</title>
  <link rel="stylesheet" href="/static/styles.css?v=__VERSION__">
</head>
<body class="ui-v__VERSION__">
  <header class="topbar">
    <div class="brand"><span class="brand-mark">LR</span><div><strong>The Living Room</strong><small>Describe any interior. Walk into it.</small></div></div>
    <div class="status-strip">__VERSION_NAV__<span class="chip" id="apiChip">API · checking</span><span class="chip" id="llmChip">Ollama · checking</span><span class="chip" id="imageChip">FLUX.2 · checking</span><span class="chip" id="gpuChip">GPU · checking</span></div>
  </header>
  <main class="workspace"__WORKSPACE_ATTR__>
    <section class="conversation">
      <div class="intro"><span class="eyebrow">TEXT → PLAN → BLOCKOUT → CANON → WORLD</span><h1>Build a room you can enter.</h1><p>Describe one interior. Approve its metric layout and camera first, then render a plan-conditioned canon and build the world.</p></div>
      <div id="messages" class="messages" aria-live="polite"></div>
      <form id="composer" class="composer"><textarea id="input" rows="3" placeholder="A sunken 1970s lounge with walnut walls, amber lamps and rain against a wide window…"></textarea><button id="sendBtn" type="submit">Generate space plan <span>↗</span></button></form>
    </section>
    __WORKSPACE_SPLITTER__
    <aside class="stage">
      <div class="stage-head"><div><span class="eyebrow">LIVE OUTPUT · V__VERSION__</span><h2 id="stageTitle">Waiting for a description</h2></div><div class="stage-tools">__REFRESH_CONTROL__<span class="stage-state" id="stageState">IDLE</span></div></div>
      <nav class="stage-rail" aria-label="Build stages"><span class="stage-step active" data-stage="brief">BRIEF</span><span class="stage-step" data-stage="plan"__PLAN_STAGE_ATTR__>PLAN</span><span class="stage-step" data-stage="blockout"__BLOCKOUT_STAGE_ATTR__>BLOCKOUT</span><span class="stage-step" data-stage="canon">CANON</span><span class="stage-step" data-stage="world">WORLD</span><span class="stage-step" data-stage="compare">COMPARE</span></nav>
      <div id="stageBody" class="stage-body"><div class="empty-stage"><div class="wire-room"><i></i><i></i><i></i></div><p>Your plan, canon, and world preview will appear here.</p></div></div>
      <div id="stageFooter" class="stage-footer"><span>Orbit preview</span><span>Godot 4 export</span><span>Physics metadata</span></div>
    </aside>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
  <script>window.APP_VERSION=__VERSION__;</script>
  <script src="/static/app.js?v=__VERSION__"></script>
</body>
</html>"""

```

### `src/workflow_provenance.py`

```python
"""Immutable workflow profiles and complete per-session provenance snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

from PIL import Image

WORKFLOW_SCHEMA_VERSION = 1

_PROFILE_VALUES = (
    {
        "id": "v3-legacy@f982288",
        "interface_version": 3,
        "release_commit": "f982288",
        "stages": {
            "canon": {
                "conditioning": "none",
                "prompt": "concept.image_prompt",
                "provider_policy": "mock_only",
            }
        },
        "source": "git show f982288",
    },
    {
        "id": "v4-reference-full@5069761",
        "interface_version": 4,
        "release_commit": "5069761",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "concept.image_prompt",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "git show 5069761",
    },
    {
        "id": "v5-reference-partial@964da06",
        "interface_version": 5,
        "release_commit": "b929f57",
        "compatibility_fixes": ["964da06", "4ac67dd"],
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "base_prompt": "concept.image_prompt",
                "latent": "encoded_blockout",
                "sigma_schedule": "partial_after_step_4",
            }
        },
        "source": "git show 964da06",
        "status": "historical",
    },
    {
        "id": "v5-reference-full-r2",
        "interface_version": 5,
        "release_commit": None,
        "supersedes": "v5-reference-partial@964da06",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "Unreleased V5 quality probe retained for provenance",
        "status": "experimental_unreleased",
    },
    {
        "id": "v6-reference-full-r1",
        "interface_version": 6,
        "release_commit": None,
        "supersedes": "v5-reference-partial@964da06",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "V6 photoreal full-generation workflow",
        "status": "active",
    },
    {
        "id": "v7-reference-full-r1",
        "interface_version": 7,
        "release_commit": None,
        "supersedes": "v6-reference-full-r1",
        "stages": {
            "canon": {
                "conditioning": "reference_latent",
                "prompt": "enriched_concept_and_plan",
                "latent": "empty",
                "sigma_schedule": "full",
            }
        },
        "source": "V7 responsive resizable interface; V6 Canon contract retained",
        "status": "active",
    },
)
_PROFILE_DOCUMENTS = MappingProxyType(
    {value["id"]: json.dumps(value, sort_keys=True) for value in _PROFILE_VALUES}
)
_ACTIVE_PROFILE_IDS = MappingProxyType(
    {
        3: "v3-legacy@f982288",
        4: "v4-reference-full@5069761",
        5: "v5-reference-partial@964da06",
        6: "v6-reference-full-r1",
        7: "v7-reference-full-r1",
    }
)
_HISTORICAL_PROFILE_IDS = MappingProxyType(
    {
        3: "v3-legacy@f982288",
        4: "v4-reference-full@5069761",
        5: "v5-reference-partial@964da06",
        6: "v6-reference-full-r1",
        7: "v7-reference-full-r1",
    }
)


def normalize_interface_version(value: int | str | None) -> int:
    try:
        version = int(value or 7)
    except (TypeError, ValueError):
        version = 7
    if version <= 3:
        return 3
    if version == 4:
        return 4
    if version == 5:
        return 5
    if version == 6:
        return 6
    return 7


def profile_by_id(profile_id: str) -> dict:
    document = _PROFILE_DOCUMENTS.get(profile_id)
    if document is None:
        raise ValueError(f"Unknown workflow profile: {profile_id}")
    return json.loads(document)


def profile_for(interface_version: int) -> dict:
    return profile_by_id(_ACTIVE_PROFILE_IDS[normalize_interface_version(interface_version)])


def historical_profile_for(interface_version: int) -> dict:
    return profile_by_id(_HISTORICAL_PROFILE_IDS[normalize_interface_version(interface_version)])


def workflow_profiles() -> list[dict]:
    return [profile_by_id(profile_id) for profile_id in _PROFILE_DOCUMENTS]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_metadata(path: str | Path) -> dict:
    artifact = Path(path)
    result = {"path": str(artifact), "exists": artifact.exists()}
    if not artifact.exists() or not artifact.is_file():
        return result
    result.update({"bytes": artifact.stat().st_size, "sha256": _sha256(artifact)})
    try:
        with Image.open(artifact) as image:
            result.update(
                {
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                    "format": image.format,
                }
            )
    except Exception:
        pass
    return result


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def write_json(path: Path, payload: dict, *, exclusive: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as handle:
        json.dump(_jsonable(payload), handle, indent=2, ensure_ascii=False)
    return path


def _pinned_profile(session) -> dict:
    profile = dict(session.workflow_profile or {})
    if not profile:
        profile = profile_by_id(session.workflow_profile_id)
    canonical = profile_by_id(profile["id"])
    if profile != canonical or session.workflow_profile_id != canonical["id"]:
        raise ValueError("Session workflow profile does not match its immutable registry contract")
    if session.interface_version != canonical["interface_version"]:
        raise ValueError("Session interface version does not match its workflow profile")
    return canonical


def snapshot_session(session, output_dir: Path) -> Path:
    """Write one immutable full-state snapshot and refresh the mutable session index."""
    profile = _pinned_profile(session)
    existing_sequences = []
    for candidate in (output_dir / "workflow").glob("snapshot_*.json"):
        try:
            existing_sequences.append(int(candidate.name.split("_")[1]))
        except (IndexError, ValueError):
            continue
    sequence = max([session.workflow_snapshot_count, *existing_sequences], default=0) + 1
    session.workflow_snapshot_count = sequence
    path = output_dir / "workflow" / f"snapshot_{sequence:04d}_{session.state.value}.json"
    session.workflow_records.append(str(path))

    artifact_paths: list[Path] = []
    for candidate in output_dir.rglob("*"):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(output_dir)
        if relative.parts[0] == "workflow" or relative.name in {"session.json", "workflow_manifest.json"}:
            continue
        artifact_paths.append(candidate)

    snapshot = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "sequence": sequence,
        "session_id": session.session_id,
        "interface_version": session.interface_version,
        "workflow_profile": profile,
        "session": session.model_dump(mode="json"),
        "artifacts": [artifact_metadata(artifact) for artifact in sorted(artifact_paths)],
    }
    write_json(path, snapshot, exclusive=True)
    write_json(
        output_dir / "workflow_manifest.json",
        {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "session_id": session.session_id,
            "interface_version": session.interface_version,
            "workflow_profile": profile,
            "latest_snapshot": str(path),
            "records": list(session.workflow_records),
            "generation_manifests": list(session.generation_manifests),
        },
    )
    return path


def write_generation_manifest(
    output_dir: Path, attempt: int, mode: str, payload: dict
) -> Path:
    """Persist one immutable generation lifecycle record."""
    base = output_dir / "workflow" / f"canon_v{attempt}_{mode}"
    path = base.with_suffix(".json")
    sequence = 2
    while path.exists():
        path = Path(f"{base}_{sequence}.json")
        sequence += 1
    document = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "attempt": attempt,
        "mode": mode,
        **payload,
    }
    return write_json(path, document, exclusive=True)

```

### `src/web/static/app.js`

```javascript
const $ = selector => document.querySelector(selector);
const messages = $('#messages');
const input = $('#input');
const sendBtn = $('#sendBtn');
const stageBody = $('#stageBody');
const stageTitle = $('#stageTitle');
const stageState = $('#stageState');
const appVersion = Number(window.APP_VERSION || 7);
const initialParams = new URLSearchParams(window.location.search);
let sessionId = appVersion >= 4 ? initialParams.get('session') || localStorage.getItem('livingRoomSessionId') : null;
let busy = false;
let pollTimer = null;
let activeViewer = null;
let currentDescription = '';
let currentPlanData = null;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

async function fetchJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('X-App-Version', String(appVersion));
  const response = await fetch(url, {...options, headers});
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; }
  catch { data = {error: text || `HTTP ${response.status}`}; }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function logEvent(eventType, action, details = {}) {
  const payload = {app_version:appVersion, session_id:sessionId, event_type:eventType, action, details};
  fetch('/api/events', {
    method:'POST', headers:{'Content-Type':'application/json','X-App-Version':String(appVersion)},
    body:JSON.stringify(payload), keepalive:true,
  }).catch(() => {});
}

function chip(id, label, ready, detail = '') {
  const element = $(id);
  element.textContent = `${label} · ${ready ? 'ready' : detail || 'offline'}`;
  element.className = `chip ${ready ? 'ok' : 'bad'}`;
}

async function loadReadiness() {
  try {
    const data = await fetchJson('/api/readiness');
    chip('#apiChip', 'API', data.api);
    chip('#llmChip', 'Ollama', data.ollama.ready, data.ollama.model);
    chip('#imageChip', 'FLUX.2', data.comfyui.ready, data.comfyui.reason ? 'offline' : 'models missing');
    chip('#gpuChip', 'GPU', data.comfyui.ready, data.comfyui.device || 'unknown');
    if (data.comfyui.device) $('#gpuChip').textContent = data.comfyui.device.replace('cuda:0 ', '').split(':')[0];
  } catch { chip('#apiChip', 'API', false, 'offline'); }
}

function addMessage(type, html) {
  const element = document.createElement('article');
  element.className = `message ${type}`;
  element.innerHTML = html;
  messages.appendChild(element);
  messages.scrollTop = messages.scrollHeight;
  return element;
}

function setStage(name) {
  document.querySelectorAll('.stage-step').forEach(step => {
    step.classList.toggle('active', step.dataset.stage === name);
  });
  logEvent('process', 'stage_change', {stage:name});
}

function setBusy(value, label = 'Working') {
  busy = value;
  sendBtn.disabled = value;
  input.disabled = value;
  stageState.textContent = value ? 'WORKING' : 'READY';
  stageState.className = `stage-state ${value ? 'working' : 'ready'}`;
  if (value) stageTitle.textContent = label;
  logEvent('process', value ? 'work_started' : 'work_finished', {label});
}

function progress(label) {
  const element = addMessage('progress', `<span class="spinner"></span><strong>${escapeHtml(label)}</strong><div class="progress-log" id="progressLog"></div>`);
  startPolling();
  return element;
}

function startPolling() {
  stopPolling();
  if (!sessionId) return;
  pollTimer = setInterval(async () => {
    try {
      const data = await fetchJson(`/api/session/${sessionId}/status`);
      const log = $('#progressLog');
      if (log && data.progress?.length) log.textContent = data.progress.at(-1);
      if (data.state === 'error' && log) log.textContent = data.error || 'Build failed';
    } catch {}
  }, 900);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function rememberSession(id) {
  sessionId = id;
  if (appVersion < 4) return;
  localStorage.setItem('livingRoomSessionId', id);
  const url = new URL(window.location.href);
  url.searchParams.set('v', String(appVersion));
  url.searchParams.set('session', id);
  history.replaceState({}, '', url);
}

async function ensureSession() {
  if (!sessionId) {
    rememberSession((await fetchJson('/api/session', {method:'POST'})).session_id);
    logEvent('lifecycle', 'session_created');
  } else {
    rememberSession(sessionId);
  }
  return sessionId;
}

function showPlan(data) {
  currentPlanData = data;
  setStage('plan');
  stageTitle.textContent = `Floor plan v${data.plan_revision}`;
  stageState.textContent = 'REVIEW PLAN';
  stageState.className = 'stage-state ready';
  showPlanArtifact('floor');
  const plan = data.floor_plan;
  const warnings = (data.warnings || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
  addMessage('assistant', `<h3>Spatial plan ready · ${plan.room.width.toFixed(1)} × ${plan.room.depth.toFixed(1)}m</h3>
    <div class="concept-grid"><span><b>Style brief</b>${escapeHtml(data.concept.era)} · ${escapeHtml(data.concept.mood)}</span>
    <span><b>Layout</b>${plan.items.length} placed items · ${plan.openings.length} openings</span>
    <span><b>Canon camera</b>${plan.camera.fov_deg.toFixed(0)}° field of view</span>
    <span><b>Authority</b>Plan locks geometry; canon controls appearance</span></div>
    ${warnings ? `<ul class="plan-warnings">${warnings}</ul>` : ''}
    <div class="actions"><button class="primary" onclick="approvePlan()">Approve plan & render canon</button>
    ${appVersion >= 4 ? `<button class="secondary artifact-button" onclick="showPlanArtifact('floor')">View 2D plan</button>
    <button class="secondary artifact-button" onclick="showPlanArtifact('blockout')">View 3D blockout</button>` : ''}
    <button class="secondary" onclick="revisePlan()">Revise plan</button><button class="secondary" onclick="editDescription()">Edit brief</button>
    ${appVersion >= 4 ? '<button class="secondary" onclick="refreshOutput()">Refresh output</button>' : ''}</div>`);
}

function showPlanArtifact(kind) {
  if (!currentPlanData) return;
  setStage(kind === 'floor' ? 'plan' : 'blockout');
  const original = kind === 'floor' ? currentPlanData.floor_plan_image : currentPlanData.blockout_image;
  const source = appVersion >= 4 ? `${original}${original.includes('?') ? '&' : '?'}refresh=${Date.now()}` : original;
  const title = kind === 'floor' ? 'Authoritative floor plan' : 'Camera-matched blockout';
  const floorLabel = appVersion >= 4 ? '2D PLAN' : 'PLAN';
  const blockoutLabel = appVersion >= 4 ? '3D BLOCKOUT' : 'BLOCKOUT';
  stageTitle.textContent = title;
  stageBody.innerHTML = `<div class="plan-artifact"><img src="${source}" alt="${title}">
    <div class="plan-tabs"><button class="${kind === 'floor' ? 'selected' : ''}" onclick="showPlanArtifact('floor')">${floorLabel}</button>
    <button class="${kind === 'blockout' ? 'selected' : ''}" onclick="showPlanArtifact('blockout')">${blockoutLabel}</button></div></div>`;
}

async function restoreSession({manual = false} = {}) {
  if (appVersion < 4) return;
  try {
    const endpoint = sessionId ? `/api/session/${sessionId}/snapshot` : '/api/session/latest/snapshot';
    const data = await fetchJson(endpoint);
    rememberSession(data.session_id);
    logEvent('lifecycle', 'session_restored', {artifact:data.artifact, state:data.state, manual});
    currentDescription = data.user_description || currentDescription;
    messages.innerHTML = '';
    if (data.artifact === 'plan') {
      showPlan(data);
    } else if (data.artifact === 'canon') {
      showCanon(data);
    } else if (data.artifact === 'world') {
      addMessage('assistant', '<h3>Restored world</h3>The latest generated world and revision controls are ready.');
      buildViewer(data.scene_graph, data.download_url);
    }
  } catch (error) {
    if (manual) addMessage('error', `<strong>Refresh failed</strong><br>${escapeHtml(error.message)}`);
    if (error.message === 'Session not found') {
      localStorage.removeItem('livingRoomSessionId');
      sessionId = null;
    }
  }
}

async function refreshOutput() {
  if (busy || appVersion < 4) return;
  stageState.textContent = 'REFRESHING';
  stageState.className = 'stage-state working';
  await restoreSession({manual:true});
}

async function sendDescription() {
  const description = input.value.trim();
  if (!description || busy) return;
  currentDescription = description;
  addMessage('user', escapeHtml(description));
  input.value = '';
  setBusy(true, 'Planning the space');
  setStage('brief');
  let wait;
  try {
    await ensureSession();
    wait = progress('Interpreting the brief and producing a metric floor plan…');
    const data = await fetchJson(`/api/session/${sessionId}/describe`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({description})});
    wait.remove();
    showPlan(data);
  } catch (error) {
    wait?.remove();
    addMessage('error', `<strong>Planning failed</strong><br>${escapeHtml(error.message)}`);
    stageState.textContent = 'ERROR';
  } finally {
    stopPolling(); setBusy(false); input.focus();
  }
}

async function revisePlan() {
  if (busy) return;
  const feedback = prompt('What should change in the floor plan?');
  if (!feedback?.trim()) return;
  addMessage('user', `Plan revision: ${escapeHtml(feedback)}`);
  setBusy(true, 'Revising floor plan');
  let wait;
  try {
    wait = progress('Replanning while preserving unaffected geometry and IDs…');
    const data = await fetchJson(`/api/session/${sessionId}/revise_plan`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({feedback})});
    wait.remove(); showPlan(data);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>Plan revision failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

function editDescription() {
  input.value = currentDescription;
  input.focus();
}

async function approvePlan() {
  if (busy) return;
  setBusy(true, 'Rendering plan-conditioned canon');
  setStage('canon');
  let wait;
  try {
    wait = progress('Using the approved blockout and camera as FLUX.2 reference geometry…');
    const data = await fetchJson(`/api/session/${sessionId}/approve_plan`, {method:'POST'});
    wait.remove(); showCanon(data);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>Canon generation failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

function showCanon(data) {
  setStage('canon');
  stageTitle.textContent = 'Plan-conditioned canon';
  stageState.textContent = (data.provider || 'image').toUpperCase();
  stageState.className = 'stage-state ready';
  stageBody.innerHTML = `<div class="canon-wrap"><img src="${data.canon_image}" alt="Generated room concept"><div class="provider-tag">${escapeHtml(data.provider || 'unknown provider')}</div></div>`;
  addMessage('assistant', `<h3>${escapeHtml(data.concept.era)} · ${escapeHtml(data.concept.mood)}</h3>
    <div class="concept-grid"><span><b>Palette</b>${escapeHtml(data.concept.palette)}</span><span><b>Lighting</b>${escapeHtml(data.concept.lighting_notes)}</span></div>
    <div class="actions"><button class="primary" onclick="approveImage()">Approve canon & build world</button><button class="secondary" onclick="rejectImage()">Revise image</button></div>`);
}

async function approveImage() {
  if (busy) return;
  setBusy(true, 'Building spatial world');
  setStage('world');
  let wait;
  try {
    wait = progress('Applying the approved plan to scene graph, meshes, physics, and Godot…');
    const data = await fetchJson(`/api/session/${sessionId}/approve`, {method:'POST'});
    wait.remove();
    addMessage('assistant', `<h3>World ready</h3>${data.scene_graph.objects.length} plan-constrained objects · ${data.scene_graph.lights.length} lights · ${data.scene_graph.doors.length} doors.`);
    buildViewer(data.scene_graph, data.download_url);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>World build failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

async function rejectImage() {
  if (busy) return;
  const feedback = prompt('What should change visually? The approved geometry and camera remain locked.');
  if (!feedback?.trim()) return;
  addMessage('user', `Canon revision: ${escapeHtml(feedback)}`);
  setBusy(true, 'Revising canon');
  let wait;
  try {
    wait = progress('Re-rendering appearance while preserving approved blockout geometry…');
    const data = await fetchJson(`/api/session/${sessionId}/reject`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({feedback})});
    wait.remove();
    stageTitle.textContent = `Canon revision ${data.attempt}`;
    stageBody.innerHTML = `<div class="canon-wrap"><img src="${data.canon_image}" alt="Revised room concept"><div class="provider-tag">${escapeHtml(data.provider)}</div></div>`;
    addMessage('assistant', `<h3>Canon revision ${data.attempt} ready</h3><div class="actions"><button class="primary" onclick="approveImage()">Approve & build world</button><button class="secondary" onclick="rejectImage()">Revise again</button></div>`);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>Revision failed</strong><br>${escapeHtml(error.message)}`);
  } finally { stopPolling(); setBusy(false); }
}

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not capture the 3D render')), 'image/png'));
}

async function reviseWorld() {
  if (busy || !activeViewer) return;
  const feedback = prompt('What should change in the world? The approved floor plan remains locked.');
  if (!feedback?.trim()) return;
  let render;
  try { render = await canvasBlob(activeViewer.renderer.domElement); }
  catch (error) { addMessage('error', escapeHtml(error.message)); return; }
  addMessage('user', `World revision: ${escapeHtml(feedback)}`);
  setBusy(true, 'Comparing world, canon, and plan');
  setStage('compare');
  let wait;
  try {
    wait = progress('Qwen Vision is comparing the captured render to the canon; approved plan geometry is protected…');
    const form = new FormData();
    form.append('feedback', feedback.trim());
    form.append('render', render, `world-render-${Date.now()}.png`);
    const data = await fetchJson(`/api/session/${sessionId}/revise_world`, {method:'POST', body:form});
    wait.remove();
    const report = data.report || {};
    const changes = (report.changes || []).map(change => `<li>${escapeHtml(change)}</li>`).join('');
    addMessage('assistant', `<h3>World revision ${data.revision} · ${Number(report.similarity_score || 0).toFixed(0)}% similarity</h3>
      <p>${escapeHtml(report.summary || 'World revised')}</p>${changes ? `<ul>${changes}</ul>` : ''}
      <small>This is revision memory, not model-weight training.</small>`);
    buildViewer(data.scene_graph, data.download_url);
  } catch (error) {
    wait?.remove(); addMessage('error', `<strong>World revision failed</strong><br>${escapeHtml(error.message)}`);
    setStage('world');
  } finally { stopPolling(); setBusy(false); }
}

function disposeViewer() {
  if (!activeViewer) return;
  cancelAnimationFrame(activeViewer.frame);
  activeViewer.observer.disconnect();
  activeViewer.controls.dispose();
  activeViewer.renderer.dispose();
  activeViewer = null;
}

function color(value, fallback) {
  try { return new THREE.Color(value || fallback); }
  catch { return new THREE.Color(fallback); }
}

function material(props = {}, fallback = '#777b84') {
  return new THREE.MeshStandardMaterial({color:color(props.base_color, fallback), roughness:props.roughness ?? .75, metalness:props.metallic ?? 0, side:THREE.DoubleSide});
}

function initWorkspaceSplitter() {
  if (appVersion !== 7) return;
  const workspace = $('#workspace');
  const splitter = $('#workspaceSplitter');
  if (!workspace || !splitter) return;

  const storageKey = 'livingRoomV7ChatPanePx';
  const narrowLayout = window.matchMedia('(max-width: 900px)');
  let paneWidth = Number(localStorage.getItem(storageKey));
  let pointerId = null;

  const bounds = () => {
    const width = workspace.getBoundingClientRect().width;
    const divider = splitter.getBoundingClientRect().width || 11;
    const minimum = Math.max(320, width * .25);
    const maximum = Math.max(minimum, Math.min(width - divider - 360, width * .7));
    return {width, minimum, maximum};
  };
  const applyWidth = (requested, persist = true) => {
    if (narrowLayout.matches) {
      workspace.style.removeProperty('--chat-pane');
      splitter.setAttribute('aria-disabled', 'true');
      return;
    }
    splitter.setAttribute('aria-disabled', 'false');
    const {width, minimum, maximum} = bounds();
    const fallback = width * .44;
    paneWidth = Math.min(maximum, Math.max(minimum, Number.isFinite(requested) && requested > 0 ? requested : fallback));
    workspace.style.setProperty('--chat-pane', `${Math.round(paneWidth)}px`);
    const percent = Math.round((paneWidth / Math.max(width, 1)) * 100);
    splitter.setAttribute('aria-valuemin', String(Math.round((minimum / width) * 100)));
    splitter.setAttribute('aria-valuemax', String(Math.round((maximum / width) * 100)));
    splitter.setAttribute('aria-valuenow', String(percent));
    splitter.setAttribute('aria-valuetext', `${percent}% chat width`);
    if (persist) localStorage.setItem(storageKey, String(Math.round(paneWidth)));
  };
  const finishResize = inputMethod => {
    const width = workspace.getBoundingClientRect().width;
    logEvent('click', 'workspace_splitter_resized', {
      input_method:inputMethod,
      chat_percent:Math.round((paneWidth / Math.max(width, 1)) * 100),
    });
  };
  const reset = inputMethod => {
    paneWidth = workspace.getBoundingClientRect().width * .44;
    applyWidth(paneWidth);
    finishResize(inputMethod);
  };

  splitter.addEventListener('pointerdown', event => {
    if (event.button !== 0 || narrowLayout.matches) return;
    pointerId = event.pointerId;
    splitter.setPointerCapture(pointerId);
    document.body.classList.add('workspace-resizing');
    event.preventDefault();
  });
  splitter.addEventListener('pointermove', event => {
    if (event.pointerId !== pointerId) return;
    const left = workspace.getBoundingClientRect().left;
    applyWidth(event.clientX - left, false);
  });
  const endPointerResize = event => {
    if (event.pointerId !== pointerId) return;
    if (splitter.hasPointerCapture(pointerId)) splitter.releasePointerCapture(pointerId);
    pointerId = null;
    document.body.classList.remove('workspace-resizing');
    applyWidth(paneWidth);
    finishResize('pointer');
  };
  splitter.addEventListener('pointerup', endPointerResize);
  splitter.addEventListener('pointercancel', endPointerResize);
  splitter.addEventListener('keydown', event => {
    if (narrowLayout.matches) return;
    const step = event.shiftKey ? 40 : 10;
    if (event.key === 'ArrowLeft') paneWidth -= step;
    else if (event.key === 'ArrowRight') paneWidth += step;
    else if (event.key === 'Home') { event.preventDefault(); reset('keyboard'); return; }
    else return;
    event.preventDefault();
    applyWidth(paneWidth);
    finishResize('keyboard');
  });
  splitter.addEventListener('dblclick', () => reset('pointer'));
  narrowLayout.addEventListener('change', () => applyWidth(paneWidth));
  window.addEventListener('resize', () => applyWidth(paneWidth, false));
  applyWidth(paneWidth);
}

function buildViewer(graph, downloadUrl) {
  disposeViewer();
  setStage('world');
  stageTitle.textContent = graph.name || 'Generated world';
  stageState.textContent = '3D READY';
  stageState.className = 'stage-state ready';
  stageBody.innerHTML = `<canvas class="viewer"></canvas><div class="viewer-hud">DRAG orbit · WHEEL zoom · RIGHT-DRAG pan</div>
    <button class="revise-world" onclick="reviseWorld()">REVISE WORLD ↻</button><a class="download" href="${downloadUrl}">DOWNLOAD GODOT ↘</a>`;
  if (typeof THREE === 'undefined' || !THREE.OrbitControls) {
    stageBody.innerHTML = '<div class="empty-stage"><p>Three.js could not load. Check the browser network console.</p></div>';
    return;
  }
  const canvas = stageBody.querySelector('canvas');
  const room = graph.room;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#07090d');
  scene.fog = new THREE.Fog('#07090d', 12, 28);
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:false, preserveDrawingBuffer:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;
  renderer.outputEncoding = THREE.sRGBEncoding;
  const camera = new THREE.PerspectiveCamera(48, 1, .05, 100);
  camera.position.set(room.width * .82, room.height * .78, room.depth * 1.12);
  const controls = new THREE.OrbitControls(camera, canvas);
  controls.target.set(0, room.height * .38, 0);
  controls.enableDamping = true;
  controls.maxDistance = Math.max(room.width, room.depth) * 3;
  controls.minDistance = 1.5;
  const addBox = (name, size, position, meshMaterial, cast = false) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), meshMaterial);
    mesh.name = name; mesh.position.set(...position); mesh.castShadow = cast; mesh.receiveShadow = true; scene.add(mesh); return mesh;
  };
  addBox('Floor', [room.width,.08,room.depth], [0,-.04,0], material(room.floor_material,'#4e5055'));
  const wallMaterial = material(room.wall_material,'#bbb5aa');
  const halfWidth = room.width / 2, halfDepth = room.depth / 2, halfHeight = room.height / 2;
  addBox('Back wall',[room.width,room.height,.12],[0,halfHeight,-halfDepth-.06],wallMaterial);
  addBox('East wall',[.12,room.height,room.depth],[halfWidth+.06,halfHeight,0],wallMaterial);
  addBox('West wall',[.12,room.height,room.depth],[-halfWidth-.06,halfHeight,0],wallMaterial);
  const grid = new THREE.GridHelper(Math.max(room.width,room.depth), Math.ceil(Math.max(room.width,room.depth)*2), 0x313947, 0x1c222c);
  grid.position.y = .006; scene.add(grid);
  (graph.objects || []).forEach(object => {
    let geometry;
    const dimensions = object.dimensions;
    if (object.primitive_shape === 'cylinder') geometry = new THREE.CylinderGeometry(Math.min(dimensions.x,dimensions.z)/2,Math.min(dimensions.x,dimensions.z)/2,dimensions.y,24);
    else if (object.primitive_shape === 'sphere') geometry = new THREE.SphereGeometry(Math.max(dimensions.x,dimensions.y,dimensions.z)/2,24,16);
    else if (object.primitive_shape === 'capsule') geometry = new THREE.CapsuleGeometry(Math.min(dimensions.x,dimensions.z)/2,Math.max(0,dimensions.y-Math.min(dimensions.x,dimensions.z)),8,16);
    else geometry = new THREE.BoxGeometry(dimensions.x,dimensions.y,dimensions.z);
    const mesh = new THREE.Mesh(geometry, material(object.material));
    mesh.name = object.name;
    mesh.position.set(object.position.x, object.position.y + dimensions.y/2, object.position.z);
    mesh.rotation.set((object.rotation.x||0)*Math.PI/180,(object.rotation.y||0)*Math.PI/180,(object.rotation.z||0)*Math.PI/180);
    mesh.scale.set(object.scale?.x||1,object.scale?.y||1,object.scale?.z||1);
    mesh.castShadow = true; mesh.receiveShadow = true; scene.add(mesh);
  });
  (graph.doors || []).forEach(door => {
    const alongX = ['north','south'].includes(door.wall);
    const mesh = addBox(door.id, alongX?[door.width,door.height,.06]:[.06,door.height,door.width], [door.position.x,door.height/2,door.position.z], material({},'#71492f'), true);
    mesh.rotation.y = (door.wall === 'east' || door.wall === 'west') ? Math.PI/2 : 0;
  });
  (graph.windows || []).forEach(windowSpec => {
    const alongX = ['north','south'].includes(windowSpec.wall);
    const geometry = new THREE.PlaneGeometry(windowSpec.width,windowSpec.height);
    const glass = new THREE.MeshPhysicalMaterial({color:0x8fb9ce,transparent:true,opacity:.42,roughness:.18,metalness:.05,side:THREE.DoubleSide});
    const mesh = new THREE.Mesh(geometry,glass);
    mesh.position.set(windowSpec.position.x,windowSpec.sill_height+windowSpec.height/2,windowSpec.position.z);
    if (!alongX) mesh.rotation.y = Math.PI/2;
    scene.add(mesh);
  });
  scene.add(new THREE.HemisphereLight(0xb8c9df,0x251d17,.75));
  scene.add(new THREE.AmbientLight(color(graph.ambient_color,'#20283a'),Math.max(.35,graph.ambient_energy||.3)));
  (graph.lights || []).forEach(item => {
    const lightColor = color(item.color,'#ffd0a0');
    let light;
    if (item.light_type === 'directional') { light = new THREE.DirectionalLight(lightColor,item.intensity||1); light.target.position.set(item.direction?.x||0,item.direction?.y||0,item.direction?.z||0); scene.add(light.target); }
    else if (item.light_type === 'spot') light = new THREE.SpotLight(lightColor,(item.intensity||1)*1.5,item.range_meters||5,(item.spot_angle_deg||45)*Math.PI/180);
    else light = new THREE.PointLight(lightColor,(item.intensity||1)*1.6,item.range_meters||6);
    light.position.set(item.position.x,item.position.y,item.position.z); light.castShadow = !!item.cast_shadows; scene.add(light);
  });
  const resize = () => { const rect = stageBody.getBoundingClientRect(); camera.aspect = rect.width/Math.max(rect.height,1); camera.updateProjectionMatrix(); renderer.setSize(rect.width,rect.height,false); };
  const observer = new ResizeObserver(resize); observer.observe(stageBody); resize();
  const state = {renderer,controls,observer,scene,camera,frame:0}; activeViewer = state;
  const animate = () => { state.frame=requestAnimationFrame(animate); controls.update(); renderer.render(scene,camera); };
  animate();
}

$('#composer').addEventListener('submit', event => { event.preventDefault(); sendDescription(); });
input.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendDescription(); } });
document.addEventListener('click', event => {
  const target = event.target instanceof Element ? event.target.closest('button,a,[role="button"]') : null;
  if (!target) return;
  logEvent('click', 'control_activated', {
    element:target.tagName.toLowerCase(), element_id:target.id || '',
    label:(target.textContent || '').trim().slice(0, 80), href:target.getAttribute('href') || '',
    stage:target.dataset.stage || document.querySelector('.stage-step.active')?.dataset.stage || '',
  });
});
Object.assign(window, {approvePlan, revisePlan, editDescription, showPlanArtifact, refreshOutput, approveImage, rejectImage, reviseWorld, logEvent});
logEvent('lifecycle', 'app_loaded', {path:window.location.pathname});
loadReadiness();
setInterval(loadReadiness, 15000);
initWorkspaceSplitter();
if (appVersion >= 4) restoreSession();
input.focus();

```

### `src/web/static/styles.css`

```css
:root{--bg:#090b10;--panel:#0f131a;--panel2:#141923;--line:#252c38;--muted:#7f8998;--text:#eef2f7;--amber:#ffb45b;--green:#63d297;--red:#ff7272;--blue:#75a7ff}*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}body{height:100vh;overflow:hidden;background:radial-gradient(circle at 20% 0,#172031 0,transparent 34%),var(--bg)}button,textarea{font:inherit}.topbar{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid var(--line);background:rgba(9,11,16,.88);backdrop-filter:blur(18px)}.brand{display:flex;align-items:center;gap:12px}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border:1px solid #57452f;background:#1b1712;color:var(--amber);font-weight:800;font-size:12px;letter-spacing:.08em}.brand strong,.brand small{display:block}.brand strong{font-size:14px;letter-spacing:.02em}.brand small{font-size:11px;color:var(--muted);margin-top:3px}.status-strip{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}.chip{padding:6px 9px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font:600 10px/1.1 ui-monospace,monospace;letter-spacing:.03em;background:#0c1016}.chip.ok{border-color:#28523d;color:var(--green);background:#0d1a14}.chip.bad{border-color:#5c3030;color:var(--red);background:#1d1112}.workspace{height:calc(100vh - 72px);display:grid;grid-template-columns:minmax(430px,44%) minmax(0,56%)}.conversation{display:flex;flex-direction:column;min-height:0;border-right:1px solid var(--line)}.intro{padding:32px 34px 22px;border-bottom:1px solid var(--line)}.eyebrow{font:700 10px/1 ui-monospace,monospace;color:var(--amber);letter-spacing:.15em}.intro h1{margin:9px 0 8px;font-size:28px;line-height:1.1;letter-spacing:-.035em}.intro p{max-width:590px;margin:0;color:#9aa4b3;font-size:13px;line-height:1.55}.messages{flex:1;overflow:auto;padding:22px 34px;scrollbar-color:#333a46 transparent}.message{margin:0 0 14px;padding:14px 16px;border:1px solid var(--line);background:rgba(18,23,31,.76);font-size:13px;line-height:1.55}.message.user{margin-left:9%;border-color:#324a70;background:#121c2b}.message.error{border-color:#633638;background:#211315;color:#ffc2c2}.message.progress{border-color:#5d482d;background:#1d1811;color:#ffd49c}.message h3{margin:0 0 8px;font-size:13px;color:var(--amber)}

.concept-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.concept-grid span{padding:9px;background:#0d1117;color:#aab3c0}.concept-grid b{display:block;color:#657083;font:700 9px ui-monospace,monospace;text-transform:uppercase;margin-bottom:4px}.actions{display:flex;gap:8px;margin-top:12px}.actions button,.composer button{border:0;cursor:pointer;font-weight:700}.primary{padding:10px 13px;background:var(--amber);color:#17120c}.secondary{padding:10px 13px;background:#202733;color:#c8d0dc;border:1px solid #343d4b!important}.composer{padding:18px 34px 24px;border-top:1px solid var(--line);background:#0c0f15}.composer textarea{display:block;width:100%;resize:none;border:1px solid #303846;border-bottom:0;background:#11161e;color:var(--text);padding:14px;outline:none;line-height:1.45}.composer textarea:focus{border-color:#6f5737}.composer button{width:100%;display:flex;justify-content:space-between;padding:12px 14px;background:var(--amber);color:#16120d}.composer button:disabled{background:#373b42;color:#777;cursor:wait}.stage{display:flex;flex-direction:column;min-width:0;padding:24px;background:linear-gradient(145deg,#0d1118,#090b10)}.stage-head{height:55px;display:flex;align-items:flex-start;justify-content:space-between}.stage-head h2{font-size:16px;margin:6px 0 0}.stage-state{padding:6px 8px;border:1px solid var(--line);font:700 9px ui-monospace,monospace;color:var(--muted)}.stage-state.working{color:var(--amber);border-color:#634b2d}.stage-state.ready{color:var(--green);border-color:#27533c}.stage-body{position:relative;flex:1;min-height:0;border:1px solid var(--line);background:#07090d;overflow:hidden;box-shadow:0 25px 80px #0008}.stage-footer{height:38px;display:flex;align-items:flex-end;gap:18px;color:#5f6876;font:600 9px ui-monospace,monospace;text-transform:uppercase}.empty-stage{height:100%;display:grid;place-content:center;justify-items:center;color:var(--muted);font-size:12px}.wire-room{position:relative;width:150px;height:100px;border:1px solid #2e3745;transform:skewY(-8deg);margin-bottom:28px}.wire-room i{position:absolute;display:block;background:#2e3745}.wire-room i:nth-child(1){width:100px;height:1px;left:25px;top:49px}.wire-room i:nth-child(2){width:1px;height:70px;left:74px;top:15px}.wire-room i:nth-child(3){width:55px;height:28px;border:1px solid #3a4555;background:transparent;left:48px;top:50px}.canon-wrap{height:100%;display:grid;place-items:center;position:relative;background:#05070a}.canon-wrap img{width:100%;height:100%;object-fit:contain}.provider-tag{position:absolute;left:12px;bottom:12px;padding:7px 9px;background:#080b10df;border:1px solid #343c48;color:var(--green);font:700 9px ui-monospace,monospace}.viewer{width:100%;height:100%;display:block}.viewer-hud{position:absolute;left:12px;bottom:12px;padding:8px 10px;background:#080b10df;border:1px solid #313a47;color:#9aa5b5;font:600 9px ui-monospace,monospace}.download{position:absolute;right:12px;bottom:12px;padding:9px 11px;background:var(--amber);color:#17120c;text-decoration:none;font:800 10px ui-monospace,monospace}.spinner{display:inline-block;width:10px;height:10px;margin-right:8px;border:2px solid #8e6b3e;border-top-color:var(--amber);border-radius:50%;animation:spin .8s linear infinite}.progress-log{margin-top:7px;color:#a98962;font:11px ui-monospace,monospace}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:900px){body{height:auto;overflow:auto}.topbar{height:auto;min-height:72px;align-items:flex-start;padding:16px}.status-strip{max-width:55%}.workspace{height:auto;display:block}.conversation{min-height:650px;border-right:0}.stage{height:620px}.intro,.messages{padding-left:20px;padding-right:20px}.composer{padding:14px 20px}.concept-grid{grid-template-columns:1fr}}

.revise-world{position:absolute;right:146px;bottom:12px;padding:9px 11px;border:1px solid #576273;background:#151c26;color:#e5ebf3;cursor:pointer;font:800 10px ui-monospace,monospace}.revise-world:hover{border-color:var(--amber);color:var(--amber)}

.stage-rail{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;margin:0 0 12px;border:1px solid var(--line);background:var(--line)}.stage-step{position:relative;padding:8px 3px;text-align:center;background:#0c1016;color:#576171;font:700 8px ui-monospace,monospace;letter-spacing:.06em}.stage-step.active{background:#221b12;color:var(--amber)}.stage-step.active:after{content:"";position:absolute;left:25%;right:25%;bottom:0;height:2px;background:var(--amber)}.plan-artifact{height:100%;display:grid;place-items:center;background:#080b10}.plan-artifact img{width:100%;height:100%;object-fit:contain}.plan-tabs{position:absolute;left:12px;bottom:12px;display:flex;border:1px solid #35404d;background:#090d13}.plan-tabs button{padding:8px 11px;border:0;background:transparent;color:#7e8998;cursor:pointer;font:800 9px ui-monospace,monospace}.plan-tabs button.selected{background:var(--amber);color:#16120d}.plan-warnings{margin:10px 0 0;padding-left:19px;color:#d7a76a;font-size:11px}.message small{display:block;margin-top:9px;color:#727e8d}.message p{margin:6px 0}.message ul{margin:7px 0;padding-left:20px}.actions{flex-wrap:wrap}@media(max-width:900px){.stage-rail{grid-template-columns:repeat(3,1fr)}.revise-world{right:12px;bottom:52px}}

.version-nav{display:flex;border:1px solid var(--line);background:#0a0e14}.version-nav a{padding:6px 9px;color:#697586;text-decoration:none;font:700 9px ui-monospace,monospace}.version-nav a.selected{background:#252018;color:var(--amber)}.stage-tools{display:flex;align-items:flex-start;gap:7px}.refresh-output{padding:6px 9px;border:1px solid #4a5667;background:#151c26;color:#dce5ef;cursor:pointer;font:800 9px ui-monospace,monospace}.refresh-output:hover{border-color:var(--amber);color:var(--amber)}.ui-v4 .stage-step[role=button]{cursor:pointer}.ui-v4 .stage-step[role=button]:hover{background:#17202c;color:#d8e0eb}.ui-v4 .plan-tabs{left:14px;top:14px;bottom:auto;box-shadow:0 8px 28px #000a}.ui-v4 .plan-tabs button{min-width:104px;padding:12px 16px;font-size:11px}.ui-v4 .artifact-button{border-color:#5a6676!important;color:#eef3f8}.ui-v4 .stage-head{height:62px}@media(max-width:900px){.version-nav{order:-1}.stage-tools{flex-direction:column;align-items:flex-end}.refresh-output{padding:5px 7px}}

/* V7: dynamic viewport sizing and an accessible, user-resizable workspace split. */
.ui-v7{height:100dvh;min-height:0;overflow:hidden;display:grid;grid-template-rows:auto minmax(0,1fr)}
.ui-v7 .topbar{height:auto;min-height:72px}
.ui-v7 .workspace{--chat-pane:44%;height:auto;min-height:0;grid-template-columns:minmax(320px,var(--chat-pane)) 11px minmax(360px,1fr)}
.ui-v7 .conversation{min-width:0;min-height:0;border-right:0}
.ui-v7 .stage{min-width:0;min-height:0}
.workspace-splitter{position:relative;z-index:5;width:11px;min-width:11px;cursor:col-resize;touch-action:none;background:#0b0f15;border:0;border-left:1px solid var(--line);border-right:1px solid var(--line);outline:0}
.workspace-splitter span{position:absolute;left:3px;top:50%;width:3px;height:48px;transform:translateY(-50%);border-radius:3px;background:#3c4655;transition:background .15s,box-shadow .15s}
.workspace-splitter:hover span,.workspace-splitter:focus-visible span{background:var(--amber);box-shadow:0 0 0 3px #ffb45b24}
.workspace-splitter:focus-visible{box-shadow:inset 0 0 0 2px var(--amber)}
.workspace-resizing,.workspace-resizing *{cursor:col-resize!important;user-select:none!important}
@media(max-width:900px){
  .ui-v7{height:auto;min-height:100dvh;overflow:auto;display:block}
  .ui-v7 .topbar{align-items:flex-start;padding:16px}
  .ui-v7 .workspace{height:auto;min-height:0;display:block}
  .ui-v7 .conversation{height:auto;min-height:calc(100dvh - 110px)}
  .ui-v7 .messages{min-height:180px}
  .ui-v7 .stage{height:auto;min-height:max(420px,70dvh)}
  .ui-v7 .stage-body{min-height:300px}
  .workspace-splitter{display:none}
}
@media(min-width:901px) and (max-height:600px){
  .ui-v7 .intro{padding:16px 24px 12px}
  .ui-v7 .intro h1{margin:6px 0;font-size:24px}
  .ui-v7 .intro p{line-height:1.35}
  .ui-v7 .messages{min-height:0;padding:12px 24px}
  .ui-v7 .composer{padding:10px 24px 12px}
  .ui-v7 .composer textarea{padding:10px;line-height:1.3}
  .ui-v7 .composer button{padding:10px 12px}
}
@media(max-width:560px){
  .ui-v7 .topbar{gap:12px;flex-direction:column}
  .ui-v7 .status-strip{max-width:none;justify-content:flex-start}
  .ui-v7 .stage{padding:16px}
  .ui-v7 .stage-head{height:auto;min-height:72px;gap:10px}
  .ui-v7 .stage-footer{height:auto;min-height:38px;flex-wrap:wrap}
}

```
