# Implementation Plan: Unified World Pipeline

## Overview

This plan builds the complete conversation-to-walkable-world-with-toggle pipeline in dependency order. It is designed for marathon execution: each wave can run to completion before the next begins, but independent tasks within a wave can be parallelized. The pipeline reuses existing V14 infrastructure where complete (marked ✓REUSE) and builds new where required.

**Proving ground:** Danny's kitchenette — "a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain."

**Always-fresh rule:** The warehouse is populated after generation, never consulted before.

## Tasks

### Wave 0: Foundation — Data Models and Contracts

- [ ] 0.1 Create unified data models
  - Create `src/unified_pipeline/models.py` with frozen dataclasses: `Brief`, `ArtBible`, `MetricPlan`, `PlanRevision`, `CameraContract`, `BlockoutResult`, `SceneCanon`, `ObjectCanon`, `MeshApproval`, `WorldContract`, `GameOverlay`, `RealOverlay`, `ModeState`, `QualificationResult`
  - Each model SHALL include `to_dict()` / `from_dict()` for JSON round-trip
  - Brief SHALL contain: room_purpose, atmosphere, era, palette, object_manifest (list with stable UUIDs), game_concept, real_capabilities, success_criteria
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 19.1, 29.2_

- [ ] 0.2 Create WorldContract schema and canonical serialization
  - Create `src/unified_pipeline/world_contract.py` with deterministic JSON serialization, SHA-256 hashing, plan_revision binding, camera_hash binding, instance list, relationship graph, and hash verification
  - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 29.2_

- [ ] 0.3 Create CameraContract with immutability enforcement
  - Create `src/unified_pipeline/camera_contract.py` with frozen dataclass: position, target, up, vfov, aspect, near, far, raster (1024×768), stable hash, and `__setattr__` override raising on mutation
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 0.4 Create Mode system data models
  - Create `src/unified_pipeline/modes.py` with `GameOverlay` (rules, scoring, win_condition, object_role_bindings by UUID), `RealOverlay` (tool_bindings by UUID, read_only=True), `ModeState` (current_mode, persisted, announced), `ModeToggle` logic
  - _Requirements: 23.1, 23.2, 23.3, 24.1, 24.2, 24.3, 25.1, 25.2, 25.5_

- [ ] 0.5 Write round-trip property tests for all Wave 0 models
  - Test JSON serialization/deserialization for Brief, WorldContract, CameraContract, GameOverlay, RealOverlay
  - Verify CameraContract immutability (mutation raises)
  - Verify WorldContract hash stability (serialize twice → same hash)
  - _Requirements: 29.1, 29.2, 29.3, 29.4_

### Wave 1: Conversation and Brief Generation

- [ ] 1.1 Implement ConversationEngine
  - Create `src/unified_pipeline/conversation.py` with Ollama-backed conversational agent
  - Implement: opening prompt generation, user response interpretation, art direction proposal, GAME concept proposal, REAL capability proposal, steering loop, Brief extraction
  - Use structured output format requesting JSON Brief fields
  - Include 30-second total deadline with schema-correct fallback
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 2.1, 2.2, 2.3_

- [ ] 1.2 Implement DreamPreviewGenerator
  - Create `src/unified_pipeline/dream_preview.py` calling FLUX via ComfyUI with conversation-derived prompt
  - 15-second generation target, provisional labeling, multiple variant support
  - Record user preference for Art_Bible conditioning
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 1.3 Implement ArtBibleDeriver
  - Create `src/unified_pipeline/art_bible.py` extracting structured style rules from Brief + preferred Dream_Preview
  - Output: era_rules, material_palette, lighting_direction, color_palette, prop_style, era_exclusions
  - Immutability enforcement once Canon begins
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 1.4 Write tests for conversation → Brief → ArtBible flow
  - Test with Danny's kitchenette canonical prompt
  - Verify Brief completeness, UUID stability, Art_Bible era exclusions
  - _Requirements: 1.8, 2.5, 4.2_

### Wave 2: Spatial Planning and Blockout

- [ ] 2.1 Implement MetricPlanGenerator
  - Create `src/unified_pipeline/plan_generator.py` using constrained template selection
  - LLM selects template + parameters (not free-form coordinates)
  - Output: room dimensions, walls, openings (parameterized 0..1 along wall), object placements, circulation paths
  - Revision tracking with provenance
  - _Requirements: 5.1, 5.2, 5.5, 5.6_

