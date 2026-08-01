# Implementation Plan: Unified World Pipeline

## Overview

This plan builds the complete conversation-to-walkable-world-with-toggle pipeline in dependency order. It is designed for marathon execution: each wave can run to completion before the next begins, but independent tasks within a wave can be parallelized. The pipeline reuses existing V14 infrastructure where complete (marked ✓REUSE) and builds new where required.

**Proving ground:** Danny's kitchenette — "a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain."

**Always-fresh rule:** The warehouse is populated after generation, never consulted before.

## Tasks

### Wave 0: Foundation — Data Models and Contracts

- [x] 0.1 Create unified data models
  - Create `src/unified_pipeline/models.py` with frozen dataclasses: `Brief`, `ArtBible`, `MetricPlan`, `PlanRevision`, `CameraContract`, `BlockoutResult`, `SceneCanon`, `ObjectCanon`, `MeshApproval`, `WorldContract`, `GameOverlay`, `RealOverlay`, `ModeState`, `QualificationResult`
  - Each model SHALL include `to_dict()` / `from_dict()` for JSON round-trip
  - Brief SHALL contain: room_purpose, atmosphere, era, palette, object_manifest (list with stable UUIDs), game_concept, real_capabilities, success_criteria
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 19.1, 29.2_

- [x] 0.2 Create WorldContract schema and canonical serialization
  - Create `src/unified_pipeline/world_contract.py` with deterministic JSON serialization, SHA-256 hashing, plan_revision binding, camera_hash binding, instance list, relationship graph, and hash verification
  - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 29.2_

- [x] 0.3 Create CameraContract with immutability enforcement
  - Create `src/unified_pipeline/camera_contract.py` with frozen dataclass: position, target, up, vfov, aspect, near, far, raster (1024×768), stable hash, and `__setattr__` override raising on mutation
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 0.4 Create Mode system data models
  - Create `src/unified_pipeline/modes.py` with `GameOverlay` (rules, scoring, win_condition, object_role_bindings by UUID), `RealOverlay` (tool_bindings by UUID, read_only=True), `ModeState` (current_mode, persisted, announced), `ModeToggle` logic
  - _Requirements: 23.1, 23.2, 23.3, 24.1, 24.2, 24.3, 25.1, 25.2, 25.5_

- [x] 0.5 Write round-trip property tests for all Wave 0 models
  - Test JSON serialization/deserialization for Brief, WorldContract, CameraContract, GameOverlay, RealOverlay
  - Verify CameraContract immutability (mutation raises)
  - Verify WorldContract hash stability (serialize twice → same hash)
  - _Requirements: 29.1, 29.2, 29.3, 29.4_

### Wave 1: Conversation and Brief Generation

- [x] 1.1 Implement ConversationEngine
  - Create `src/unified_pipeline/conversation.py` with Ollama-backed conversational agent
  - Implement: opening prompt generation, user response interpretation, art direction proposal, GAME concept proposal, REAL capability proposal, steering loop, Brief extraction
  - Use structured output format requesting JSON Brief fields
  - Include 30-second total deadline with schema-correct fallback
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 2.1, 2.2, 2.3_

- [x] 1.2 Implement DreamPreviewGenerator
  - Create `src/unified_pipeline/dream_preview.py` calling FLUX via ComfyUI with conversation-derived prompt
  - 15-second generation target, provisional labeling, multiple variant support
  - Record user preference for Art_Bible conditioning
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 1.3 Implement ArtBibleDeriver
  - Create `src/unified_pipeline/art_bible.py` extracting structured style rules from Brief + preferred Dream_Preview
  - Output: era_rules, material_palette, lighting_direction, color_palette, prop_style, era_exclusions
  - Immutability enforcement once Canon begins
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 1.4 Write tests for conversation → Brief → ArtBible flow
  - Test with Danny's kitchenette canonical prompt
  - Verify Brief completeness, UUID stability, Art_Bible era exclusions
  - _Requirements: 1.8, 2.5, 4.2_

### Wave 2: Spatial Planning and Blockout

- [x] 2.1 Implement MetricPlanGenerator
  - Create `src/unified_pipeline/plan_generator.py` using constrained template selection
  - LLM selects template + parameters (not free-form coordinates)
  - Output: room dimensions, walls, openings (parameterized 0..1 along wall), object placements, circulation paths
  - Revision tracking with provenance
  - _Requirements: 5.1, 5.2, 5.5, 5.6_

