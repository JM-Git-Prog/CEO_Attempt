# Implementation Plan

## Overview

This spec governs the UPBGE compilation/export path that consumes a WorldContract (produced by either the V14 photo pipeline or the text-to-world LLM path). The implementation is organized into: foundation (already done), UPBGE compilation (next priority after V14 stabilizes), and export/runtime (downstream).

**Priority context:** V14 (photo-to-real-3d-world) is the active development priority. This spec's remaining work activates after V14 produces stable WorldContracts. The UPBGE path then becomes an optional high-quality export for any WorldContract.

## Status Summary

- Tasks 1-2: **COMPLETE** — WorldContract models, unsupported-feature policy, redistribution review
- Tasks 3-4: **COMPLETE** — Semantic commands, relationship solver (working, 84% corpus pass)
- Tasks 5-12: **COMPLETE** — UPBGE sidecar, scene compiler, runtime templates, export adapters, parity gates, provenance, QA, interface versioning (V11 released)
- Task 13: **SUPERSEDED** — V11-era ratchet qualification loop is replaced by simpler V14-aware approach below

## Tasks

- [x] 1. Freeze boundaries and characterize current behavior
  - [x] 1.1 Record the current Godot assembler, Blender prototype, Plan, Camera_Contract, Scene_Graph, and provenance behavior as characterization fixtures.
  - [x] 1.2 Capture known failure fixtures for duplicate counts, missing ceiling fixtures, blocked openings, camera drift, and mismatched transforms.
  - [x] 1.3 Define the unsupported-feature policy and explicit fallback behavior before introducing UPBGE routing.
  - [x] 1.4 Record a license and redistribution decision for the exact UPBGE build before packaging work.
  - _Requirements: 1, 7, 8, 9_

- [x] 2. Define the engine-neutral world contract
  - [x] 2.1 Add versioned models for room shell, openings, instances, materials, lights, camera, physics intent, interactions, and export policy.
  - [x] 2.2 Define canonical JSON serialization, stable ordering, finite-number rules, units, coordinate system, and content hashing.
  - [x] 2.3 Add deterministic conversion from approved Plan, Scene_Graph, Camera_Contract, and appearance intent.
  - [x] 2.4 Reject duplicate IDs, dangling references, invalid dimensions, unsupported relations, and conflicting authorities.
  - [x] 2.5 Verify canonical round trips and equivalent hashes for semantically identical input.
  - _Requirements: 1, 3, 5, 9_

- [x] 3. Introduce typed LLM semantic commands
  - [x] 3.1 Define allowlisted command models for create, remove, replace, relate, style, light, camera-request, physics-intent, and interaction-intent operations.
  - [x] 3.2 Extend planning prompts to emit explicit relationships rather than relying on name keyword inference.
  - [x] 3.3 Implement command validation for identities, references, limits, authorization, relation cycles, and immutable authorities.
  - [x] 3.4 Apply accepted command batches transactionally and emit before/after hashes plus structured rejection reasons.
  - [x] 3.5 Ensure no command field can carry Python, shell commands, executable paths, or engine operators.
  - _Requirements: 2, 3, 8_

- [x] 4. Build the deterministic relationship solver
  - [x] 4.1 Implement constraints for centered, against-wall, adjacent-to, directional, around, above, facing, and near-corner relationships.
  - [x] 4.2 Resolve rotation-aware bounds, opening keep-clear volumes, requested clearances, mount heights, and camera occupancy.
  - [x] 4.3 Preserve authored intent through weighted constraints and return unsatisfied constraints instead of overlapping fallback placement.
  - [x] 4.4 Produce a solver report mapping every relation to satisfied, relaxed, or blocked status.
  - [x] 4.5 Replace broad text-keyword movement only for the new workflow profile; preserve retained behavior.
  - _Requirements: 1, 2, 3, 5_

- [x] 5. Implement UPBGE capability discovery and sidecar isolation
  - [x] 5.1 Replace Blender-only discovery with pinned UPBGE-first discovery through configuration, known locations, and PATH.
  - [x] 5.2 Probe executable identity, version, Blender API version, game-runtime capability, Eevee support, and glTF exporter support.
  - [x] 5.3 Launch compilation in a restricted subprocess with read-only input, a unique output directory, no inherited secrets, bounded resources, and timeout handling.
  - [x] 5.4 Pass options explicitly so render, `.blend`, GLB, and runtime packaging can be independently enabled.
  - [x] 5.5 Return structured capability and failure reports without silently substituting regular Blender.
  - _Requirements: 4, 8, 9, 11_

