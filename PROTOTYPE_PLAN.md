# The Living Room — Prototype Plan

## Goal

Demonstrate the core loop end-to-end in the simplest possible vertical slice:

**User describes a room → AI generates a canon image → User approves → System builds a walkable 3D world with physics and lighting derived from that image.**

No toggle. No warehouse. No game mode. No real-mode tool connections. Just the foundational loop that proves the concept works.

---

## The Vertical Slice

**Scene:** A single small room — a 1950s diner counter with four stools, a pendant lamp, a door, and a window.

**Success Criteria:**
1. User types a description in a chat interface
2. AI interprets and generates a photorealistic canon image
3. User approves (or marks flaws and regenerates)
4. System produces a 3D scene in Godot with:
   - Architectural shell (walls, floor, ceiling, a door, a window)
   - Objects placed where the canon image shows them (counter, stools, lamp)
   - Physics on every object (stools can be knocked over, door swings)
   - Lighting matched to the canon image (warm pendant, ambient window light)
5. User walks through in first-person and interacts with objects

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    CONVERSATION UI                           │
│              (Web app — simple chat + image display)         │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR (Python)                      │
│         LLM Agent: interprets, plans, coordinates           │
│         Local model via Ollama or vLLM                       │
└──────┬──────────┬───────────────┬───────────────┬───────────┘
       │          │               │               │
       ▼          ▼               ▼               ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌─────────────┐
│  CANON   │ │  SCENE   │ │   ASSET      │ │   SCENE     │
│  IMAGE   │ │  GRAPH   │ │   FACTORY    │ │   ASSEMBLER │
│  GEN     │ │  BUILDER │ │              │ │             │
│          │ │          │ │  Per-object  │ │  Godot      │
│  FLUX    │ │  LLM →   │ │  3D gen via  │ │  project    │
│  (local) │ │  JSON    │ │  TripoSR /  │ │  builder    │
│          │ │  scene   │ │  Shap-E     │ │             │
└──────────┘ └──────────┘ └──────────────┘ └─────────────┘
```

---

## Phases

### Phase 0 — Foundation (Week 1)
**What:** Set up the development environment and prove each component works in isolation.

| Task | Tool | Output |
|------|------|--------|
| Install Ollama + pull a capable local LLM (Llama 3.1 70B or Mistral Large) | Ollama | LLM responds to prompts locally |
| Install ComfyUI + FLUX.1-dev model | ComfyUI | Can generate photorealistic interior images from text |
| Install TripoSR | Python/pip | Can reconstruct a 3D mesh from a single object image |
| Install Godot 4.x | Direct download | Can open and run a 3D scene with physics |
| Create a minimal Python project skeleton | Python | CLI that chains: prompt → image → mesh → Godot scene |

**Verification:** Each tool runs independently. `echo "a chrome diner stool" | pipeline` produces an image, then a mesh, then a Godot scene file you can open.

---

### Phase 1 — The Conversation + Canon Image (Week 2)
**What:** Build the front door. User describes → AI interprets → Canon image generated → User approves.

**Components:**
1. **Chat UI** — A web page (Python + FastAPI + HTMX or simple React). Text input, image display, approve/reject buttons, annotation overlay for marking flaws.
2. **Orchestrator Agent** — Python service using a local LLM. Takes the user's description and outputs:
   - A structured scene concept (era, mood, palette, key objects)
   - A detailed image generation prompt optimized for FLUX
3. **Canon Image Generator** — Calls FLUX (via ComfyUI API or diffusers pipeline) with the optimized prompt. Returns a photorealistic image.
4. **Approval Loop** — User sees image, can approve or annotate. If rejected, orchestrator adjusts prompt and regenerates.

**Data Flow:**
```
User: "A 1950s diner counter. Four chrome stools, checkered floor,
       warm pendant lamp, rain outside the window."
       