- [x] 2.2 Implement PlanValidator
  - Create `src/unified_pipeline/plan_validator.py` checking: room closure, opening validity (not too close to corners), object non-overlap, circulation clearance (≥0.6m), door swing clearance, dimensional plausibility
  - Auto-correction with new revision on failure
  - _Requirements: 5.3, 5.4, 5.5_

- [x] 2.3 Implement BlockoutRenderer
  - Create `src/unified_pipeline/blockout_renderer.py` producing 3D blockout from validated Plan using CameraContract
  - Show walls with actual openings, object placeholders at correct scale
  - Output image at CameraContract raster dimensions (1024×768)
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 2.4 Implement approval gate for Plan/Blockout
  - Create `src/unified_pipeline/approval_gates.py` with `await_blockout_approval()` supporting approve/revise
  - Revision loop: feedback → new Plan revision → re-render → re-approve
  - Block downstream until approved
  - _Requirements: 7.3, 7.4, 7.5_

- [x] 2.5 Write tests for Plan generation and validation
  - Test constrained template selection, validation rules (closure, overlap, circulation), revision tracking
  - Test Danny's kitchenette dimensions are plausible
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

### Wave 3: Canon Generation and Object Isolation

- [x] 3.1 Implement SceneCanonGenerator
  - Create `src/unified_pipeline/canon_generator.py` using FLUX conditioned on Blockout + Art_Bible
  - Preserve the same immutable CameraContract framing and Plan-owned geometry
  - Produce a cross-authority honesty report covering shell/openings, every manifest UUID, measured/photo placement, rotation-aware extents, dimensions/heights, forbidden overlap, palette/material intent, and prompt fidelity
  - Canon may propose bounded appearance evidence but SHALL NOT rewrite Plan geometry; non-green reports block Canon approval
  - Hash-bind the report and approval to the Plan revision + CameraContract hash
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

- [x] 3.2 Implement ObjectIsolator (MVP — raw segmentation, no inpainting)
  - Create `src/unified_pipeline/object_isolator.py` with SAM segmentation producing RGBA Object_PNGs
  - Map each segment to a stable Brief manifest UUID/category; list index and fuzzy noun matching are non-authoritative
  - Quality gate: reject empty masks or <1% coverage
  - Object_Canon = raw segmentation output (no inpainting completion for MVP)
  - Require one explicit Object_Canon approval writer; rejection invalidates dependent mesh/material artifacts
  - Inpainting completion interface defined but body stubbed (post-MVP)
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 3.3 Implement RoomPlateGenerator
  - Create `src/unified_pipeline/room_plate.py` — Canon with all objects inpainted out (FLUX)
  - Treat Room_Plate as optional appearance/texture evidence only; it SHALL NOT define architecture, collision, openings, navigation, or camera
  - _Requirements: 16.2_

- [x] 3.4 Write tests for Canon pipeline
  - Test full honesty report, Plan/Camera hash binding, approval invalidation, and rejection of geometry rewrites
  - Test Object_Canon UUID mapping and quality gate (reject bad completions)
  - _Requirements: 8.3, 9.4_

### Wave 4: Mesh Generation and Materials (✓REUSE V14 infrastructure)

- [x] 4.1 Wire existing Hunyuan3D generator for unified pipeline
  - Reuse `src/photo_pipeline/stages/hunyuan3d_v2_generator.py` — adapt interface to accept Object_Canon and output to unified models
  - Maintain: 50 steps, cfg=7.0, octree_resolution=384, 180s stall timeout, mesh validation (≥100 faces, ≥50 vertices, embedded texture, no ground sheet)
  - _Requirements: 10.3, 10.4, 10.6_

- [x] 4.2 Wire existing Trellis2 generator as fallback
  - Reuse `src/photo_pipeline/stages/trellis2_generator.py` — adapt interface
  - _Requirements: 10.4_

- [x] 4.3 Wire existing placeholder generator
  - Reuse `src/photo_pipeline/stages/placeholder_generator.py`
  - _Requirements: 10.5_

