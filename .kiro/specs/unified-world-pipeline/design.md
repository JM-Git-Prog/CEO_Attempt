# Design: Unified World Pipeline

## Overview

This design defines the complete architecture for the Unified World Pipeline — a marathon-executable system that transforms natural-language conversation into a walkable, interactive 3D world with persistent GAME and REAL mode behaviors, compounding asset warehouse, and engine-neutral output. It reuses existing V14 infrastructure where complete and builds new stages for conversation, planning, approval gates, architectural finishing, mode overlays, and unified orchestration.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CONVERSATION UI (Web)                              │
│         Chat interface + Dream Preview + Approval gates              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   UNIFIED ORCHESTRATOR                                │
│     Manages stage sequencing, approval gates, SSE progress           │
└──┬──────┬───────┬───────┬───────┬───────┬───────┬───────┬──────────┘
   │      │       │       │       │       │       │       │
   ▼      ▼       ▼       ▼       ▼       ▼       ▼       ▼
┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐
│CONVO ││DREAM ││ PLAN ││BLOCK ││CANON ││OBJECT││ MESH ││MATER │
│ENGINE││PREV  ││GENER ││ OUT  ││ GEN  ││ISOL  ││ GEN  ││IALS  │
└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘
   │      │       │       │       │       │       │       │
   ▼      ▼       ▼       ▼       ▼       ▼       ▼       ▼
┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐
│BRIEF ││ART   ││VALID ││CAMERA││APPROV││OBJ   ││APPROV││SEMAN │
│      ││BIBLE ││ATION ││CONTR ││ AL   ││CANON ││ AL   ││LABEL │
└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘└──────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WORLD ASSEMBLY                                     │
│  Room Shell + Finish Pass + Physics + WorldContract + Gates          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ENGINE COMPILATION                                 │
│         Browser (Three.js) │ Godot 4 │ UPBGE 0.50                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WALKABLE WORLD                                     │
│         First-person + Physics + Interaction + Lighting              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌──────────────────────┬─────┴─────┬──────────────────────────────────┐
│    GAME OVERLAY      │  TOGGLE   │    REAL OVERLAY                   │
│ Rules + Scoring +    │ Per-room  │ Tool bindings +                   │
│ Object roles         │ Persist   │ Read-only surfaces                │
└──────────────────────┴───────────┴──────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ASSET WAREHOUSE (append-only)                      │
│         Category dirs + JSON registry + Asset cards                   │
└─────────────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### Six Authorities (One Truth Per Concern)

| Authority | Controls | Never Controls |
|---|---|---|
| Dream_Preview | Immediate mood, style exploration | Final geometry, placement, collision |
| Metric_Plan | Dimensions, openings, circulation, placement | Surface appearance, atmosphere |
| Scene_Canon | Final appearance, atmosphere, object identity | Collision, architectural dimensions |
| Object_Canon | One object's approved appearance and identity | Final world position |
| Approved_Asset | Concrete mesh, materials, scale, provenance | Room-wide lighting, position |
| WorldContract | Final binding of everything | Independent creative reinterpretation |

## Stage Sequencing

```
Conversation
    │ (user steers)
    ▼
Brief + Art_Bible
    │ (structured intent locked)
    ▼
Dream_Preview ←── (provisional, non-authoritative)
    │
    ▼
Metric_Plan ──► Validate ──► Revise if needed
    │
    ▼
CameraContract (immutable from here)
    │
    ▼
Blockout ──► [HUMAN GATE: approve spatial layout]
    │
    ▼
Scene_Canon ──► [HUMAN GATE: approve appearance]
    │
    ▼
Object Isolation + Completion ──► [HUMAN GATE: pick Object_Canon]
    │
    ▼
Mesh Generation ──► [HUMAN GATE: approve shape]
    │
    ▼
Materials (Pass 1 immediate, Pass 2 background)
    │
    ▼
Depth + Room Shell + Finish Pass
    │
    ▼
Physics Classification + Settle
    │
    ▼
WorldContract Assembly ──► Hash + Bind
    │
    ▼
Validation Gates (provenance, containment, overlap, circulation, camera, asset, material, parity)
    │
    ▼
Engine Compilation (browser + selected engine)
    │
    ▼
Walkable World ──► [HUMAN GATE: final QA]
    │
    ▼
GAME Design + REAL Binding + Toggle Setup
    │
    ▼
Asset Warehouse Catalog (append-only, post-generation)
```

## Data Models

### Key Design Decisions

### Always-Fresh Generation
The warehouse is populated AFTER generation, never consulted BEFORE. This ensures:
- Every world is unique to its source conversation
- No stale asset substitution corrupts visual consistency
- The warehouse grows monotonically without affecting pipeline behavior
- Future warehouse-reuse optimization can be added as a profile without breaking the pipeline