Orchestrator LLM outputs:
{
  "era": "1950s",
  "mood": "warm, nostalgic, rainy evening",
  "architecture": {
    "floor": "black and white checkered linoleum",
    "walls": "cream tile wainscoting, painted upper",
    "ceiling": "pressed tin tiles"
  },
  "objects": [
    {"name": "counter", "material": "formica with chrome edge"},
    {"name": "stool", "count": 4, "material": "chrome frame, red vinyl seat"},
    {"name": "pendant_lamp", "count": 1, "type": "industrial chrome"},
    {"name": "window", "type": "storefront glass", "condition": "rain outside"}
  ],
  "lighting": {
    "primary": "warm pendant over counter, ~3000K",
    "ambient": "cool blue-gray from rainy window",
    "accent": "none"
  },
  "image_prompt": "Interior photograph of a 1950s American diner counter..."
}
```

**Verification:** User can have a conversation, see a generated image, reject it with a note ("too bright, needs more shadow"), and get a revised image that addresses the note.

---

### Phase 2 — Scene Graph from Canon Image (Week 3)
**What:** Given an approved canon image + the structured scene concept, produce a complete spatial layout.

**Components:**
1. **Vision-Language Analysis** — Use a local VLM (LLaVA or similar via Ollama) to analyze the approved canon image:
   - Identify every object and its approximate position
   - Estimate room dimensions from perspective cues
   - Confirm lighting direction and intensity zones
2. **Scene Graph Builder** — The orchestrator LLM takes the VLM analysis + original scene concept and produces a precise scene graph:

```json
{
  "room": {
    "width": 6.0, "depth": 4.0, "height": 3.0,
    "floor_material": "checkered_linoleum",
    "wall_material": "cream_tile_lower_painted_upper",
    "ceiling_material": "pressed_tin"
  },
  "objects": [
    {
      "id": "counter_01",
      "type": "counter",
      "position": [3.0, 0.0, 1.5],
      "rotation": [0, 0, 0],
      "dimensions": [4.0, 1.0, 0.6],
      "physics": {"mass": 200, "static": true},
      "material": "formica_chrome_edge"
    },
    {
      "id": "stool_01",
      "type": "stool",
      "position": [1.5, 0.0, 2.0],
      "rotation": [0, 0, 0],
      "dimensions": [0.4, 0.75, 0.4],
      "physics": {"mass": 8, "static": false, "can_topple": true},
      "material": "chrome_red_vinyl"
    }
    // ... more objects
  ],
  "lights": [
    {
      "id": "pendant_01",
      "type": "point_light",
      "position": [3.0, 2.7, 1.5],
      "color": [255, 214, 170],
      "intensity": 800,
      "radius": 3.0
    },
    {
      "id": "window_ambient",
      "type": "directional",
      "direction": [0.2, -0.5, -0.8],
      "color": [180, 200, 220],
      "intensity": 200
    }
  ],
  "doors": [
    {
      "id": "door_01",
      "position": [0.0, 0.0, 2.0],
      "wall": "west",
      "swing": "inward",
      "physics": {"hinge_axis": "y", "mass": 15}
    }
  ]
}
```

**Verification:** The scene graph is valid JSON. Object positions don't overlap. Doors don't open into walls. Lights are positioned at ceiling height. A validation script checks all constraints.

---

### Phase 3 — Asset Factory (Week 4)
**What:** For each object in the scene graph, produce a textured 3D mesh.

**Strategy — Hybrid approach:**
1. **Primitive objects** (walls, floor, ceiling, counter) — Generated procedurally as parameterized meshes. A counter is a box with edge bevels. A wall is a plane with thickness. Fast, precise, physics-ready.
2. **Styled objects** (stools, lamp, door) — Generated via TripoSR or Shap-E from a reference image. The reference image is either:
   - Cropped/segmented from the canon image (using SAM/GroundingDINO), or
   - Generated specifically for that object by FLUX ("a chrome diner stool on white background, product photo")
3. **Post-processing** — Each mesh is:
   - Decimated to a reasonable poly count
   - UV-unwrapped (if not already)
   - Exported as .glb (Godot-compatible)
   - Tagged with physics properties from the scene graph

**Pipeline per object:**
```
scene_graph.objects[i]
    → generate reference image (FLUX, isolated object on white BG)
    → reconstruct 3D mesh (TripoSR)
    → decimate + clean (Open3D / trimesh)
    → export .glb
    → attach physics metadata
    → store in /assets/{object_id}.glb