- [x] 4.4 Implement MeshApprovalGate
  - Create `src/unified_pipeline/mesh_approval.py` with turntable preview generation and approve/reject/regenerate flow
  - Record rejection reasons, track retry count
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [x] 4.5 Wire existing material processor (two-pass)
  - Reuse `src/photo_pipeline/stages/material_processor.py` — Pass 1 immediate, Pass 2 background
  - Hot-swap via WebSocket for V14+ viewers
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [x] 4.6 Wire existing semantic labeler
  - Reuse `src/photo_pipeline/stages/semantic_labeler.py`
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 4.7 Implement unified resource arbiter
  - Wrap the existing VRAM manager with one explicit schedule for Ollama, Dream/Canon FLUX, SAM, edit/inpaint, DA3, Hunyuan3D, Trellis2, painting, and every ComfyUI instance
  - Enforce one GPU owner at a time (including the planner), `/free` + measured release, host-RAM thresholds, OOM retry/fallback, and durable owner diagnostics
  - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

- [x] 4.8 Wire depth estimator as optional evidence adapter
  - Reuse `src/photo_pipeline/stages/depth_anything3.py` only to produce provenance-bearing depth evidence or aligned appearance reference
  - Prohibit depth from authorizing room dimensions, openings, collision, navigation, object transforms, or camera; reject per-axis/min-max spatial normalization
  - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_

- [x] 4.9 Write fast integration tests for accelerated V15 paths
  - Test fallback chain (Hunyuan → Trellis2 → placeholder), VRAM ordering, approval blocking, and stable UUID propagation
  - Fast authority/approval/VRAM/mesh/Canon slice: 144 passed on 2026-07-31
  - _Requirements: 10.3, 10.4, 10.5, 10.6_

### Wave 5: Room Shell, Architecture, and Physics

- [x] 5.1 Implement authoritative parametric room adapter
  - Reuse the existing approved Plan/solver/compiler path to build walls, floor, ceiling, openings, navigable bounds, and architectural collision
  - Bind every architectural element to the approved normalized Plan revision and immutable CameraContract
  - Allow a depth-derived mesh only as an optional aligned, non-colliding, honestly labeled appearance/reference layer
  - Fail closed if more than one source claims architecture or collision authority
  - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7_

- [x] 5.2 Implement FinishPass (procedural primitive placement — no CSG)
  - Create `src/unified_pipeline/finish_pass.py` placing pre-baked architectural primitives:
    - Door frames and window frames: box extrusions along opening edges
    - Baseboards: 2D profile swept along wall floor-line
    - Casing: 2D profile swept along opening perimeter
    - Outlets/switches: flat quad decals at era-appropriate heights
  - All placement parameterized along parent wall (0..1)
  - Respect Art_Bible era exclusions
  - Crown molding, wainscoting, vent covers: interface defined, body stubbed (post-MVP)
  - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7_

- [x] 5.3 Wire existing physics classifier
  - Reuse `src/photo_pipeline/stages/physics_classifier.py` — density table, 25kg threshold, architectural override
  - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5_

- [x] 5.4 Implement door hinge and interaction configuration
  - Create `src/unified_pipeline/door_physics.py` with hinge joint setup, swing limits, mass assignment
  - _Requirements: 18.6_

- [x] 5.5 Wire existing physics settle pass
  - Reuse `src/photo_pipeline/stages/physics_settle.py` — 500 iterations or 5s, clamp within bounds
  - _Requirements: 18.7, 18.8_

- [x] 5.6 Write tests for authoritative room, finish pass, and physics
  - Test Plan-derived room/opening/collision identity, rejection of dual room authority, and non-colliding optional depth reference
  - Test era-appropriate detail generation, door hinge configuration, settle convergence, rotation-aware extents, and circulation preservation
  - _Requirements: 16.1, 16.5, 17.1, 17.5, 18.6, 18.7_

### Wave 6: WorldContract Assembly and Validation

- [x] 6.1 Implement mandatory solve chain and WorldContractAssembler
  - Create `src/unified_pipeline/assembler.py` enforcing: solve → normalize → validate → immutable CameraContract → constrained SceneGraph → WorldContract → relationship solve → canonical serialization/hash
  - Bind one nonzero Plan revision, camera hash, authoritative parametric room, instances, solved transforms, relationships, physics, materials, and approved asset `(path, sha256, triangle_count)` records
  - Normalize each approved asset exactly once; reject revision mismatch, duplicate authority, consumer defaults, or post-hash mutation
  - _Requirements: 19.1, 19.2, 19.3, 19.4_