- [x] 6. Replace the Blender prototype with a contract-driven scene compiler
  - [x] 6.1 Make the compiler consume canonical World_Contract input instead of mutable `session.json`.
  - [x] 6.2 Generate solid room geometry with real door/window apertures and stable opening IDs.
  - [x] 6.3 Compile objects from explicit geometry/asset strategies without name-based physics inference.
  - [x] 6.4 Preserve contract transforms, mounts, materials, identities, and instance counts.
  - [x] 6.5 Apply the Camera_Contract with exact axis conversion, vertical FOV, clipping planes, aspect, and raster.
  - [x] 6.6 Export GLB extras, save `.blend`, render a neutral reference, and honor each requested output flag.
  - _Requirements: 1, 5, 7, 8_

- [x] 7. Add versioned UPBGE runtime templates
  - [x] 7.1 Implement first-person spawn, movement, collision, gravity, pause, and exit as first-party templates.
  - [x] 7.2 Implement allowlisted door and grabbing interactions with validated parameters.
  - [x] 7.3 Configure static, kinematic, dynamic, and trigger bodies from physics intent.
  - [x] 7.4 Persist dynamic runtime state separately from the approved World_Contract.
  - [x] 7.5 Package or launch the playable runtime only after capability and parity gates pass.
  - _Requirements: 6, 8, 9_

- [x] 8. Implement portable export adapters
  - [x] 8.1 Define a common ExportAdapter result contract with artifacts, capabilities, unsupported features, diagnostics, and manifests.
  - [x] 8.2 Adapt the existing Godot assembler to consume World_Contract while retaining historical behavior behind existing profiles.
  - [x] 8.3 Add GLB plus metadata output suitable for Three.js GLTFLoader.
  - [x] 8.4 Preserve stable IDs, units, axes, cameras, lights, materials, and target-independent interaction metadata.
  - [x] 8.5 Return explicit unsupported-feature results for target-specific behavior without silent semantic loss.
  - _Requirements: 1, 7, 11_

- [x] 9. Add structural parity and runtime smoke gates
  - [x] 9.1 Export a machine-readable UPBGE scene inventory for rooms, openings, objects, lights, cameras, physics, and interactions.
  - [x] 9.2 Compare inventory to World_Contract with explicit numeric tolerances and exact count/identity checks.
  - [x] 9.3 Add GLB reload validation for finite geometry, bounds, extras, cameras, and lights.
  - [x] 9.4 Add an UPBGE smoke harness for load, player spawn, movement, collision, door traversal, and required interactions.
  - [x] 9.5 Reject artifacts on mandatory parity or runtime failures and preserve diagnostics.
  - _Requirements: 5, 6, 7, 10_

- [x] 10. Integrate compiler provenance and pipeline routing
  - [x] 10.1 Add immutable prepared and terminal Compiler_Manifest records with exact inputs, versions, hashes, timings, and diagnostics.
  - [x] 10.2 Add UPBGE output and reports to WorldSession, workflow snapshots, telemetry, and artifact metadata.
  - [x] 10.3 Add profile-controlled UPBGE, Godot, and fallback routing to WorldBuilder without changing retained sessions.
  - [x] 10.4 Stop mutating `SceneConcept.key_objects`; generate plan-derived conditioning and compile metadata as separate immutable fields.
  - [x] 10.5 Ensure recompilation never overwrites historical artifacts or manifests.
  - _Requirements: 1, 9, 11_

- [x] 11. Integrate automated and human QA
  - [x] 11.1 Run qwen2.5vl:7b on Floor Plan, Blockout, and Canon with the seven-category rubric and strict pass/confidence output.
  - [x] 11.2 Require human adjudication for failed, unavailable, or confidence-below-0.8 vision results.
  - [x] 11.3 Bind QA entries to artifact hashes, interface/profile identity, plan revision, and Canon attempt.
  - [x] 11.4 Add supersession links and deduplicate repeated submissions without deleting append-only history.
  - [x] 11.5 Include UPBGE reference render, parity report, and runtime smoke status in QA evidence.
  - _Requirements: 10_

- [x] 12. Introduce a new immutable workflow profile and interface version
  - [x] 12.1 Add a new interface/profile instead of modifying V9 or V10 behavior.
  - [x] 12.2 Reject unsupported future interface versions rather than coercing them to V10.
  - [x] 12.3 Add version-switch links and keep all preceding released interfaces accessible and stable.
  - [x] 12.4 Expose truthful compiler target, native/fallback status, versions, failures, and downloadable portable artifacts.
  - [x] 12.5 Validate the new page, relevant APIs, and static JavaScript while running retained-version checks.
  - _Requirements: 9, 11_

