# Design: Unified World Pipeline

## Overview

This design defines the complete architecture for the Unified World Pipeline — a marathon-executable system that transforms natural-language conversation into a walkable, interactive 3D world with persistent GAME and REAL mode behaviors, a compounding asset warehouse, and engine-neutral output. It reuses proven V14 infrastructure only where it preserves the V15 authority lessons: the approved Metric_Plan owns space, neural outputs remain evidence or asset candidates, and no result is final before a gated canonical WorldContract exists.

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
│ Parametric Room + Finish + Physics + WorldContract + Gates          │
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
Authoritative Parametric Room + Finish Pass
    │
    ├── Optional aligned depth appearance/reference (non-colliding, never architectural authority)
    │
    ▼
Physics Classification + Settle
    │
    ▼
WorldContract Assembly ──► Solve Relationships ──► Canonical Hash
    │
    ▼
Structural Publication Gates (provenance, containment, overlap/openings/circulation, camera, asset, material)
    │
    ▼
Engine Compilation (browser + selected engine)
    │
    ▼
Compiler Parity Gate ──► Final Event Publication
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
Existing V14 infrastructure is reused only behind unified adapters and the corrected authority boundary:
- Hunyuan3D generator, Trellis2 generator, placeholder generator
- Depth estimator as optional evidence/appearance input only; never room geometry or collision authority
- Physics classifier and settle pass operating on Plan-derived architecture
- Material processor (two-pass), semantic labeler
- Asset warehouse as append-only catalog; no implicit pre-generation substitution
- Existing parametric Plan/solver/compiler path for authoritative room architecture

New infrastructure is built for:
- Conversation engine, Brief/Art_Bible generation
- Plan generator with constrained templates
- Blockout renderer
- Approval gate system
- Finish pass (architectural completion)
- WorldContract assembly with relationship solving and hash binding
- Structural and post-compile parity gates
- GAME/REAL/Toggle mode system
- Unified orchestrator with durable checkpoints, revision invalidation, and replay
- Resource arbiter covering Ollama, every ComfyUI model/service, and host RAM
- Cross-authority Canon honesty report

## Correctness Properties

### Property 1: Single spatial authority
**Validates: Requirements 5.3, 6.3, 19.1**
Only the approved normalized Metric_Plan may authorize room dimensions, openings, navigation, collision, object transforms, and camera derivation.

### Property 2: Evidence boundary
**Validates: Requirements 3.2, 8.2, 14.1, 16.1**
Dream, Canon, masks, depth, neural meshes, and room plates are provisional evidence or appearance candidates; they cannot rewrite solved geometry.

### Property 3: Mandatory solve chain
**Validates: Requirements 5.5, 6.3, 19.1, 19.2**
The order is solve → normalize → validate → immutable CameraContract → constrained SceneGraph → WorldContract → relationship solve → canonical serialization/hash. Any mutation creates a new revision and repeats validation.

### Property 4: Three-view identity
**Validates: Requirements 7.2, 8.2, 22.6**
Blockout/blueprint, Scene_Canon framing, and first-person world derive from the same Plan and CameraContract. Canon QA checks shell/openings, all objects, rotation-aware extents, dimensions/heights, overlap, palette/material intent, and prompt fidelity.

### Property 5: No consumer drift
**Validates: Requirements 19.3, 21.4**
Browser, Godot, and UPBGE never infer, clamp, rescale, rotate, offset, default, or normalize authoritative values independently. Approved assets are normalized exactly once.

### Property 6: Finality
**Validates: Requirements 19.4, 19.5, 19.6**
Pre-contract events are provisional. Final events require the exact nonzero revision, canonical hash, solved transforms, approved asset/material bindings, and passing gate report.

### Property 7: Stable identity
**Validates: Requirements 2.4, 9.3, 26.2**
UUID/category bindings survive segmentation, approval, regeneration, compilation, replay, and warehouse cataloging; list index and fuzzy noun matching are non-authoritative.

### Property 8: Measured-space transform
**Validates: Requirements 5.3, 6.2, 14.3**
Evidence alignment may use one camera-anchored uniform similarity transform plus translation-to-fit; per-axis or min-max normalization is forbidden.

## Durable Orchestration and Ownership

- Every stage writes an atomic checkpoint containing input hashes, output hashes, plan revision, external job ID, approval revision, and completion state.
- Resume reconciles external jobs and is idempotent; it never blindly resubmits pending work. A newer revision cancels stale responses and invalidates all dependent artifacts and approvals.
- One durable worker lease and one approval writer own each session. Watched-server reloads cannot erase ownership or create duplicate workers.
- Superseded artifacts are archived with lineage rather than overwritten or deleted. Rejections and unresolved flags block downstream stages until explicitly resolved.
- The resource arbiter serializes Ollama, Dream/Canon FLUX, SAM, edit/inpaint, depth, Hunyuan, Trellis, painting, and all ComfyUI instances; it owns unload, OOM recovery, stall handling, and host-RAM thresholds.

## Error Handling

- **Fail closed:** revision/hash mismatch, dual room authority, stale approval, invalid provenance, unsafe camera, forbidden overlap, opening/circulation failure, asset digest failure, material dishonesty, or compiler parity failure blocks final publication.
- **Degrade honestly:** unavailable optional depth reference, Pass 2 material delay, or non-authoritative visual enhancement failure may continue only with explicit degraded labels.
- **Diagnostic only:** failed sessions and partial qualification rounds are retained for debugging but never count as release evidence.

## Testing Strategy

- Fast tests cover canonical hash/revision rejection, CameraContract immutability, Plan containment/circulation, approval invalidation, fallback order, complete GPU arbitration, no-min-max alignment, exactly-once asset normalization, event ordering/replay, stale-response cancellation, and compiler drift.
- Integration tests exercise crash/restart at every external-job boundary and prove idempotent resume with no duplicate GPU submission.
- Qualification starts from a fresh zero-state session, records exact stage artifact hashes/source fingerprints, distinguishes mocked from live evidence, and restarts after any failure.

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