- [x] 6.2 Implement all structural publication gates
  - Create `src/unified_pipeline/validation_gates.py` with fail-closed gates for:
    - provenance: unbroken evidence → intent → approved Plan → contract chain with nonzero revision
    - containment: rotation-aware room/opening/object/collision extents and camera inside permitted bounds
    - overlap/opening/circulation: no forbidden solids, valid hosts, unoccluded openings, ≥0.6m required clearance
    - camera: navigable interior origin, outside collision, valid near/far, observes solved interior
    - asset/material: verified path, SHA-256, positive triangles, exactly-once normalization, honest material/degraded state
    - geometry/physics/semantic: closure, collision/settle, stable UUID/category, canonical hash stability
  - Record each result with revision, canonical hash, offending node/binding, and focused diagnostics
  - All structural gates pass before compilation; compiler parity runs after compilation in Task 7.4 and before publication
  - _Requirements: 20.1–20.10_

- [x] 6.3 Implement event finality and replay system
  - Create `src/unified_pipeline/event_system.py` with provisional/final classification, revision/hash binding, and contract-before-final ordering
  - Preserve finality across SSE, WebSocket, reconnect/replay, sidecars, and compiler events; reject or downgrade stale/mismatched events
  - _Requirements: 19.5, 19.6, 27.2_

- [x] 6.4 Write tests for solve chain, gates, and finality
  - Test deterministic post-relationship hash, revision mismatch rejection, exactly-once normalization, no consumer drift, and dual-authority rejection
  - Test every gate pass/fail path plus final event ordering, reconnect/replay, stale-response cancellation, and hash mismatch downgrade
  - _Requirements: 19.2, 19.3, 20.1–20.10_

### Wave 7: Engine Compilation

- [x] 7.1 Implement BrowserCompiler (Three.js)
  - Create `src/unified_pipeline/compilers/browser.py` deriving Three.js scene from WorldContract
  - GLTFLoader, PBR metallic-roughness, orbit + first-person controls, progressive SSE loading
  - _Requirements: 21.1, 21.4_

- [x] 7.2 Implement GodotCompiler
  - Create `src/unified_pipeline/compilers/godot.py` emitting Godot 4 project: .tscn, physics bodies (RigidBody3D/StaticBody3D), first-person controller, grabbing, door hinges, lighting
  - _Requirements: 21.2, 21.4, 21.6_

- [x] 7.3 Implement UPBGECompiler
  - Create `src/unified_pipeline/compilers/upbge.py` emitting .blend with player controller, character physics, logic bricks
  - _Requirements: 21.3, 21.4, 21.6_

- [x] 7.4 Implement compiler selection and post-compile parity gate
  - Create `src/unified_pipeline/compilers/parity.py` verifying browser and selected engine payloads carry the same canonical WorldContract hash, revision, camera, room dimensions, solved instance transforms, asset bindings, and material bindings
  - Reject independent consumer defaults, clamps, rescaling, rotation/offset substitution, camera inference, or second asset normalization
  - Parity SHALL pass after compilation and before any final event or publication
  - _Requirements: 20.8, 21.4, 21.5_

- [x] 7.5 Write tests for compilation and parity
  - Test each compiler produces valid output from a test WorldContract
  - Verify parity gate catches hash mismatches
  - _Requirements: 21.4, 20.8_

### Wave 8: Walkable World and Interaction

- [x] 8.1 Implement first-person controller for browser
  - Extend V14 Three.js viewer with: WASD movement, mouse look (PointerLock), gravity, collision with static bodies, safe spawn position selection
  - _Requirements: 22.1, 21.6_

- [ ] 8.2 Implement object interaction system
  - Door swing (hinge physics), object grab/release (raycasting + constraint), push/topple (impulse application)
  - _Requirements: 22.2, 22.3, 22.4_

- [x] 8.3 Implement lighting from WorldContract
  - Place light fixtures at contract positions, set intensity/color/temperature from Scene_Canon-derived values
  - Compute shadows from each light source
  - _Requirements: 22.5_

- [x] 8.4 Implement three-view identity and Canon fidelity comparison
  - Create `src/unified_pipeline/canon_compare.py` comparing Plan-derived Blockout/blueprint, Scene_Canon, and first-person World render per stable UUID and region
  - GREEN requires shell/opening truth, every requested object, placement/dimensions/heights, zero forbidden overlap, and palette/material fidelity; presence/order alone is insufficient
  - Store the verdict as hash-bound evidence and block final QA on red/amber according to configured release policy
  - _Requirements: 22.6_