- [ ] 2.2 Implement PlanValidator
  - Create `src/unified_pipeline/plan_validator.py` checking: room closure, opening validity (not too close to corners), object non-overlap, circulation clearance (≥0.6m), door swing clearance, dimensional plausibility
  - Auto-correction with new revision on failure
  - _Requirements: 5.3, 5.4, 5.5_

- [ ] 2.3 Implement BlockoutRenderer
  - Create `src/unified_pipeline/blockout_renderer.py` producing 3D blockout from validated Plan using CameraContract
  - Show walls with actual openings, object placeholders at correct scale
  - Output image at CameraContract raster dimensions (1024×768)
  - _Requirements: 7.1, 7.2, 7.3_

- [ ] 2.4 Implement approval gate for Plan/Blockout
  - Create `src/unified_pipeline/approval_gates.py` with `await_blockout_approval()` supporting approve/revise
  - Revision loop: feedback → new Plan revision → re-render → re-approve
  - Block downstream until approved
  - _Requirements: 7.3, 7.4, 7.5_

- [ ] 2.5 Write tests for Plan generation and validation
  - Test constrained template selection, validation rules (closure, overlap, circulation), revision tracking
  - Test Danny's kitchenette dimensions are plausible
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

### Wave 3: Canon Generation and Object Isolation

- [ ] 3.1 Implement SceneCanonGenerator
  - Create `src/unified_pipeline/canon_generator.py` using FLUX conditioned on Blockout + Art_Bible
  - Same CameraContract framing, object presence validation (present/missing/uncertain per manifest item)
  - Approval gate: approve/reject/regenerate
  - Hash binding to plan revision + camera hash
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

- [ ] 3.2 Implement ObjectIsolator (MVP — raw segmentation, no inpainting)
  - Create `src/unified_pipeline/object_isolator.py` with SAM segmentation producing RGBA Object_PNGs
  - Map each segment to Brief manifest UUID
  - Quality gate: reject empty masks or <1% coverage
  - Object_Canon = raw segmentation output (no inpainting completion for MVP)
  - Inpainting completion interface defined but body stubbed (post-MVP)
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [ ] 3.3 Implement RoomPlateGenerator
  - Create `src/unified_pipeline/room_plate.py` — Canon with all objects inpainted out (FLUX)
  - Used as texture source for room shell
  - _Requirements: 16.2_ (Room_Plate for shell texturing)

- [ ] 3.4 Write tests for Canon pipeline
  - Test object presence validation, hash binding, approval gate logic
  - Test Object_Canon quality gate (reject bad completions)
  - _Requirements: 8.3, 9.4_

### Wave 4: Mesh Generation and Materials (✓REUSE V14 infrastructure)

- [ ] 4.1 Wire existing Hunyuan3D generator for unified pipeline
  - Reuse `src/photo_pipeline/stages/hunyuan3d_v2_generator.py` — adapt interface to accept Object_Canon and output to unified models
  - Maintain: 50 steps, cfg=7.0, octree_resolution=384, 180s stall timeout, mesh validation (≥100 faces, ≥50 vertices, embedded texture, no ground sheet)
  - _Requirements: 10.3, 10.4, 10.6_

- [ ] 4.2 Wire existing Trellis2 generator as fallback
  - Reuse `src/photo_pipeline/stages/trellis2_generator.py` — adapt interface
  - _Requirements: 10.4_

- [ ] 4.3 Wire existing placeholder generator
  - Reuse `src/photo_pipeline/stages/placeholder_generator.py`
  - _Requirements: 10.5_

- [ ] 4.4 Implement MeshApprovalGate
  - Create `src/unified_pipeline/mesh_approval.py` with turntable preview generation and approve/reject/regenerate flow
  - Record rejection reasons, track retry count
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 4.5 Wire existing material processor (two-pass)
  - Reuse `src/photo_pipeline/stages/material_processor.py` — Pass 1 immediate, Pass 2 background
  - Hot-swap via WebSocket for V14+ viewers
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [ ] 4.6 Wire existing semantic labeler
  - Reuse `src/photo_pipeline/stages/semantic_labeler.py`
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [ ] 4.7 Wire existing VRAM manager
  - Reuse `src/photo_pipeline/vram_manager.py` — enforce sequential model loading
  - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

- [ ] 4.8 Wire existing depth estimator
  - Reuse `src/photo_pipeline/stages/depth_anything3.py`
  - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

- [ ] 4.9 Write integration tests for mesh generation pipeline
  - Test fallback chain (Hunyuan → Trellis2 → placeholder), VRAM ordering, approval gate
  - _Requirements: 10.3, 10.4, 10.5, 10.6_

### Wave 5: Room Shell, Architecture, and Physics

