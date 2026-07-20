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