- [x] 8.5 Write interaction and walkability tests
  - Test spawn safety, collision response, door swing, grab/release
  - _Requirements: 22.1, 22.2, 22.3, 22.4_

### Wave 9: Mode Toggle and REAL Mode (GAME stubbed)

- [x] 9.1 Implement GameOverlay data model and stub designer
  - Create `src/unified_pipeline/game_designer.py` — data model for GameOverlay (rules, scoring, win_condition, object_role_bindings by UUID)
  - Stub implementation: returns a suggested theme + mechanics based on Brief room_purpose, but NO functional gameplay logic
  - Full AI game design is a follow-on session
  - _Requirements: 23.1, 23.2, 23.3, 23.4_

- [x] 9.2 Implement RealBinder (read-only surface display)
  - Create `src/unified_pipeline/real_binder.py` — tool connection system
  - MCP-server-compatible bindings, read-only v1, surface assignment by UUID
  - Implement one working binding: display static text/data on a bound surface
  - Budget/land earning logic is post-MVP
  - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5_

- [x] 9.3 Implement ModeToggle (config switch)
  - Create `src/unified_pipeline/mode_toggle.py` — per-room state, persist, announce on entry
  - Toggle switches between REAL overlay (functional) and GAME overlay (stubbed/placeholder)
  - Verify: no visual change on switch, only behavior overlays swap
  - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6_

- [x] 9.4 Write tests for toggle and REAL mode
  - Test mode persistence, toggle preserves visuals, REAL binding displays data
  - _Requirements: 25.2, 25.5, 24.4_

### Wave 10: Asset Warehouse and Orchestration

- [x] 10.1 Wire existing Asset Warehouse for unified pipeline
  - Reuse `src/photo_pipeline/asset_warehouse.py` — adapt to accept unified models
  - Append-only, never consulted pre-generation, full metadata registry
  - Add game_properties and real_bindings fields to registry
  - _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6_

- [x] 10.2 Implement durable UnifiedOrchestrator
  - Create `src/unified_pipeline/orchestrator.py` wiring: Conversation → Brief → Art_Bible → Dream → Plan solve/normalize/validate → Camera → Blockout approval → Canon honesty/approval → Segment → Object_Canon approval → Mesh approval → Materials → authoritative Parametric Room + optional depth reference → Finish → Physics/Settle → relationship-solved WorldContract/hash → structural gates → Compile → parity gate → final events → GAME/REAL/Toggle → Warehouse Catalog
  - Write atomic per-stage checkpoints with input/output hashes, Plan revision, approval revision, external job ID, attempt, and completion state
  - Resume idempotently by reconciling pending external jobs; never blindly resubmit. Cancel stale responses and invalidate/archive every downstream artifact and approval after an upstream revision
  - Enforce one durable session worker lease, one approval writer, explicit unresolved-flag blocking/resolution, Windows detached child process groups, and reload-safe ownership
  - SSE/WS progress reports current stage, objects X/N, elapsed/ETA, provisional/final state, revision, and canonical hash where valid
  - No hard time cap; 180s stall detection triggers bounded recovery/fallback without weakening quality gates
  - _Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6_

- [x] 10.3 Implement web routes for unified pipeline
  - Add routes: `GET /?v=16` (default), `POST /api/session/unified/start` (begins conversation), `POST /api/session/{id}/message` (conversation turn), `POST /api/session/{id}/approve/{stage}`, `GET /api/session/{id}/dream_preview`, `GET /api/session/{id}/blockout`, `GET /api/session/{id}/canon`, `GET /api/session/{id}/mesh/{object_id}`, SSE events, WS materials
  - Maintain V3-V15 routes unchanged
  - _Requirements: 28.1, 28.2, 28.3, 28.4_

- [x] 10.4 Write orchestration recovery and integration tests
  - Test full pipeline with mocked GPU stages using Danny's kitchenette prompt
  - Verify corrected stage order, all five approvals, structural/parity publication gates, and provisional/final event ordering
  - Crash/restart at every external-job boundary and prove idempotent resume, no duplicate submissions, stale-response cancellation, downstream invalidation, and worker-lease exclusivity
  - _Requirements: 27.1, 27.2, 27.4, 28.4_