- [ ] 5.1 Wire existing room shell reconstructor
  - Reuse `src/photo_pipeline/stages/room_shell_reconstructor.py`
  - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7_

- [ ] 5.2 Implement FinishPass (procedural primitive placement — no CSG)
  - Create `src/unified_pipeline/finish_pass.py` placing pre-baked architectural primitives:
    - Door frames and window frames: box extrusions along opening edges
    - Baseboards: 2D profile swept along wall floor-line
    - Casing: 2D profile swept along opening perimeter
    - Outlets/switches: flat quad decals at era-appropriate heights
  - All placement parameterized along parent wall (0..1)
  - Respect Art_Bible era exclusions
  - Crown molding, wainscoting, vent covers: interface defined, body stubbed (post-MVP)
  - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7_

- [ ] 5.3 Wire existing physics classifier
  - Reuse `src/photo_pipeline/stages/physics_classifier.py` — density table, 25kg threshold, architectural override
  - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5_

- [ ] 5.4 Implement door hinge and interaction configuration
  - Create `src/unified_pipeline/door_physics.py` with hinge joint setup, swing limits, mass assignment
  - _Requirements: 18.6_

- [ ] 5.5 Wire existing physics settle pass
  - Reuse `src/photo_pipeline/stages/physics_settle.py` — 500 iterations or 5s, clamp within bounds
  - _Requirements: 18.7, 18.8_

- [ ] 5.6 Write tests for finish pass and physics
  - Test era-appropriate detail generation, door hinge configuration, settle pass convergence
  - _Requirements: 17.1, 17.5, 18.6, 18.7_

### Wave 6: WorldContract Assembly and Validation

- [ ] 6.1 Implement WorldContractAssembler
  - Create `src/unified_pipeline/assembler.py` binding: Plan revision, CameraContract hash, room shell, all instances (position/rotation/scale/asset/physics/material), lighting config, relationship graph
  - Deterministic serialization + SHA-256 hash
  - _Requirements: 19.1, 19.2, 19.3, 19.4_

- [ ] 6.2 Implement 3 MVP validation gates
  - Create `src/unified_pipeline/validation_gates.py` with:
    - `geometry_gate`: room closure, all walls connect, every object within bounds, camera in navigable space
    - `physics_gate`: every mesh has verified path + positive tri count, collisions match geometry, no floaters
    - `semantic_gate`: every object labeled, category valid, WorldContract hash stable
  - Each gate returns pass/fail + focused failure details
  - All 3 must pass before final publication
  - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5_

- [ ] 6.3 Implement event finality system
  - Create `src/unified_pipeline/event_system.py` with provisional/final event classification, hash binding for final events, ordering guarantees
  - _Requirements: 19.5, 19.6_

- [ ] 6.4 Write tests for WorldContract assembly and validation
  - Test hash stability, gate pass/fail logic, event ordering
  - _Requirements: 19.2, 19.3, 20.1, 20.4_

### Wave 7: Engine Compilation

- [ ] 7.1 Implement BrowserCompiler (Three.js)
  - Create `src/unified_pipeline/compilers/browser.py` deriving Three.js scene from WorldContract
  - GLTFLoader, PBR metallic-roughness, orbit + first-person controls, progressive SSE loading
  - _Requirements: 21.1, 21.4_

- [ ] 7.2 Implement GodotCompiler
  - Create `src/unified_pipeline/compilers/godot.py` emitting Godot 4 project: .tscn, physics bodies (RigidBody3D/StaticBody3D), first-person controller, grabbing, door hinges, lighting
  - _Requirements: 21.2, 21.4, 21.6_

- [ ] 7.3 Implement UPBGECompiler
  - Create `src/unified_pipeline/compilers/upbge.py` emitting .blend with player controller, character physics, logic bricks
  - _Requirements: 21.3, 21.4, 21.6_

- [ ] 7.4 Implement compiler selection and parity verification
  - Create `src/unified_pipeline/compilers/parity.py` verifying browser and engine payloads carry same WorldContract hash and equivalent derived values
  - _Requirements: 20.8, 21.4, 21.5_

- [ ] 7.5 Write tests for compilation and parity
  - Test each compiler produces valid output from a test WorldContract
  - Verify parity gate catches hash mismatches
  - _Requirements: 21.4, 20.8_

### Wave 8: Walkable World and Interaction

- [ ] 8.1 Implement first-person controller for browser
  - Extend V14 Three.js viewer with: WASD movement, mouse look (PointerLock), gravity, collision with static bodies, safe spawn position selection
  - _Requirements: 22.1, 21.6_

