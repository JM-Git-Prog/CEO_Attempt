# Implementation Plan

## Overview

Implement the engine-neutral contract and safety boundary first, then add UPBGE compilation/runtime, portability adapters, evidence gates, and finally a new versioned product release. Tasks preserve existing released behavior until the new profile passes fresh-session qualification.

## Current Execution

- **Overall task:** `13. Complete release qualification` — **IN PROGRESS**
- **Current subtask:** `13.5.3` — All 3 TRAINING-REAIM solver/target fixes applied: (A) against_wall slides past openings, adjacent_to clamped to bounds; (B) synthesized-centered replaced with distributed wall placement; (C) training target strips x/z/rotation_deg. Corpus pass rate: 22% → 84%. Training set regenerated (202 train, 50 holdout). Next: retrain LoRA on corrected target, then re-measure stochastic pass rate.
- **MVP guardrail:** Deliver a usable end-to-end MVP within 6–8 active coding hours; timebox deep work and defer anything not blocking the clean V11 pass.
- **Latest validated checkpoint:** Tests passing (85/85 targeted suite, compileall+node clean). Solver fixes verified against full corpus (84.3% pass rate vs prior 22%). Training target regenerated without solver-owned fields. Commits: `f103af6` (Tier 0 fixes), `bbd97f8` (against_wall + adjacent_to), `ff74d8e` (centered default + training target).

## Tasks


- [x] 1. Freeze boundaries and characterize current behavior
  - [x] 1.1 Record the current Godot assembler, Blender prototype, Plan, Camera_Contract, Scene_Graph, and provenance behavior as characterization fixtures.
  - [x] 1.2 Capture known failure fixtures for duplicate counts, missing ceiling fixtures, blocked openings, camera drift, and mismatched transforms.
  - [x] 1.3 Define the unsupported-feature policy and explicit fallback behavior before introducing UPBGE routing.
  - [x] 1.4 Record a license and redistribution decision for the exact UPBGE build before packaging work.
  - _Requirements: 1, 7, 8, 9, 12_

- [x] 2. Define the engine-neutral world contract
  - [x] 2.1 Add versioned models for room shell, openings, instances, materials, lights, camera, physics intent, interactions, and export policy.
  - [ ] 2.2 Define canonical JSON serialization, stable ordering, finite-number rules, units, coordinate system, and content hashing.
  - [ ] 2.3 Add deterministic conversion from approved Plan, Scene_Graph, Camera_Contract, and appearance intent.
  - [ ] 2.4 Reject duplicate IDs, dangling references, invalid dimensions, unsupported relations, and conflicting authorities.
  - [ ] 2.5 Verify canonical round trips and equivalent hashes for semantically identical input.
  - _Requirements: 1, 3, 5, 9_

- [x] 3. Introduce typed LLM semantic commands
  - [ ] 3.1 Define allowlisted command models for create, remove, replace, relate, style, light, camera-request, physics-intent, and interaction-intent operations.
  - [ ] 3.2 Extend planning prompts to emit explicit relationships rather than relying on name keyword inference.
  - [ ] 3.3 Implement command validation for identities, references, limits, authorization, relation cycles, and immutable authorities.
  - [ ] 3.4 Apply accepted command batches transactionally and emit before/after hashes plus structured rejection reasons.
  - [ ] 3.5 Ensure no command field can carry Python, shell commands, executable paths, or engine operators.
  - _Requirements: 2, 3, 8_

- [x] 4. Build the deterministic relationship solver
  - [ ] 4.1 Implement constraints for centered, against-wall, adjacent-to, directional, around, above, facing, and near-corner relationships.
  - [ ] 4.2 Resolve rotation-aware bounds, opening keep-clear volumes, requested clearances, mount heights, and camera occupancy.
  - [ ] 4.3 Preserve authored intent through weighted constraints and return unsatisfied constraints instead of overlapping fallback placement.
  - [ ] 4.4 Produce a solver report mapping every relation to satisfied, relaxed, or blocked status.
  - [ ] 4.5 Replace broad text-keyword movement only for the new workflow profile; preserve retained behavior.
  - _Requirements: 1, 2, 3, 5, 10_

- [x] 5. Implement UPBGE capability discovery and sidecar isolation
  - [ ] 5.1 Replace Blender-only discovery with pinned UPBGE-first discovery through configuration, known locations, and PATH.
  - [ ] 5.2 Probe executable identity, version, Blender API version, game-runtime capability, Eevee support, and glTF exporter support.
  - [ ] 5.3 Launch compilation in a restricted subprocess with read-only input, a unique output directory, no inherited secrets, bounded resources, and timeout handling.
  - [ ] 5.4 Pass options explicitly so render, `.blend`, GLB, and runtime packaging can be independently enabled.
  - [ ] 5.5 Return structured capability and failure reports without silently substituting regular Blender.
  - _Requirements: 4, 8, 9, 11_

- [x] 6. Replace the Blender prototype with a contract-driven scene compiler
  - [ ] 6.1 Make the compiler consume canonical World_Contract input instead of mutable `session.json`.
  - [ ] 6.2 Generate solid room geometry with real door/window apertures and stable opening IDs.
  - [ ] 6.3 Compile objects from explicit geometry/asset strategies without name-based physics inference.
  - [ ] 6.4 Preserve contract transforms, mounts, materials, identities, and instance counts.
  - [ ] 6.5 Apply the Camera_Contract with exact axis conversion, vertical FOV, clipping planes, aspect, and raster.
  - [ ] 6.6 Export GLB extras, save `.blend`, render a neutral reference, and honor each requested output flag.
  - _Requirements: 1, 5, 7, 8_