- [ ] 13. V14 WorldContract → UPBGE export integration
  - [ ] 13.1 Verify V14 WorldContract output is compatible with existing UPBGE Scene_Compiler input
    - Confirm V14's `geometry_strategy: "asset"` with real GLB meshes feeds correctly into the UPBGE compilation path
    - Validate that V14's PhysicsIntent (DYNAMIC/STATIC with mass, friction, restitution) maps to UPBGE physics bodies
    - Test the Room_Shell_Mesh GLB can be imported as UPBGE room geometry
  - [ ] 13.2 Add V14-specific UPBGE compilation options
    - Import real textured GLB meshes (from Hunyuan3D/Trellis2) as UPBGE objects instead of primitive geometry
    - Map V14's two-pass PBR materials (metallic, roughness, normal) to UPBGE Eevee materials
    - Preserve V14's dynamic/static physics classification in UPBGE body configuration
  - [ ] 13.3 Run structural parity between V14 WorldContract and UPBGE-compiled scene
    - Object count, identities, transforms, dimensions must match within tolerance
    - Physics body modes must match WorldContract PhysicsIntent
    - Room shell geometry must preserve depth-reconstructed shape
  - [ ] 13.4 Run runtime smoke on UPBGE package compiled from V14 WorldContract
    - Player spawn, first-person movement, collision with real meshes
    - Dynamic objects respond to physics (grabbable items)
    - Static objects remain immovable
    - Door/opening traversal if applicable
  - _Requirements: 1, 5, 6, 7, 9, 10_

- [ ] 14. Photo-to-2D-CAD flywheel data capture
  - [ ] 14.1 Implement floor plan projector that converts V14 3D layout to 2D CAD JSON
    - Project object (x, z) positions to top-down (x, y) coordinates
    - Convert ScaleResult dimensions to footprint rectangles
    - Extract room boundary polygon from depth-reconstructed room shell
    - Mark openings (doors/windows) with positions and widths
  - [ ] 14.2 Implement corpus capture hook in V14 pipeline
    - After successful V14 WorldContract assembly, extract training pair (photo, cad_json)
    - Append to `data/flywheel/corpus.jsonl` (deduplicated, append-only)
    - Include metadata: session_id, source_photo_hash, object_count, generation_quality
  - [ ] 14.3 Implement diversity batch runner for corpus expansion
    - Process photos from public datasets (3D-FRONT, ScanNet renders) through V14
    - Cycle least-sampled room types first
    - Run at idle priority (yield to active V14 sessions)
    - Target: 500+ labeled pairs before F2 training gate
  - _Requirements: 1 (WorldContract as ground truth)_

## Task Dependency Graph

```json
{
  "waves": [
    {"wave": 1, "tasks": ["1"]},
    {"wave": 2, "tasks": ["2"]},
    {"wave": 3, "tasks": ["3", "4"]},
    {"wave": 4, "tasks": ["5"]},
    {"wave": 5, "tasks": ["6"]},
    {"wave": 6, "tasks": ["7", "8"]},
    {"wave": 7, "tasks": ["9"]},
    {"wave": 8, "tasks": ["10"]},
    {"wave": 9, "tasks": ["11"]},
    {"wave": 10, "tasks": ["12"]},
    {"wave": 11, "tasks": ["13"]},
    {"wave": 12, "tasks": ["14"]}
  ]
}
```

Task 13 depends on V14 being stable (photo-to-real-3d-world-v14 spec tasks largely complete).
Task 14 depends on Task 13 (needs V14 producing reliable WorldContracts to generate training data).

## Notes

- Tasks 1-12 are COMPLETE — the UPBGE compilation infrastructure exists and works.
- Task 13 bridges V14's real-mesh WorldContract output to the existing UPBGE compiler.
- Task 14 begins the photo-to-2D-CAD SLM training data pipeline (see `self-learning-flywheel-design.md`).
- UPBGE installation, redistribution, and version pinning remain governed by `upbge-redistribution-decision.md` (BLOCKED status unchanged).
- No task authorizes arbitrary model-generated code execution.
- Historical profiles and interfaces remain behaviorally stable.
- V14 implementation (photo-to-real-3d-world-v14 spec) takes priority over tasks 13-14.