- [ ] 8.2 Implement object interaction system
  - Door swing (hinge physics), object grab/release (raycasting + constraint), push/topple (impulse application)
  - _Requirements: 22.2, 22.3, 22.4_

- [ ] 8.3 Implement lighting from WorldContract
  - Place light fixtures at contract positions, set intensity/color/temperature from Scene_Canon-derived values
  - Compute shadows from each light source
  - _Requirements: 22.5_

- [ ] 8.4 Implement Canon fidelity comparison
  - Create `src/unified_pipeline/canon_compare.py` comparing World render vs Scene_Canon, outputting green/amber/red verdict per region
  - _Requirements: 22.6_

- [ ] 8.5 Write interaction and walkability tests
  - Test spawn safety, collision response, door swing, grab/release
  - _Requirements: 22.1, 22.2, 22.3, 22.4_

### Wave 9: Mode Toggle and REAL Mode (GAME stubbed)

- [ ] 9.1 Implement GameOverlay data model and stub designer
  - Create `src/unified_pipeline/game_designer.py` — data model for GameOverlay (rules, scoring, win_condition, object_role_bindings by UUID)
  - Stub implementation: returns a suggested theme + mechanics based on Brief room_purpose, but NO functional gameplay logic
  - Full AI game design is a follow-on session
  - _Requirements: 23.1, 23.2, 23.3, 23.4_

- [ ] 9.2 Implement RealBinder (read-only surface display)
  - Create `src/unified_pipeline/real_binder.py` — tool connection system
  - MCP-server-compatible bindings, read-only v1, surface assignment by UUID
  - Implement one working binding: display static text/data on a bound surface
  - Budget/land earning logic is post-MVP
  - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5_

- [ ] 9.3 Implement ModeToggle (config switch)
  - Create `src/unified_pipeline/mode_toggle.py` — per-room state, persist, announce on entry
  - Toggle switches between REAL overlay (functional) and GAME overlay (stubbed/placeholder)
  - Verify: no visual change on switch, only behavior overlays swap
  - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6_

- [ ] 9.4 Write tests for toggle and REAL mode
  - Test mode persistence, toggle preserves visuals, REAL binding displays data
  - _Requirements: 25.2, 25.5, 24.4_

### Wave 10: Asset Warehouse and Orchestration

- [ ] 10.1 Wire existing Asset Warehouse for unified pipeline
  - Reuse `src/photo_pipeline/asset_warehouse.py` — adapt to accept unified models
  - Append-only, never consulted pre-generation, full metadata registry
  - Add game_properties and real_bindings fields to registry
  - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6_

- [ ] 10.2 Implement UnifiedOrchestrator
  - Create `src/unified_pipeline/orchestrator.py` wiring all waves into one pipeline
  - Stage order: Conversation → Brief → Dream → Plan → Validate → Camera → Blockout → Approve → Canon → Approve → Segment → Object_Canon → Approve → Mesh Gen → Approve → Materials → Depth → Room Shell → Finish → Physics → Settle → WorldContract → Gates → Compile → GAME Design → REAL Bind → Toggle Setup → Warehouse Catalog
  - SSE progress at each transition, per-object counters
  - No hard time cap, 180s stall detection only
  - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6_

- [ ] 10.3 Implement web routes for unified pipeline
  - Add routes: `GET /?v=16` (default), `POST /api/session/unified/start` (begins conversation), `POST /api/session/{id}/message` (conversation turn), `POST /api/session/{id}/approve/{stage}`, `GET /api/session/{id}/dream_preview`, `GET /api/session/{id}/blockout`, `GET /api/session/{id}/canon`, `GET /api/session/{id}/mesh/{object_id}`, SSE events, WS materials
  - Maintain V3-V15 routes unchanged
  - _Requirements: 28.1, 28.2, 28.3, 28.4_

- [ ] 10.4 Write orchestration integration tests
  - Test full pipeline with mocked GPU stages using Danny's kitchenette prompt
  - Verify stage ordering, approval gates block correctly, SSE events fire
  - _Requirements: 27.1, 27.2, 27.4, 28.4_

### Wave 11: Qualification

- [ ] 11.1 Implement qualification harness
  - Create `src/unified_pipeline/qualification.py` with: fresh session creation, canonical prompt injection ("Danny's kitchenette..."), all-stage traversal, gate verification, diagnostic recording
  - _Requirements: 30.1, 30.2, 30.3, 30.4_