### Human Gates
Five mandatory human approval points prevent expensive downstream work on bad foundations:
1. **Blockout** — catches spatial errors before Canon rendering
2. **Scene_Canon** — locks visual target before mesh generation
3. **Object_Canon** — ensures clean input per object
4. **Mesh Shape** — prevents painting bad geometry
5. **Final World QA** — user perception is law

### Mode Overlays
GAME and REAL are behavior layers on top of a stable WorldContract:
- Same geometry, materials, lighting, physics base
- Different interaction affordances, data bindings, scoring
- Toggle changes only what objects DO, never what they LOOK LIKE
- Persisted independently per room

### Constrained Template Selection
The LLM does not free-form emit metric coordinates. It selects from constrained templates:
- "kitchen, 3-4m × 3-5m, ceiling 2.4-2.7m, counter on long wall, entry on short wall"
- Parameters stay within declared ranges
- Validator catches the remaining edge cases
- This is the mitigation for unconstrained LLM spatial emission failures

### Reuse Strategy
Existing V14 infrastructure is reused where complete:
- Hunyuan3D generator, Trellis2 generator, placeholder generator
- VRAM manager, depth estimator, physics classifier, physics settle
- Material processor (two-pass), semantic labeler
- Asset warehouse, room shell reconstructor

New infrastructure is built for:
- Conversation engine, Brief/Art_Bible generation
- Plan generator with constrained templates
- Blockout renderer
- Approval gate system
- Finish pass (architectural completion)
- WorldContract assembly with hash binding
- Validation gates
- GAME/REAL/Toggle mode system
- Unified orchestrator

## File Structure

```
src/unified_pipeline/
├── __init__.py
├── models.py                    # All data models (Brief, Plan, WorldContract, etc.)
├── world_contract.py            # Canonical serialization + hashing
├── camera_contract.py           # Immutable camera projection
├── modes.py                     # GameOverlay, RealOverlay, ModeToggle
├── conversation.py              # Ollama-backed conversational agent
├── dream_preview.py             # FLUX Dream_Preview generation
├── art_bible.py                 # Style derivation from Brief + Dream
├── plan_generator.py            # Constrained template selection
├── plan_validator.py            # Spatial validation rules
├── blockout_renderer.py         # 3D blockout from validated Plan
├── canon_generator.py           # FLUX Canon conditioned on Blockout
├── object_isolator.py           # SAM segmentation + inpainting
├── room_plate.py                # Canon with objects removed
├── mesh_approval.py             # Turntable preview + approve/reject
├── finish_pass.py               # Architectural detail derivation
├── door_physics.py              # Hinge joints and door behavior
├── assembler.py                 # WorldContract assembly
├── validation_gates.py          # Pre-publication gates
├── event_system.py              # Provisional/final event classification
├── approval_gates.py            # Human approval gate infrastructure
├── canon_compare.py             # World vs Canon fidelity comparison
├── game_designer.py             # AI game concept generation
├── real_binder.py               # MCP-compatible tool bindings
├── mode_toggle.py               # Per-room toggle logic
├── orchestrator.py              # Full pipeline orchestration
├── qualification.py             # Zero-state qualification harness
├── compilers/
│   ├── __init__.py
│   ├── browser.py               # Three.js scene derivation
│   ├── godot.py                 # Godot 4 project emission
│   ├── upbge.py                 # UPBGE .blend emission
│   └── parity.py                # Cross-compiler hash verification
└── tests/
    ├── test_models.py
    ├── test_world_contract.py
    ├── test_plan_validator.py
    ├── test_validation_gates.py
    ├── test_modes.py
    ├── test_orchestrator.py
    └── test_qualification.py
```

## Integration with Existing Infrastructure

The unified pipeline imports from the existing `src/photo_pipeline/` package:
- `src/photo_pipeline/stages/hunyuan3d_v2_generator.py`
- `src/photo_pipeline/stages/trellis2_generator.py`
- `src/photo_pipeline/stages/placeholder_generator.py`
- `src/photo_pipeline/stages/material_processor.py`
- `src/photo_pipeline/stages/semantic_labeler.py`
- `src/photo_pipeline/stages/depth_anything3.py`
- `src/photo_pipeline/stages/room_shell_reconstructor.py`
- `src/photo_pipeline/stages/physics_classifier.py`
- `src/photo_pipeline/stages/physics_settle.py`
- `src/photo_pipeline/vram_manager.py`
- `src/photo_pipeline/asset_warehouse.py`
- `src/photo_pipeline/comfyui_client.py`

These are imported as dependencies, not duplicated. The unified pipeline provides the orchestration and new stages around them.
