# Implementation Plan: Unified World Pipeline

## Overview

This plan builds the complete conversation-to-walkable-world-with-toggle pipeline in dependency order. It is designed for marathon execution: each wave can run to completion before the next begins, but independent tasks within a wave can be parallelized. The pipeline reuses existing V14 infrastructure where complete (marked ✓REUSE) and builds new where required.

**Demo proving ground:** Reproduce the immutable photoreal Golden Room source `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png` (SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6`) as a geometry-honest Golden Browser Room, using original workflow `danny-v4.1-items.ui.json` (SHA-256 `0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196`) as immutable appearance/composition evidence only.

**Release generalization benchmark:** `Danny's kitchenette — a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain.` The exact 142-byte UTF-8 prompt has SHA-256 `af6759e5d516561fad3fb49b129f02ad27743e273d1345173d59430f462f32ec` and remains exclusive to the later fresh Release Profile qualification.

**Profile freshness rule:** Release and fresh-benchmark runs generate without pre-generation warehouse reuse. The photo-bound Demo Profile may reuse only hash-verified, human-approved assets that pass StandaloneAssetGate.

**WorldMirror feasibility decision:** HY-World 2.0 is a candidate reconstruction/generation backend, not product architecture or spatial authority. Full HY-World worldgen remains deferred off the single-RTX-4090 critical path; only WorldMirror 2.0 receives one bounded local preflight and, after a separate explicit size/isolation confirmation, feasibility attempt before the fixed-recliner bake-off.

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

- [x] 8.2 Implement object interaction system
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

### Wave 11: Restart Session Continuity Fix and Fresh V16 Qualification

> Requirement references in Wave 11 target `bugfix.md`; retained pipeline requirements remain additionally binding.

- [x] 11.0 Recover the authoritative checkpoint and finalize the bugfix specification
  - Preserve the uncommitted V16 repairs exactly as found; do not reset, overwrite, or describe them as validated
  - Record `unified-world-pipeline` V16 as governing, the historical `llm-driven-upbge-runtime` Task 10 continuation as superseded, Tasks 1–12 as complete history, and Tasks 13–14 as inactive downstream work
  - Preserve the exact 922 unified/strict-real, 36 V14/V16 route, and 53 mesh-focused green baseline only for its validated fingerprint; record that newer repairs are unvalidated and no clean live zero-state V16 release pass exists
  - Preserve all known failed/non-canonical sessions as append-only diagnostic evidence
  - Finalize `bugfix.md`, `design.md`, `.config.kiro`, and this ordered task plan without implementation or qualification claims
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.3, 3.4_

- [x] 11.1 Preserve, fingerprint, and validate the recovered V16 candidate before qualification
  - Capture the current revision, relevant working-tree diff, and deterministic candidate-tree fingerprint before changing code; keep all uncommitted repairs intact
  - Run focused repaired-behavior tests first, then the full unified/strict-real, V14/V16 route, and mesh-focused suites; bind results to the exact candidate fingerprint instead of inheriting the historical 922/36/53 evidence
  - Run diagnostics, compile checks, workflow JSON validation, and diff checks against that same fingerprint
  - Validate the V16 page, relevant API routes, and static JavaScript; verify V3–V15 selectors/routes and version-switch links remain accessible and behaviorally stable
  - If validation fails, record it, repair only the demonstrated cause, assign a new fingerprint, and repeat this task before continuing
  - Treat the existing qualification harness and mocked GPU-stage results as diagnostic tooling only
  - _Requirements: 2.3, 2.5, 2.6, 3.1, 3.2, 3.4_

- [x] 11.2 Write the restart bug-condition exploration test before any new reconciliation implementation
  - **Property 1: Bug Condition** - Restart Recovery Reconciles Conflicting Evidence
  - **CRITICAL**: This standalone property-based test MUST run before implementing a restart reconciler and MUST fail on an unfixed path; the failure confirms the defect
  - **DO NOT** fix the test or implementation when the expected failure first appears
  - Generate immutable `RecoverySnapshot` fixtures satisfying `isBugCondition(input)`: stale active Task 10 plus newer Tasks 1–12 completion, dirty candidate after a fingerprint-bound green baseline, diagnostic-session reuse, no clean live pass, source-order permutations, and premature Tasks 13–14 activation
  - Assert `expectedBehavior(result)`: V16 stays active; stale Task 10 is superseded; Tasks 13–14 stay inactive; validation applies only to an exact fingerprint; newer repairs stay unvalidated; ineligible sessions are rejected; and the first unmet V16 gate is selected
  - Run on the validated-but-unfixed recovery path and document the minimal counterexample; if it unexpectedly passes, add no speculative implementation and revisit the root-cause/design hypothesis
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 11.3 Write restart preservation property tests before any new reconciliation implementation
  - **Property 2: Preservation** - Non-Bug Recovery and Release Evidence Remain Stable
  - **IMPORTANT**: This standalone task follows observation-first methodology where `isBugCondition(input)` is false
  - Observe and record unfixed behavior for normal durable V16 resume, exact tree/evidence matches, one worker lease and approval writer, retained V3–V15 access, diagnostic inspection, exact baseline/prompt reporting, and defect-triggered session replacement
  - Write differential properties preserving those outputs, durable checkpoint identity, append-only diagnostics, and V3–V15 page/API/static-JavaScript behavior; verify they pass before implementation
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 11.4 Implement restart reconciliation only if Tasks 11.2–11.3 prove an implementation gap

  - [x] 11.4.1 Implement the smallest recovery-boundary fix
    - Normalize task, memory, continuation, validation, tree, service, and session facts into scoped evidence with source digests, timestamps, supersession links, and exact revision/tree fingerprints
    - Resolve task truth, candidate validation, service readiness, and release qualification independently and deterministically; reject ambiguous ties rather than selecting by retrieval order
    - Add a fail-closed eligibility predicate requiring a validated candidate fingerprint, V16, a brand-new empty non-restored session, exact canonical prompt, live required services, no mocks, complete applicable stage inspection, and no defect
    - Keep old Task 10 and failed sessions append-only while excluding them from active/release truth; keep Tasks 13–14 inactive; emit accepted/rejected facts, fingerprints, ineligibility reasons, release state, and exactly one next action
    - Keep the fix outside V3–V15 behavior and preserve normal idempotent V16 durable-session reconciliation
    - _Bug_Condition: `isBugCondition(input)` where scoped records conflict, a candidate lacks matching validation, qualification evidence is ineligible, or downstream work is premature_
    - _Expected_Behavior: `expectedBehavior(result)` from the Restart Session Continuity Fix design_
    - _Preservation: non-bug recovery, V3–V15 behavior, durable V16 resume, append-only diagnostics, exact baseline/prompt, and restart-on-defect semantics_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 11.4.2 Verify the original exploration test now passes
    - **Property 1: Expected Behavior** - Restart Recovery Reconciles Conflicting Evidence
    - Re-run the SAME property from Task 11.2; verify every bug-condition snapshot and record permutation satisfies `expectedBehavior(result)`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 11.4.3 Verify the original preservation tests still pass
    - **Property 2: Preservation** - Non-Bug Recovery and Release Evidence Remain Stable
    - Re-run the SAME observation-based differential properties from Task 11.3; do not replace them after seeing implementation output
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 11.4.4 Add restart reconciliation integration tests
    - Simulate process and agent-session restart with the known conflicting checkpoint; verify monotonic progression, exact fingerprint binding, and preservation of the prior baseline
    - Verify relevant tree changes return to candidate validation, invalid transitions fail closed, failed/restored sessions stay ineligible, and durable external-job restart retains one lease/writer with idempotent reconciliation
    - If recovery status is user-visible, advance the query version instead of overwriting a released interface, retain preceding versions, and add page/API/static-JavaScript coverage
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.6_

- [x] 11.5 Checkpoint - validate the exact post-fix candidate
  - If Task 11.4 was needed, fingerprint the new candidate and rerun focused restart tests, Property 1, Property 2, full affected suites, diagnostics, compile, workflow JSON, and diff checks
  - Revalidate the V16 page, relevant API routes, static JavaScript, V3–V15 routes/selectors, and version-switch links
  - Continue only when all evidence matches the exact candidate fingerprint; confirm Tasks 13–14 remain inactive
  - _Requirements: 2.3, 2.5, 2.6, 3.1, 3.2, 3.4_

- [x] 11.6 Verify required local services and models before creating a qualification session
  - Verify Comfy Desktop is live specifically on `localhost:8188`, its required workflows/nodes respond, and no agent-managed terminal owns the long-running process
  - Verify Ollama is live on `localhost:11434`; confirm the configured conversation/semantic model and required vision models are installed and callable, including `qwen2.5vl:7b` and `qwen3.6:27b`
  - Verify the V16 app/API/static assets serve the validated candidate fingerprint; fix any preflight failure and repeat without creating a session
  - _Requirements: 2.6, 3.5_

- [ ] 11.7 Preserve failed zero-state V16 smoke evidence as diagnostic-only history
  - Retain every failed Task 11.7 session and artifact append-only; each remains permanently ineligible for Demo Ready and release evidence
  - Preserve the exact attempted prompt: `Danny's kitchenette — a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain.`
  - Never restore, resume, clone, repair in place, or count a failed Task 11.7 session; the replacement run is Task 11.7.1 and remains deferred until Task 11.8.9 records Demo Ready
  - _Requirements: 35.7-35.11, 36.1-36.3, 42.1, 42.2, 42.4_

- [ ] 11.8 Complete the photo-bound Golden Room Demo Ready milestone without starting a replacement session
  - Preserve the counter/cabinet semantic repair as a focused regression prerequisite, run the bounded WorldMirror 2.0 feasibility decision, then reproduce the immutable photoreal Golden Room through the following leaf tasks in order
  - Do not create a replacement zero-state or qualifying session anywhere in Task 11.8
  - Preserve V3–V16 behavior, unrelated working-tree changes, process ownership, all failed-session evidence, and the distinction between photo-bound Demo Ready and prompt-driven Release Ready
  - _Requirements: 38.1-38.12, 42.1-42.4, 42.9, 42.10, 43.1-43.14_

  - [x] 11.8.1 Repair counter/cabinet semantic observation and bind focused revalidation
    - Make `counter`, `countertop`, `kitchen counter`, `built-in counter`, `cabinet`, and `cabinet/storage` reconcile to the required built-in counter/cabinet UUID without permitting unrelated full-frame detections
    - Add or update focused regression coverage for the preserved failure, then rerun only the affected candidate validation, page/API/static-JavaScript checks, V3–V16 retention checks, and service preflight required by the repair
    - Record the repaired exact candidate fingerprint; counter/cabinet is a regression prerequisite, not a Golden Room hero asset; do not start or resume any live pipeline session
    - _Requirements: 38.7, 42.3, 42.9, 42.10_

  - [x] 11.8.2 Bind the immutable Golden Room reference, freeze exploration, and declare the Demo Profile
    - Bind authoritative image `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png` at SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6` and original workflow `C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json` at SHA-256 `0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196` as immutable appearance/composition evidence only
    - Confirm `C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png` hashes identically to `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6`; fail closed and document any mismatch
    - Record that MiniMax, DA3, MoGe, Anima, HY-Pano, WorldNav, WorldStereo, MoVerse, One2Scene, and other open-ended exploratory geometry/model work are frozen; permit no such downloads, integration, capability preflight, or new video/depth generation. The sole model-integration exception is the following bounded WorldMirror Task 11.8.2a after its explicit confirmation checkpoint; already-available recliner video-depth evidence remains permitted in Task 11.8.3
    - Create a new immutable photo-bound Demo Profile run identity, record permitted approved warehouse reuse, and never relabel diagnostic evidence
    - _Requirements: 38.3-38.5, 38.8, 41.1-41.3, 41.6, 41.7_

  - [x] 11.8.2a Preflight WorldMirror 2.0 and run one bounded local feasibility gate only after renewed confirmation
    - Phase A — documentation/preflight only: inspect the official HY-World 2.0 and WorldMirror license and redistribution terms; inventory required repository, weights, dependencies, disk, cache/output storage, peak VRAM/RAM, CUDA, Python, compiler, and native-build compatibility; identify any official reduced-memory/offload mode; confirm Golden Room inputs and all inference remain local with no telemetry, vLLM, cloud, or external data transmission
    - Record measured or source-grounded repository/model/environment/cache/output size estimates, a fixed setup/storage budget, an isolated reversible environment path, exact cleanup steps, one-GPU ownership plan, and a 60-minute maximum active Phase-B budget; Phase A SHALL NOT install/download HY-World, start services or sessions, run inference, generate assets, or modify production code/tests/UI
    - Stop after Phase A and request explicit user confirmation of the measured license finding, sizes, storage budget, local-only path, isolation, and cleanup. Only that later confirmation may authorize Phase B downloads/installation; this plan update does not authorize them
    - Phase B — only after that explicit confirmation: create the reversible isolated environment, implement the smallest disposable local WorldMirror adapter/runner and deterministic evidence manifest, load WorldMirror locally or use only an official documented reduced-memory/offload mode viable on the 24GB RTX 4090, and run one bounded reconstruction from local hash-bound Golden Room evidence under safe single-GPU process ownership
    - Capture candidate depth, normals, cameras, point cloud, 3DGS, TSDF, and mesh outputs that the official path actually emits; hash every input/output and record provenance, commands/configuration, timing, peak VRAM, peak RAM, and disk use. Keep all outputs non-authoritative and non-colliding unless later aligned, validated, contract-bound, structurally/visually gated, and human-approved
    - PASS only when the isolated environment is reversible; the model loads or an official viable 24GB mode is documented; one reconstruction completes without OOM or unsafe ownership; output loads locally; approved-camera resemblance and at least one novel-view coherence are materially better than current source-only/depth evidence; and no placeholder or cloud demo substitutes for evidence
    - FAIL or DEFER on multi-GPU-only requirements, >24GB use without an official viable mode, setup/time/storage overrun, CUDA/Python/native-build incompatibility, license/redistribution blocker, inability to prove local-only execution, unloadable output, or no material visual improvement. Record the exact blocker, freeze WorldMirror, and proceed directly to Task 11.8.3 without HY-Pano, WorldNav, WorldStereo, MoVerse, One2Scene, or unrelated exploration
    - Preserve MetricPlan as sole authority for dimensions, transforms, placement, architecture, openings, collision, navigation, and CameraContract. WorldMirror cameras/depth/normals/point clouds/3DGS/TSDF/meshes are evidence only; TSDF or mesh may become a visual or collision candidate solely after explicit contract/gate/human approval and may never silently replace Plan architecture
    - Keep full HY-World worldgen deferred because official guidance recommends at least four GPUs, reports testing on eight H20 GPUs, and uses external vLLM; any later remote/high-end or cloud evaluation requires separate explicit permission
    - _Requirements: 43.1-43.14, 38.1, 38.8-38.10, 42.9, 42.10_

  - [x] 11.8.3 Run the fixed-recliner three-lane bake-off within 60–90 active minutes after the WorldMirror verdict
    - Begin only after Task 11.8.2a records PASS, FAIL, or DEFER; a WorldMirror failure or deferral returns here immediately and SHALL NOT expand model exploration
    - Use one fixed recliner UUID and common source identity across raw crop, existing Qwen amodal completion, and video-depth only if already available when the bake-off begins
    - Bind each candidate to Golden Room source/workflow hashes, source/input hashes, workflow identity, asset hash, elapsed active time, and durable-material status
    - Stop at the fixed budget and carry completed candidates forward; do not extend the timebox for missing lanes or new model work
    - _Requirements: 38.9, 38.10, 39.1-39.5_

  - [x] 11.8.4 Apply one common StandaloneAssetGate and select the visually best recliner lane
    - Independently load every completed candidate and inspect the same neutral multi-angle turntable rubric: silhouette/identity, reconstruction artifacts, fused scene geometry, and durable material continuity
    - Reject placeholders, unresolved external materials, temporary materials, and Pass-1-only candidates; require human approval bound to the exact asset hash, candidate fingerprint, and Golden Room reference hashes
    - Select the visually best passing lane; if no lane passes, record a fail-closed blocker without expanding model exploration
    - _Requirements: 38.11, 39.1-39.5, 39.13, 39.14_

  - [ ] 11.8.4a Remediate and approve the Golden Room source-matched raw-crop recliner
    - Preserve Task 11.8.4 and `task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json` as immutable no-pass evidence; do not edit, relabel, replace, or retroactively convert its verdict
    - Use only the Golden Room source-matched `raw_crop` recliner candidate and the existing approved local material pipeline; do not use the rejected Qwen lane, WorldMirror, MoVerse, MASt3R, DUSt3R, or any unapproved model download, integration, capability preflight, or exploratory generation
    - Produce a new independently loadable GLB with embedded durable non-temporary materials and textures, no unresolved external materials or buffers, and hash-bound neutral multi-angle evidence exposing silhouette, topology, identity, material continuity, fused geometry, and reconstruction artifacts
    - Preserve recliner UUID `3b2cae03-3556-5c1e-a19b-ea3c1e15694c` and the raw-crop candidate's Golden Room source/workflow provenance; preserve MetricPlan as sole authority for dimensions, transforms, placement, architecture, openings, collision, and navigation, the immutable Plan-derived CameraContract as camera authority, and WorldContract as final binding authority
    - Rerun the exact Task 11.8.4 common StandaloneAssetGate checks in the same order against the new artifact, with no lane-specific exception or weakened criterion
    - Never manufacture human approval: if and only if every non-human check passes, present the exact artifact hash, candidate fingerprint, Golden Room reference hashes, provenance, neutral multi-angle evidence, and gate results, then pause for explicit user approval bound to those exact values
    - Keep Task 11.8.5 blocked unless the remediated candidate passes every common-gate check, including that explicit hash-bound human approval; otherwise record a new fail-closed blocker without reopening model exploration
    - Run targeted validation of artifact loadability, embedded material/texture durability, URI/buffer resolution, hash/provenance/UUID bindings, neutral evidence, and exact gate parity; record commands, results, input/output hashes, candidate fingerprint, approval state, and blocker or pass verdict as new immutable evidence
    - User authorizes up to ten additional evidence-renderer-only attempts with automatic direct inspection of the authoritative Canon image, source crop, and every generated preview from disk; stop early only when every non-human common-gate check and the strict local vision gate pass, with no GLB, model, or downstream scope expansion
    - Do not change any UI or interface version, production code or service ownership, Comfy Desktop ownership, Windows Scheduled Task or Ratchet-watch ownership, or unrelated working-tree content; do not start a replacement or qualification session and do not commit
    - _Requirements: 38.4, 38.5, 38.8, 38.11, 39.1-39.5, 39.13, 39.14, 41.3, 41.6, 42.9_

  - [ ] 11.8.4b Prove Canon decomposition and deterministic shell/recliner reconstruction after the rejected neural geometry
    - Preserve Task 11.8.4, rejected Task 11.8.4a, all prior evidence, and rejected GLB SHA-256 `4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf` unchanged and append-only
    - Run the immutable `danny-v4.1-items.api.json` SAM3 workflow against locked Canon SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6`; reuse the existing app's empty-twin output only and do not rerun prompt-generated Canon/restyle/colorize branches
    - Produce a hash-bound `CanonDecompositionPack` covering the room shell, camera estimate, and every clearly visible item with stable UUID, source alpha-mask/cutout path and hash, structured positive/negative prompts, geometry/components, bounded appearance-only size estimate, material/color cues, relative pose, occlusion/confidence, and relationships
    - Preserve MetricPlan as sole spatial authority, immutable Plan-derived CameraContract as camera authority, and WorldContract as final binding authority; decomposition, empty-twin, generated geometry, and renders remain non-authoritative appearance evidence
    - Build a new deterministic empty-room shell and an independently loadable recliner GLB from explicitly separate back, seat, left/right arms, base, footrest, seams, and cushion segments; never reuse, modify, smooth, or rerender the rejected Task 11.8.4a GLB
    - Require embedded durable materials, no unresolved image/buffer URI, distinct component topology, source/workflow/output hash checks, and two local review PNGs: Canon-camera comparison/contact sheet plus neutral multi-angle recliner sheet
    - Automatically open both exact PNGs locally, but never infer approval; after all non-human checks pass, stop at `AWAITING_EXPLICIT_HUMAN_REVIEW` and leave this task unchecked until a later explicit human approval is bound to the exact hashes and candidate fingerprint
    - Current state is `FAIL_CLOSED_HUMAN_REJECTED`: preserve candidate fingerprint `d220ae78b3c8fd327a5aeb6aca523fd0ee5b132429c6947b1d413e89f5d204e9` and recliner GLB SHA-256 `b4a3358f1cec5b5c051301ae5bab136f0e3ce7eaeb5b9ed1f0dd918efff6a39e` unchanged as the immutable closest/best-so-far structural baseline and diagnostic evidence only, never as an approved asset, Demo Ready evidence, or release evidence
    - Bind the rejection to Canon SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6`, contact-sheet SHA-256 `243652bb622a4e550299de9f62f07c8704eb2e2a6423ee8ed5fb0a5e21d53443`, multi-angle-sheet SHA-256 `6d755b1555ac8c95bdc362f0895c95d118268805e9c525e582cb63ff5525aaf2`, and append-only rejection evidence `.kiro/specs/unified-world-pipeline/evidence/task-11.8.4b-human-rejection-best-structural-baseline-8b1d00d1-c773-4d62-a823-7e21041b43b5.json` SHA-256 `36d65fbf6a617959510fb297479d295d4f4c6d69d4ba1938c85b3e195ac9c509`; the user's statement that it is the closest result is comparative structural guidance and SHALL NOT be interpreted as human approval
    - Keep this task unchecked and Task 11.8.5 `BLOCKED_NOT_STARTED`; do not start a session, qualification, downstream task, UI version, service/process ownership change, staging, or commit
    - _Requirements: 38.4, 38.5, 38.8, 38.11, 39.1-39.5, 39.13, 39.14, 41.3, 41.6, 42.9_

  - [ ] 11.8.4c Refine the best structural recliner baseline with the authoritative Danny Tornado Art Bible
    - Begin only from immutable diagnostic baseline fingerprint `d220ae78b3c8fd327a5aeb6aca523fd0ee5b132429c6947b1d413e89f5d204e9`; locate the authoritative Danny Tornado Art Bible, record its exact path and SHA-256, reject ambiguous or unverified substitutes, and preserve the locked Canon SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6`
    - Extract recliner-specific era, style, proportion, upholstery, material, color, construction, and wear cues grounded jointly in the hash-bound Art Bible and locked Canon; record source-grounded cue provenance and distinguish appearance guidance from MetricPlan, CameraContract, and WorldContract authority
    - Produce improved hash-bound positive and negative recliner prompts that explicitly target a softer overstuffed Canon-matched silhouette, worn brown upholstery, correct arm/back/cushion proportions, a conventional recliner base, and an integrated/aligned footrest while excluding rigid/thin/blocky forms, pedestal or office-chair bases, detached/misaligned footrests, modern pristine upholstery, fused room geometry, and blob-like or melted topology
    - Refine rather than restart the deterministic separate-component architecture: preserve independently inspectable back, seat, left/right arms, base, footrest, seams, and cushion topology and preserve all authority boundaries; do not modify or relabel the Task 11.8.4b baseline artifact
    - Emit a new independently loadable GLB, new candidate fingerprint, new artifact hash, durable embedded materials/textures, no unresolved image/buffer URI, and provenance binding the Art Bible, locked Canon, prior structural baseline, generator/configuration, and every output
    - Replay the same Task 11.8.4b non-human checks and complete common StandaloneAssetGate order without exceptions or weakened criteria; produce two new hash-bound review sheets, one Canon-camera comparison/contact sheet and one neutral multi-angle recliner sheet, and automatically inspect both locally
    - If and only if every non-human check passes, stop at `AWAITING_EXPLICIT_HUMAN_REVIEW`; require a new explicit human approval bound to the new GLB hash, new candidate fingerprint, Art Bible hash, Canon hash, both review-sheet hashes, source lane, UUID, and gate evidence before this leaf can pass
    - Do not download or use a new model or cloud service, reopen exploratory geometry, generate a session, start qualification or downstream work, change UI/version/services/process ownership, stage, or commit
    - _Requirements: 38.4, 38.5, 38.8, 38.11, 39.1-39.5, 39.13, 39.14, 41.3, 41.6, 42.9_

  - [ ] 11.8.5 Produce and approve the five standalone Golden Room hero assets only after Task 11.8.4c passes
    - Status: `BLOCKED_NOT_STARTED`
    - Begin only after Task 11.8.4c records a new Art-Bible-guided deterministic recliner candidate that passes every common StandaloneAssetGate check and has explicit user approval bound to the exact artifact hash, candidate fingerprint, Art Bible hash, Golden Room reference hashes, both review-sheet hashes, UUID, source lane, and gate evidence
    - Produce or explicitly reuse permitted approved assets for the recliner, refrigerator, CRT television, wooden TV stand, and bookshelf by stable UUID
    - Require independent load, durable non-temporary materials, neutral turntable evidence, and human approval for every hero asset under StandaloneAssetGate
    - Do not count placeholders, fused room geometry, temporary Pass-1-only materials, or counter/cabinet toward the five
    - _Requirements: 39.1-39.6, 41.3, 41.6_

  - [ ] 11.8.6 Assemble one Golden Browser room in normative product order
    - Confirm Prompt → Dream Preview → approved MetricPlan/Blockout → geometry-conditioned final Scene Canon → object production; the final Scene Canon must be Plan/Blockout/CameraContract-derived and visually converge on the immutable Golden Room reference without importing it as Canon
    - Assemble the five approved UUID-bound hero assets from the approved MetricPlan, immutable CameraContract, approved Scene_Canon, and hash-bound asset bindings
    - Include mandatory fidelity/set dressing: ceiling fan, wall mirror, area rug, telephone side table, table lamp, foreground sofa, trophy shelf/trophies, and paintings; preserve the long warm room, wood-plank floor, cream walls, rear and right wooden doors, right-side street-facing window, warm lamp/daylight balance, and approved camera composition
    - Set dressing may use approved, procedural, or non-hero assets but may not be missing, gross placeholders, fused remnants, or visually identity-breaking; produce one Browser room only and do not start fresh qualification or engine polish
    - _Requirements: 38.2-38.6, 39.6-39.10, 40.1, 40.2_

  - [ ] 11.8.7 Pass Golden Room SceneVisualGate and Browser playability
    - From the approved camera, require the final room to be immediately recognizable as `danny-v4-01-canon_00002_.png`, with all five hero assets, complete fidelity inventory, recognizable shell/composition, material completeness, Plan-consistent transforms, and Golden Room-consistent palette/lighting intent
    - Inspect at least one navigable first-person viewpoint and require the room identity and visual coherence to hold up without claiming pixel identity from the navigable view
    - Verify safe spawn, first-person movement, collision, and access sufficient to inspect every hero asset and mandatory set-dressing region
    - Fail closed on missing inventory, gross placeholders, fused remnants, temporary Pass-1-only materials, identity-breaking substitutions, or visual defects even when structural/hash/parity gates pass; visual success also does not excuse structural failure
    - _Requirements: 39.7-39.14, 40.1, 40.2_

  - [ ] 11.8.8 Demonstrate one functional GAME interaction and one REAL read-only binding
    - Bind one user action to a stable Golden Room object UUID so it changes persistent room GAME state and displays visible score, success, or progress feedback
    - Retain at least one working UUID-bound REAL read-only surface display and verify mode switching changes behavior only, not approved hero assets, set dressing, or room visuals
    - _Requirements: 40.3-40.5, 23.1-23.4, 24.1-24.5, 25.1-25.5_

  - [ ] 11.8.9 Record photo-bound Demo Ready for the exact candidate
    - Bind the record to candidate fingerprint, Demo Profile identity, authoritative source image path/hash, identical mirror verification, workflow path/hash, five hero asset hashes/approvals, full fidelity-inventory verdict, Plan revision, Canonical_Hash where available, SceneVisualGate, playability, GAME proof, REAL proof, and timestamp
    - State explicitly that this photo-bound Demo Ready proves Golden Room reproduction and is not prompt-driven Release Ready, fresh qualification evidence, or Platform Complete
    - Unlock Task 11.7.1 only; Tasks 11.9–11.11 remain inactive
    - _Requirements: 40.1, 40.6-40.9, 42.4, 42.7, 42.8_

- [ ] 11.7.1 Run the replacement clean zero-state V16 smoke pass only after Demo Ready
  - Require Task 11.8.9 Demo Ready evidence for the same exact candidate fingerprint before creating a session
  - Create a brand-new empty V16 Release Profile generalization-benchmark session; never restore, resume, clone, reuse, or relabel a prior session or Demo Profile run
  - Keep this prompt-driven Release Profile evidence distinct from the photo-bound Golden Room Demo Profile
  - Submit exactly: `Danny's kitchenette — a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain.`
  - Traverse and inspect Brief, Dream, Plan, Blockout, geometry-conditioned Canon, objects, standalone assets/materials, World, Compare, physics, WorldContract/hash, compilation/parity, walkability, GAME/REAL behavior, and toggle; all release assets remain fresh
  - Record exact prompt bytes, candidate/source fingerprint, live-vs-mocked status, artifact hashes, revisions, canonical hash, service identities, per-stage verdicts, visual gates, and browser owner
  - If any defect appears, append diagnostic evidence, permanently disqualify the session, return to the first invalidated Task 11.8 leaf, and require another new Task 11.7.1 session after repair; never continue in place
  - _Requirements: 30.1-30.6, 35.6-35.11, 36.1-36.10, 38.12, 41.5-41.7, 42.1-42.7_

- [ ] 11.9 Run five fresh headless rounds only after Demo Ready and Task 11.7.1 pass
  - Require Task 11.8.9 and one clean Task 11.7.1 bound to the same exact candidate fingerprint
  - Use five distinct brand-new empty V16 Release Profile session IDs and the exact 142-byte canonical prompt with SHA-256 `af6759e5d516561fad3fb49b129f02ad27743e273d1345173d59430f462f32ec`; no approved Demo Profile asset may substitute for fresh generation
  - Inspect all affected stages and capture exact eligibility evidence; route any defect through the append-only defect loop and count only fresh clean eligible sessions
  - _Requirements: 35.6-35.11, 36.1-36.10, 40.8, 41.5, 42.5-42.7_

- [ ] 11.10 Run five fresh human-like rounds only after Demo Ready and Task 11.7.1 pass
  - Require Task 11.8.9 and one clean Task 11.7.1 bound to the same exact candidate fingerprint
  - Use five distinct brand-new empty V16 Release Profile session IDs and the exact 142-byte canonical prompt with SHA-256 `af6759e5d516561fad3fb49b129f02ad27743e273d1345173d59430f462f32ec`; exercise real browser navigation, approvals, reconnect/replay, World/Compare inspection, visual gates, and GAME/REAL toggle behavior without mocks
  - Verify V16 page/API/static JavaScript, retained-version links, artifacts/revisions/hashes, and all applicable stages; append and route any defect without reusing its session
  - _Requirements: 35.6-35.11, 36.1-36.10, 40.8, 41.5, 42.5-42.7_

- [ ] 11.11 Final qualification and Release Ready checkpoint
  - Require photo-bound Demo Ready, one clean prompt-driven replacement Task 11.7.1, five eligible headless rounds, and five eligible human-like rounds, all bound to the final candidate and exact prompt
  - Confirm V3–V16 remain stable, V16 is default, switching links are clear, and final V16 page/API/static-JavaScript validation passes
  - Confirm failed sessions remain diagnostic-only, Demo Profile reuse did not enter release evidence, and Platform Complete is not claimed
  - Do not commit during this tasks phase; after clean qualification and explicit release direction, stage only relevant files, use `feat(web): release v16 interface`, and report the clean-version URL, fresh qualifying session URL, exact canonical prompt, and commit hash
  - _Requirements: 36.4-36.12, 40.7-40.9, 41.5-41.7, 42.7-42.10_

### Frozen Diagnostic Spike (outside the active dependency graph)

- [ ] 11.D1 Preserve the Canon-to-geometry spike as frozen diagnostic history
  - Retain existing immutable inputs, outputs, hashes, and verdicts as non-authoritative and release-ineligible evidence
  - Do not run MiniMax, DA3, MoGe, Anima, HY-Pano, WorldNav, WorldStereo, MoVerse, One2Scene, new video/depth generation, or other open-ended model downloads, integration, or capability preflight on the active critical path; the sole model-integration exception is Task 11.8.2a's bounded WorldMirror gate after its explicit user-confirmation checkpoint
  - Allow Task 11.8.3 to consume already-available video-depth recliner evidence only; it receives no authority and must pass the same common StandaloneAssetGate
  - Do not alter UI, qualify/release, activate Tasks 11.9–11.11, weaken gates, launch ComfyUI, or own the Windows Ratchet watch
  - _Requirements: 37.1-37.13, 38.8-38.11, 41.2, 42.9, 42.10_

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
    { "id": 11, "tasks": ["11.0", "11.1", "11.2", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8", "11.8.1", "11.8.2", "11.8.2a", "11.8.3", "11.8.4", "11.8.4a", "11.8.4b", "11.8.4c", "11.8.5", "11.8.6", "11.8.7", "11.8.8", "11.8.9", "11.7.1", "11.9", "11.10", "11.11"], "gate": "Counter/cabinet regression is exact-fingerprint validated; Golden Room source/workflow/mirror hashes are bound; general exploration is frozen; one bounded WorldMirror preflight and explicitly re-authorized local feasibility verdict is recorded; one common recliner bake-off preserves its no-pass evidence; rejected Task 11.8.4a remains immutable; the rejected Task 11.8.4b candidate remains the closest/best-so-far structural baseline as diagnostic evidence only; Task 11.8.4c must hash-bind the authoritative Danny Tornado Art Bible and produce a new refined deterministic candidate that passes the same non-human/common gates and receives explicit hash-bound human approval before Task 11.8.5; five hero assets plus complete fidelity inventory produce a photo-bound Golden Browser room that passes visual/playability/GAME/REAL Demo Ready gates; only then may the distinct exact-kitchenette-prompt Release Profile smoke and five fresh headless plus five fresh human-like rounds qualify release" }
  ]
}
```

## Notes

- **Current governing constraint: reach the photo-bound Golden Room Demo Ready milestone within 6–8 active coding hours.** The WorldMirror decision is one fixed local gate, not permission for open-ended backend research; FAIL/DEFER returns directly to the recliner bake-off. Defer full HY-World worldgen, new model families, and non-blocking polish rather than expanding this path.
- HY-World 2.0 is a candidate backend in the same broad persistent/navigable 3D category, while conversation/Brief/ArtBible, MetricPlan authority, deterministic WorldContract, per-object warehouse, human gates, engine-neutral compilation, and persistent GAME/REAL overlays remain product-owned.
- WorldMirror Phase A is documentation/preflight only. Phase B installation/download and execution require a new explicit user confirmation after measured license, size, storage, isolation, local-only, and cleanup facts are presented; no cloud use is implicit.
- Tasks marked ✓REUSE leverage existing V14 infrastructure (already implemented and tested)
- Human approval gates are mandatory: Blockout, Scene_Canon, Object_Canon, Mesh Shape, and Final World QA; one durable approval writer owns each decision
- The release and fresh-benchmark profiles remain always-fresh and NEVER consult the warehouse before generation; the Demo Profile may reuse only hash-verified, human-approved warehouse assets that pass StandaloneAssetGate.
- GAME remains broadly stubbed beyond the MVP, but Demo Ready requires one minimal UUID-bound interaction that changes persistent GAME state and shows visible progress; REAL retains at least one working read-only binding.
- REAL mode ships with read-only surface binding (one working example)
- The photo-bound Demo Profile reproduces the hash-bound Golden Room; the later Release Profile qualification scene remains the exact Danny's kitchenette prompt and tests fresh prompt-driven generalization.
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