- [ ] 11.2 Run qualification with Danny's kitchenette
  - Execute full pipeline from empty session
  - Inspect every stage: Brief correctness, Plan validity, Blockout spatial truth, Canon fidelity, mesh quality, physics behavior, walkability, GAME concept, REAL binding, toggle behavior
  - Record pass/fail per stage
  - _Requirements: 30.3, 30.4, 30.5, 30.6_

- [ ] 11.3 Fix any failures and re-qualify from fresh session
  - Failed sessions become diagnostic evidence only
  - Iterate until one complete clean pass
  - _Requirements: 30.5, 30.6_

- [ ] 11.4 Commit release
  - Stage relevant files, commit as `feat(web): release v16 unified-world-pipeline`
  - Provide: clean-version URL, fresh session URL, canonical prompt, commit hash
  - _Requirements: 30.7_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1", "0.2", "0.3", "0.4", "0.5"], "gate": "All models serialize/deserialize correctly" },
    { "id": 1, "tasks": ["1.1", "1.2", "1.3", "1.4"], "gate": "Danny's kitchenette produces valid Brief + Art_Bible" },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5"], "gate": "Plan validates, Blockout renders, approval blocks downstream" },
    { "id": 3, "tasks": ["3.1", "3.2", "3.3", "3.4"], "gate": "Canon approved, objects isolated with quality gate" },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"], "gate": "Meshes generate with fallback chain, materials apply two-pass" },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6"], "gate": "Room shell + finish + physics settle produces valid scene" },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.4"], "gate": "WorldContract hash-stable, all gates implemented" },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3", "7.4", "7.5"], "gate": "All compilers produce valid output from same contract" },
    { "id": 8, "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5"], "gate": "Player walks, interacts, lighting matches Canon" },
    { "id": 9, "tasks": ["9.1", "9.2", "9.3", "9.4"], "gate": "GAME persists, REAL displays data, toggle works" },
    { "id": 10, "tasks": ["10.1", "10.2", "10.3", "10.4"], "gate": "Full orchestration runs end-to-end with Danny prompt" },
    { "id": 11, "tasks": ["11.1", "11.2", "11.3", "11.4"], "gate": "One clean zero-state qualification pass committed" }
  ]
}
```

## Notes

- **Realistic timeline: 22-30 hours active coding across 2-3 marathon sessions.** The 6-12h estimate is retired.
- Tasks marked ✓REUSE leverage existing V14 infrastructure (already implemented and tested)
- Human approval gates are mandatory: Blockout (7.3), Canon (8.4), Mesh Shape (11.2), Final World QA (22.7)
- The always-fresh rule means Wave 4 mesh generation NEVER checks the warehouse — it generates, then catalogs
- GAME mode is STUBBED in the marathon (data model + suggested theme only); full implementation is post-MVP
- REAL mode ships with read-only surface binding (one working example)
- The qualification scene is Danny's kitchenette but the pipeline is scene-agnostic
- Existing property tests from V14 remain valid and should continue passing
- Finish pass uses procedural primitive placement (profile sweeps + decals), NOT CSG/boolean geometry
- MVP ships 3 validation gates (geometry, physics, semantic); remaining 5 are post-MVP

## Stub Table (marathon scope)

| Component | Marathon Delivery | Post-MVP |
|---|---|---|
| Conversation → Brief → Art_Bible | Full implementation | — |
| Dream Preview (FLUX resident) | Full implementation | — |
| Plan generator + validator | Full implementation | — |
| Blockout renderer | Full implementation | — |
| Canon generator + approval | Full implementation | — |
| Object Isolator | Raw SAM segmentation only | Amodal inpainting completion |
| Mesh generation chain | Full (Hunyuan → Trellis2 → placeholder) | — |
| Mesh approval gate | Full (turntable + approve/reject) | — |
| Materials (two-pass) | Full implementation | — |
| Finish pass | Baseboards, frames, casing, outlets (primitives) | Crown molding, wainscoting, vents |
| Physics + settle | Full implementation | — |
| WorldContract + hash | Full implementation | — |
| Validation gates | 3 core (geometry, physics, semantic) | 5 additional (provenance, circulation, material, asset, parity) |
| Engine compilation | Browser (Three.js) full; Godot/UPBGE wired | — |
| Walkable world + interactions | Full (WASD, doors, grab, physics) | — |
| Mode Toggle | Config switch (works) | — |
| GAME Designer | Stubbed (data model + theme suggestion) | Full AI game logic, persistence, remodel patching |
| REAL Binder | One working read-only binding | Full MCP integration, budget earning |
| Warehouse catalog | Full (append-only post-generation) | — |