- [x] 7. Add versioned UPBGE runtime templates
  - [ ] 7.1 Implement first-person spawn, movement, collision, gravity, pause, and exit as first-party templates.
  - [ ] 7.2 Implement allowlisted door and grabbing interactions with validated parameters.
  - [ ] 7.3 Configure static, kinematic, dynamic, and trigger bodies from physics intent.
  - [ ] 7.4 Persist dynamic runtime state separately from the approved World_Contract.
  - [ ] 7.5 Package or launch the playable runtime only after capability and parity gates pass.
  - _Requirements: 6, 8, 9_

- [x] 8. Implement portable export adapters
  - [ ] 8.1 Define a common ExportAdapter result contract with artifacts, capabilities, unsupported features, diagnostics, and manifests.
  - [ ] 8.2 Adapt the existing Godot assembler to consume World_Contract while retaining historical behavior behind existing profiles.
  - [ ] 8.3 Add GLB plus metadata output suitable for a future Three.js loader.
  - [ ] 8.4 Preserve stable IDs, units, axes, cameras, lights, materials, and target-independent interaction metadata.
  - [ ] 8.5 Return explicit unsupported-feature results for target-specific behavior without silent semantic loss.
  - _Requirements: 1, 7, 11_

- [x] 9. Add structural parity and runtime smoke gates
  - [ ] 9.1 Export a machine-readable UPBGE scene inventory for rooms, openings, objects, lights, cameras, physics, and interactions.
  - [ ] 9.2 Compare inventory to World_Contract with explicit numeric tolerances and exact count/identity checks.
  - [ ] 9.3 Add GLB reload validation for finite geometry, bounds, extras, cameras, and lights.
  - [ ] 9.4 Add an UPBGE smoke harness for load, player spawn, movement, collision, door traversal, and required interactions.
  - [ ] 9.5 Reject artifacts on mandatory parity or runtime failures and preserve diagnostics.
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
  - _Requirements: 10, 12_

- [x] 12. Introduce a new immutable workflow profile and interface version
  - [x] 12.1 Add a new interface/profile instead of modifying V9 or V10 behavior.
  - [x] 12.2 Reject unsupported future interface versions rather than coercing them to V10.
  - [x] 12.3 Add version-switch links and keep all preceding released interfaces accessible and stable.
  - [x] 12.4 Expose truthful compiler target, native/fallback status, versions, failures, and downloadable portable artifacts.
  - [x] 12.5 Validate the new page, relevant APIs, and static JavaScript while running retained-version checks.
  - _Requirements: 9, 11, 12_

- [-] 13. Complete release qualification
  - [x] 13.1 Run focused model, solver, compiler, parity, manifest, and adapter validation.
  - [x] 13.2 Run UPBGE capability, GLB load, runtime smoke, Godot fallback, and target portability checks.
  - [ ] 13.3 Create a brand-new empty session and run the canonical prompt on the exact target commit.
  - [ ] 13.4 Inspect Brief, Plan, Blockout, Canon, World, Compare, manifests, parity, runtime, and QA evidence.
  - [-] 13.5 If any defect appears, record and fix it, discard the session, and restart from another new empty session.
    - [x] 13.5.1 Record/discard `c3dd343b` and add V11-only full rotation-aware bounds composition qualification before Camera_Contract approval.
    - [-] 13.5.2 Implement the tiered Ratchet Loop from `ratchet-loop-design.md` with immutable evidence and fresh sessions only.
      - [x] 13.5.2.1 Remove the phantom focused-test pass; Tier 0 runs compileall, Node syntax, and the full suite once.
      - [x] 13.5.2.2 Add deterministic environment-forced mock E2E with mock-only alignment `not_applicable` when required.
      - [x] 13.5.2.3 Normalize adapter failures to stable `stage/rule/detail` signatures.
      - [x] 13.5.2.4 Write atomic `scoreboard.json` and `NEXT.md` keyed by fingerprint × lane with KEEP/REVERT/INDETERMINATE.
      - [x] 13.5.2.5 Add K=2 parallel fresh-session sampling, N=5 early stop, and GPU-busy guard.
      - [x] 13.5.2.6 Add `lanes.json` with all remote/spend lanes disabled by default and capped.
      - [x] 13.5.2.7 Add the 0.8 rolling formal trigger, serialized Tier 3, QUALIFIED, STUCK, and BUDGET stops.
      - [x] 13.5.2.8 Add passive flywheel F0 corpus backfill and idle/preemptible extraction; keep F1+ blocked on `QUALIFIED.md`.
    - [ ] 13.5.3 Validate the loop, rerun full/static checks, and restart `13.3` with another brand-new empty session.
  - [ ] 13.6 Only after one clean pass, stage relevant files and prepare the required release record; do not commit unless explicitly requested.
  - _Requirements: 10, 11, 12_

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
    {"wave": 11, "tasks": ["13"]}
  ]
}
```

Tasks 3 and 4 may proceed in parallel after Task 2. Task 7 runtime work and Task 8 adapter work may proceed in parallel after the compiler contract stabilizes. Product UI/version work begins only after compiler, parity, provenance, and QA paths are operational.

## Notes

- UPBGE installation, redistribution, and version pinning require explicit approval and license review.
- No task authorizes arbitrary model-generated code execution.
- Historical profiles and interfaces must remain behaviorally stable.
- A failed test session is diagnostic evidence, never release evidence.
- Do not commit implementation or release changes unless the user explicitly requests a commit.