### Wave 11: Qualification

- [x] 11.1 Implement qualification harness
  - Create `src/unified_pipeline/qualification.py` with fresh-session creation, canonical prompt injection, complete stage traversal, gate verification, and append-only diagnostic recording
  - Record source fingerprints, exact artifact hashes, Plan/approval revisions, contract hash, compiler parity, browser owner, and whether each result is mocked or live
  - _Requirements: 30.1, 30.2, 30.3, 30.4_

- [x] 11.2 Run clean qualification with Danny's kitchenette
  - Start from a brand-new empty session and traverse: Conversation → Brief → Dream → Plan → Blockout → Canon → Objects → Meshes → Materials → Physics → WorldContract → Compilation → Validation → Walk → GAME → REAL → Toggle
  - Inspect three-view identity, authority/gates, mesh/material quality, physics/walkability, overlays, reconnect/replay, and browser/compiler parity
  - After the zero-state smoke passes, run five fresh headless rounds and five fresh human-like rounds; never reuse or restore a qualifying session
  - Record pass/fail and exact evidence per stage and round
  - _Requirements: 30.3, 30.4, 30.5, 30.6_

- [x] 11.3 Fix any failure and restart qualification
  - Failed sessions remain diagnostic evidence only
  - Fix the cause, discard the failed session as release evidence, and restart the entire clean sequence with another new empty session
  - _Requirements: 30.5, 30.6_

- [x] 11.4 Commit release
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
    { "id": 5, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6"], "gate": "Plan-derived room is sole authority; finish and physics preserve openings/circulation" },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3", "6.4"], "gate": "Relationship-solved WorldContract is hash-stable; all structural gates and finality tests pass" },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3", "7.4", "7.5"], "gate": "All compilers derive from one contract and post-compile parity passes" },
    { "id": 8, "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5"], "gate": "Player walks/interacts and three-view identity passes" },
    { "id": 9, "tasks": ["9.1", "9.2", "9.3", "9.4"], "gate": "GAME persists, REAL displays data, toggle works" },
    { "id": 10, "tasks": ["10.1", "10.2", "10.3", "10.4"], "gate": "Durable pipeline resumes idempotently with leases, invalidation, and final event ordering" },
    { "id": 11, "tasks": ["11.1", "11.2", "11.3", "11.4"], "gate": "Clean smoke plus five headless and five human-like fresh rounds pass" }
  ]
}
```

## Notes

- **Realistic timeline: 22-30 hours active coding across 2-3 marathon sessions.** The 6-12h estimate is retired.
- Tasks marked ✓REUSE leverage existing V14 infrastructure (already implemented and tested)
- Human approval gates are mandatory: Blockout, Scene_Canon, Object_Canon, Mesh Shape, and Final World QA; one durable approval writer owns each decision
- The always-fresh rule means Wave 4 mesh generation NEVER checks the warehouse — it generates, then catalogs
- GAME mode is STUBBED in the marathon (data model + suggested theme only); full implementation is post-MVP
- REAL mode ships with read-only surface binding (one working example)
- The qualification scene is Danny's kitchenette but the pipeline is scene-agnostic
- Existing V14 property tests remain useful but do not override the V15 authority, finality, resume, or qualification corrections
- All structural publication gates ship in MVP; compiler parity runs post-compile and before publication
- Finish pass uses procedural primitive placement (profile sweeps + decals), NOT CSG/boolean geometry

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
| Authoritative room | Parametric Plan-derived architecture/collision | Optional non-colliding depth appearance/reference |
| Finish pass | Baseboards, frames, casing, outlets (primitives) | Crown molding, wainscoting, vents |
| Physics + settle | Full implementation | — |
| WorldContract + hash | Full implementation | — |
| Validation gates | Full structural set before compile + parity after compile | Additional visual polish metrics only |
| Engine compilation | Browser (Three.js) full; Godot/UPBGE wired | — |
| Walkable world + interactions | Full (WASD, doors, grab, physics) | — |
| Mode Toggle | Config switch (works) | — |
| GAME Designer | Stubbed (data model + theme suggestion) | Full AI game logic, persistence, remodel patching |
| REAL Binder | One working read-only binding | Full MCP integration, budget earning |
| Warehouse catalog | Full (append-only post-generation) | — |