```

**Verification:** Each .glb file opens in a 3D viewer. Meshes are watertight. Scale matches scene graph dimensions (within 10%). File sizes are under 5MB each.

---

### Phase 4 — Scene Assembly in Godot (Week 5-6)
**What:** Take the scene graph + generated assets and produce a runnable Godot project.

**Components:**
1. **Godot Project Generator** — A Python script that:
   - Creates a Godot 4 project directory structure
   - Generates a `.tscn` scene file programmatically
   - Places each asset at its scene graph position
   - Configures physics bodies (RigidBody3D for movable objects, StaticBody3D for fixed)
   - Adds collision shapes (auto-generated convex hulls or trimeshes)
   - Sets up lights (OmniLight3D, DirectionalLight3D) with colors/intensities from scene graph
   - Adds a first-person character controller (camera + collision + movement script)
   - Configures environment (WorldEnvironment with ambient light, fog if needed)

2. **Physics Configuration:**
   - Stools → RigidBody3D, mass=8kg, convex collision shape
   - Counter → StaticBody3D, trimesh collision
   - Door → HingeJoint3D connecting to wall
   - Floor/walls → StaticBody3D, simple box colliders

3. **Lighting Configuration:**
   - Pendant lamp → OmniLight3D at position, warm color, energy from scene graph
   - Window ambient → DirectionalLight3D, cool color, lower energy
   - Environment → subtle ambient to prevent pure-black shadows

4. **First-Person Controller:**
   - WASD movement, mouse look
   - Interact key (E) to push/grab objects
   - Basic grab/release mechanic for small physics objects

**Output:** A complete Godot project folder that opens in Godot Editor and runs immediately with `godot --path ./output_project`.

**Verification:** 
- Open the project in Godot. Press Play.
- Walk around the diner counter in first person.
- Bump a stool — it moves and rotates physically.
- Look at the pendant lamp — it casts warm light on the counter with visible shadow.
- Open the door — it swings on its hinge.
- The scene visually resembles the approved canon image in layout and mood.

---

### Phase 5 — End-to-End Integration (Week 7)
**What:** Wire everything together so the full loop runs from a single user interaction.

**Flow:**
```
1. User opens web UI
2. Types: "A 1950s diner counter, four chrome stools, pendant lamp, rainy window"
3. Sees canon image in ~30 seconds
4. Clicks "Approve"
5. Progress bar shows: "Building scene graph... Generating assets... Assembling world..."
6. After 5-10 minutes: "Your world is ready. [Launch] [Download Project]"
7. Clicks Launch → Godot window opens with the walkable diner
```

**Integration tasks:**
- API endpoints connecting UI → Orchestrator → Image Gen → Scene Graph → Asset Factory → Assembler
- Progress reporting (WebSocket or SSE) back to the UI
- Error handling at each stage with fallback (if TripoSR fails on an object, use a primitive placeholder)
- Final coherence check before launch (all assets exist, scene file valid, no missing references)

**Verification:** One person who has never seen the system can type a description and walk into a 3D world within 15 minutes total (including generation time), without touching any tool other than the chat UI and the approve button.

---

## Technology Stack (All Open Source)

| Layer | Tool | License | Role |
|-------|------|---------|------|
| LLM (orchestration) | Llama 3.1 70B via Ollama | Llama Community | Interprets descriptions, builds scene graphs, generates prompts |
| VLM (image analysis) | LLaVA-1.6 or Llama 3.2 Vision via Ollama | Open | Analyzes canon image for object positions and lighting |
| Image generation | FLUX.1-dev via ComfyUI or diffusers | Apache 2.0 (inference) | Generates photorealistic canon images |
| 3D reconstruction | TripoSR | MIT | Single-image → 3D mesh for styled objects |
| Mesh processing | trimesh / Open3D | MIT / BSD | Decimation, cleaning, collision shape generation |
| Segmentation | SAM 2 (Segment Anything) | Apache 2.0 | Isolate objects from canon image for individual reconstruction |
| 3D engine + physics | Godot 4.x | MIT | Runtime: rendering, physics, interaction, first-person control |
| Web UI | FastAPI + HTMX (or Svelte) | MIT / MIT | Chat interface, image display, approval |
| Agent framework | LangGraph or plain Python | MIT | Orchestration, state management, tool calling |
| Scene file generation | Custom Python → .tscn writer | — | Produces Godot scene files programmatically |

---

## What the Prototype Deliberately Omits

These are deferred to post-prototype iterations:

| Feature | Why deferred |
|---------|-------------|
| The Warehouse | Requires a persistence layer, asset normalization, and retrieval. Adds complexity without proving the core loop. |
| The Toggle (real/game modes) | Requires tool integration framework and game design AI. Separate concern from world-building. |
| Architectural completeness (molding, outlets, etc.) | The prototype proves the loop works. Fidelity increases later with better prompts and procedural detail generators. |
| Iteration without regeneration | Requires diffing scene graphs and selective asset replacement. Important but not MVP. |
| Multi-room scenes | The prototype handles one room. Expansion is additive. |
| Material PBR accuracy | Initial meshes will have basic textures. Physically-based material matching comes later. |
| Collaborative/multiplayer | Single user only in prototype. |
| Local-first deployment packaging | Prototype runs as dev services. Packaging as a single app comes later. |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| TripoSR produces low-quality meshes for complex objects | High | Medium | Fallback to procedural primitives for V1. Use FLUX to generate cleaner reference images (isolated object, white BG, multiple angles). |
| Scene graph positions don't match canon image | Medium | High | Use VLM depth estimation + perspective geometry. Accept approximate placement in V1 and let user nudge later. |
| FLUX can't run locally on available hardware | Medium | Medium | Use FLUX-schnell (smaller) or fall back to SD3.5. Or use cloud inference (Replicate/Together) temporarily while keeping the interface open-source. |
| Godot scene files are complex to generate programmatically | Low | Medium | Godot .tscn is a well-documented text format. Alternatively, use Godot's headless mode with GDScript to build scenes via API. |
| End-to-end takes too long (>30 min) | Medium | High | Parallelize asset generation. Cache common objects. Use simpler geometry for V1. Target: 10-15 min for a simple scene. |
| LLM produces inconsistent scene graphs | Medium | Medium | Structured output (JSON mode) + validation schema + retry with error feedback. |

---

## Timeline Summary

| Week | Phase | Deliverable |
|------|-------|-------------|
| 1 | Foundation | All tools installed and working independently |
| 2 | Conversation + Canon Image | Chat UI → canon image generation → approval loop working |
| 3 | Scene Graph | Approved image → validated spatial JSON with objects, lights, physics |
| 4 | Asset Factory | Scene graph → individual 3D meshes for each object |
| 5-6 | Scene Assembly | Scene graph + assets → runnable Godot project with physics + lighting |
| 7 | Integration | Full end-to-end: type → approve → walk into world |

**Total: 7 weeks to a working prototype.**

---

## First Demo Script

When the prototype is complete, this is the demo:

1. Open the web app. The screen shows a chat: *"Describe the room you want to build."*
2. Type: *"A small 1950s diner. Chrome counter with four red stools. One pendant lamp casting warm light. Checkered floor. Rain on the window. A swinging door to the kitchen."*
3. Wait ~30 seconds. A photorealistic image appears — a moody diner interior, exactly as described.
4. Click **Approve**.
5. Watch the progress: *"Analyzing scene... Building layout... Generating stool... Generating lamp... Generating counter... Assembling world... Adding physics... Configuring lights..."*
6. After 10 minutes: **"Your world is ready."**
7. Click **Launch**.
8. A Godot window opens. You're standing inside the diner.
9. Walk forward. Your footsteps echo.
10. Bump a stool. It spins on its base.
11. Push the kitchen door. It swings open on its hinge.
12. Look up. The pendant lamp glows warm. Your shadow falls on the checkered floor.
13. Look at the window. The cool blue light of a rainy evening fills the glass.

That's the prototype. One description. One image. One world.

---

## Next Steps After Prototype

Once the core loop works:

1. **Warehouse (v0.1)** — Save every generated asset with its physics/material metadata. On next build, check warehouse before generating.
2. **Iteration** — "Remove two stools, make it darker" modifies the scene graph and re-assembles without regenerating everything.
3. **Architectural detail** — Add procedural molding, baseboards, outlets, ceiling treatment based on era/style.
4. **Game mode** — AI proposes game mechanics for the space. Same objects, new behaviors.
5. **Real mode** — Connect one object to one real tool (desk → email, terminal → shell) as proof of concept.
6. **Multi-room** — Add a second room with a connecting passage.
7. **Quality** — Better meshes (multi-view reconstruction), PBR materials, baked lighting.
