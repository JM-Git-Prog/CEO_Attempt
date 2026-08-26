# Recliner Canon Visual Refinement Fix Bugfix Design

## Overview

This bugfix closes the complete Golden Room visual defect: starting from the immutable locked Canon and the exact existing empty twin, it assembles the complete approved 3D world and renders one deterministic `1024×768` Golden Room proof PNG that must satisfy a calibrated, fail-closed 95% contract. The detailed recliner v2 repair remains mandatory, but a passing recliner alone cannot pass the room or unblock Task 11.8.5.

The implementation will extend existing deterministic proof and validation paths rather than regenerate Canon, revise the approved Plan, start another model lane, or create a long-running agent process. Each invocation performs exactly one bounded iteration, writes an append-only event chain and atomic continuation checkpoint, then exits. A later explicit invocation or the already Windows-owned loop may consume the checkpoint without any ownership or configuration change. Every failure receives a fresh iteration ID; no failed iteration is resumed in place or promoted.

Success is ordered and exact-hash bound: immutable-reference lock, calibrated scoring contract, complete 3D assembly, structural/build/import/world-load/render checks, isolated dual replay, hard gates, `I/G/L/M/P` floors and `S >= 95.000000`, strict local qwen screening, independent primary adjudication, and finally explicit human approval of the exact evidence. Only that last approval permits `VALIDATED_SUCCESS` and a KiroGraph Solution. No state is named `COMMITTED`, and this work performs no staging or commit.

## Glossary

- **Bug_Condition (C)**: The locked Golden Room inputs produce, or are represented by, a deterministic 3D proof assembly that is sparse, blocky, incomplete, identity-breaking, uncalibrated, non-replayable, or below any hard gate/category floor, including the recliner v2 subgate.
- **Property (P)**: One fresh iteration produces a complete deterministic assembled-world PNG and exact evidence that passes every locked machine, visual, and human gate without changing an authority contract or historical artifact.
- **Preservation**: Byte-for-byte retention of locked inputs, prior candidates/evidence, authority contracts, UI/session/process/task/repository boundaries, and unrelated working-tree changes.
- **Locked Canon**: `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png`, SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6`; appearance/composition evidence only.
- **Locked empty twin**: Existing own output `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-02-twin_00002_.png`, 1,372,293 bytes, SHA-256 `2f67a5f3d3b44a4fb1eacf1ada5e57d4fbf401662358b01ccf087c4a83a59103`; immutable room/scene evidence only.
- **MetricPlan**: Sole authority for dimensions, transforms, placement, architecture, openings, collision, and navigation.
- **CameraContract**: Sole immutable Plan-derived camera authority.
- **WorldContract**: Final UUID, object, relationship, interaction, and binding authority.
- **CanonDecompositionPack**: Locked inventory, stable identities, masks, appearance cues, and relationships derived from Canon; evidence, not spatial authority.
- **Render contract**: Versioned manifest locking references, contracts, assets, renderer/engine versions, full-frame camera and raster settings, color management, masks, metrics, calibration, and scorer implementation.
- **Canonical pixel hash**: SHA-256 of a version tag, width, height, channel mode, and decoded row-major pixel bytes, independent of PNG metadata.
- **Hard gate**: A binary prerequisite that cannot be compensated by any score.
- **Critical submetric floor**: A calibrated minimum for one object, opening, region, or perceptual family; averages cannot hide its failure.
- **Primary adjudication**: Independent non-human inspection of the exact machine-passing evidence after qwen. It is not human approval.
- **Iteration**: One never-reused ID, immutable input snapshot, at most one bounded causal change, one build/validation attempt, and one checkpoint.
- **Problem / Attempt / Solution**: Exactly one Problem and Attempt audit observation per iteration; Solution exists only after full validation and explicit exact-hash human approval.

## Bug Details

### Bug Condition

The current three-panel proof is structurally useful diagnostic evidence but is not a complete calibrated Golden Room match. The existing proof code identifies the empty twin by path but does not include it in `EXPECTED_HASHES`; `combine_contact_sheet` fits three images into review panels rather than preserving the required full-frame scoring protocol; and `build_evidence` proves shell/recliner structure, not complete inventory, engine load, calibrated room metrics, replay, or human-approved convergence. The current recliner candidate also remains visually rigid despite passing optimistic qwen screening.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type GoldenRoomIteration
  OUTPUT: boolean

  referencesValid := exactUniqueLockedReferences(input)
  contractValid := calibratedImmutableRenderAndScoringContract(input)
  completeWorld := exactInventoryCountsAndUUIDs(input)
                   AND approvedMetricPlanCameraWorldBindings(input)
                   AND candidateIsRenderedComplete3DWorld(input)
  reclinerValid := mandatoryReclinerV2Gate(input)
  machineValid := buildImportWorldLoadRenderChecks(input)
                  AND glbMaterialUriChecks(input)
                  AND exactDualReplay(input)
  visualValid := allHardGatesPass(input)
                 AND input.I >= 95
                 AND input.G >= 95
                 AND input.L >= 95
                 AND input.M >= 90
                 AND input.P >= 95
                 AND input.S >= 95.000000
                 AND allCriticalSubmetricsPass(input)
  reviewValid := strictQwenPass(input)
                 AND independentPrimaryPass(input)
                 AND exactHashHumanApproval(input)

  RETURN NOT referencesValid
      OR NOT contractValid
      OR NOT completeWorld
      OR NOT reclinerValid
      OR NOT machineValid
      OR NOT visualValid
      OR NOT reviewValid
END FUNCTION
```

### Desired Property

```
FUNCTION expectedBehavior(result)
  INPUT: result of type GoldenRoomIterationResult
  OUTPUT: boolean

  RETURN result.iterationIdIsFresh
    AND result.priorBytesUnchanged
    AND result.completeInventoryExact
    AND result.authorityBindingsValid
    AND result.proofOrigin == "complete_3d_world_fixed_camera_render"
    AND result.renderProtocolHash == result.calibration.renderProtocolHash
    AND result.replayA.semanticHashes == result.replayB.semanticHashes
    AND result.allHardGatesPass
    AND result.I >= 95 AND result.G >= 95 AND result.L >= 95
    AND result.M >= 90 AND result.P >= 95
    AND result.S >= 95.000000
    AND result.reclinerV2Pass
    AND result.qwenPass AND result.primaryPass
    AND result.humanApproval.bindsEveryRequiredHash
    AND result.state == "VALIDATED_SUCCESS"
    AND result.kirograph.problemCount == 1
    AND result.kirograph.attemptCount == 1
    AND result.kirograph.solutionCount == 1
    AND result.task11_8_5 == "BLOCKED_NOT_STARTED"
    AND result.stagedOrCommitted == false
END FUNCTION
```

### Examples

- The current sparse proof has valid files but omits or degrades required inventory and has no calibrated score. Expected: `BLOCKED_UNCALIBRATED` before a percentage is advertised.
- Two files named like the empty twin exist, or the exact path hashes differently. Expected: `INITIALIZE_REFERENCES` fails closed; no replacement or regeneration is selected.
- Every object except one trophy is correct. Expected: inventory hard gate fails even if average mask IoU and composite would exceed 95.
- A candidate scores `S=96.2`, but one opening has the wrong topology, one critical chair mask is below its floor, or `P=94.99`. Expected: failed diagnostic iteration.
- A machine-passing candidate gets a qwen pass but primary adjudication finds sparse/blocky artifacts. Expected: primary failure, fresh next iteration, no human request.
- Machine, qwen, and primary gates pass but no explicit exact-hash human approval exists. Expected: `AWAITING_EXPLICIT_HUMAN_REVIEW`, not `VALIDATED_SUCCESS` and no Solution.
- A build fails because a GLB URI is unsafe. Expected: preserve the iteration, record that exact build error as Problem, make URI repair the sole next change, checkpoint, and start a fresh ID later.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Preserve the Task 11.8.4b structural baseline, failed Task 11.8.4c candidate, all earlier proof/evidence bytes, hashes, chronology, verdicts, and diagnostic-only eligibility.
- Preserve Canon, Art Bible, exact empty twin, approved MetricPlan, CameraContract, WorldContract input, decomposition/inventory, asset bytes, and their authority boundaries. Canon and empty twin never revise Plan or camera.
- Preserve `src/unified_pipeline/plan_generator.py::revise` behavior; this bugfix must not call it. Any Plan mismatch is a blocker, not permission to revise spatial truth.
- Preserve exact inventory/stable UUID semantics from `src/unified_pipeline/object_manifest.py::build_plan_bound_selected_manifest`; segmentation observations from `ObjectIsolator.segment` never replace Plan identity.
- Preserve the existing StandaloneAssetGate order and all recliner criteria. Room scoring supplements rather than dilutes them.
- Preserve routes, APIs, pages, selectors, static JavaScript, default/retained UI versions, sessions, qualification state, Task 11.8.4c state, and Task 11.8.5 `BLOCKED_NOT_STARTED`.
- Preserve Windows ownership of the Ratchet loop/keepalive and Comfy Desktop ownership of port 8188. No agent terminal owns a watcher/server and no Scheduled Task, hook, or owner configuration changes.
- Preserve unrelated hook/worktree changes exactly; do not stage, reset, clean, rewrite, or claim them.
- Use no cloud service, dependency/model download, new geometry model, restored session, qualification run, staging, or commit.

**Scope:**
Only later implementation files explicitly named below, focused tests, and brand-new append-only iteration evidence may change. Historical evidence and references are read-only. Partial, best-so-far, interrupted, or failed iterations remain diagnostic and cannot unblock downstream work.

## Hypothesized Root Cause

1. **Proof scope is too narrow**: `tools/canon_decomposition_upbge_proof.py::worker_main` and `build_evidence` prove a deterministic shell/recliner diagnostic, not a complete WorldContract-bound Golden Room.
2. **Empty-twin lock is incomplete**: `EMPTY_TWIN_PATH` is exact, but it is absent from `EXPECTED_HASHES`; discovery therefore does not yet prove uniqueness and byte identity.
3. **Contact-sheet transforms are unsuitable for scoring**: `combine_contact_sheet` uses `ImageOps.fit` to crop/resize panels. That is acceptable for labeled review only, never metric input.
4. **Inventory truth is split**: the proof's item table, ObjectIsolator masks, Plan-selected manifest, and WorldContract must be reconciled by stable UUID and exact count before rendering; optimistic average overlap cannot establish inventory.
5. **Existing comparison gates are necessary but not numerical 95% proof**: `ThreeViewIdentityComparator.compare` enforces identity, geometry, overlap, and appearance, while `store_evidence` is immutable, but neither defines calibrated full-frame `I/G/L/M/P` scoring.
6. **Available metric capability is incomplete**: the active interpreter has Pillow 12.0.0, NumPy 2.2.6, SciPy 1.18.0, and OpenCV 4.12.0, but no `cv2.quality`, scikit-image, torch, torchvision, LPIPS, or PIQ. Structural/color/feature metrics are feasible locally; a learned-perceptual metric must be discovered as an already-installed exact-hash capability or scoring must remain `BLOCKED_UNCALIBRATED`.
7. **Engine evidence is fragmented**: `strict_real_handlers.handle_compile` and `handle_automated_final_validation` provide the qualified Browser compile and contract/asset checks, but the convergence proof must also perform bounded import, world-load, and fixed-camera render smoke checks and bind those results.
8. **Recliner surfaces are under-modeled**: flat rounded boxes, an upright/tall back, squared arm layering, exposed dark structure, weak footrest continuity, and insufficient material auditing produce the known rigid chair failure.
9. **No durable one-iteration protocol exists**: current scripts do not enforce one fresh identity per failure, hash-chained events, atomic continuation, exactly-one KiroGraph Problem/Attempt, or bottleneck-first one-change planning.
10. **Optimistic screening can overrule perception unless ordered**: qwen passed the failed chair; deterministic gates and independent primary adjudication must precede human review, and only explicit human approval may establish Solution.

## Correctness Properties

Property 1: Bug Condition - Complete Golden Room convergence

_For any_ fresh iteration where the bug condition holds, the system SHALL either produce a complete fixed-camera 3D proof assembly that passes the immutable contract, exact dual replay, all hard gates and submetric floors, the calibrated `I/G/L/M/P` formula, mandatory recliner v2, strict qwen, independent primary adjudication, and exact-hash human approval, or fail closed with append-only diagnostic evidence and no promotion.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.27, 2.28, 2.29, 2.30**

Property 2: Preservation - Authorities, evidence, scope, and blocking

_For any_ input or behavior outside the fresh candidate's bounded causal change, the fixed path SHALL preserve prior bytes and verdicts, MetricPlan/CameraContract/WorldContract authority, inventory UUIDs, common gate order, local process ownership, UI/session/qualification/task/repository state, and unrelated changes, while Task 11.8.5 remains blocked.

**Validates: Requirements 2.7, 2.8, 2.9, 2.14, 2.30, 2.31, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18**

Property 3: Calibration - No uncalibrated or candidate-tuned 95% claim

_For any_ scoring attempt, the scorer SHALL use one pre-candidate immutable calibration/render contract with sufficient accepted, rejected, exact-positive, and synthetic single-category controls; any missing capability, inseparable metric, contract drift, candidate-specific alignment/reweighting, or unavailable component SHALL yield `BLOCKED_UNCALIBRATED` rather than a score.

**Validates: Requirements 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 3.16**

Property 4: Iteration durability - Fresh bounded replayable work

_For any_ failed or interrupted bounded invocation, the runner SHALL atomically checkpoint the exact terminal evidence, exit, and require a never-reused iteration ID for the next attempt; it SHALL never loop into a second attempt in the same invocation or depend on an agent process remaining alive.

**Validates: Requirements 2.23, 2.24, 2.29, 2.31, 3.17**

Property 5: Audit lifecycle - Solution requires exact approval

_For any_ iteration, exactly one Problem and one Attempt SHALL be durable locally and delivered idempotently to KiroGraph, while a Solution SHALL exist if and only if the same iteration is fully validated and explicitly human-approved against the complete exact-hash evidence set.

**Validates: Requirements 2.25, 2.26**

## Fix Implementation

### Existing Integration Points

| Existing path / symbol | Designed use |
|---|---|
| `src/unified_pipeline/plan_generator.py::revise` | Negative boundary: never call; approved Plan/hash remains spatial authority. |
| `src/unified_pipeline/object_manifest.py::build_plan_bound_selected_manifest` and `load_selected_manifest` | Lock exact Plan instance IDs, counts, Canon/Plan/Camera/approval hashes, including the built-in counter. |
| `src/unified_pipeline/object_isolator.py::ObjectIsolator.segment` | Read existing UUID-mapped Canon masks as evidence only; do not rerun SAM or accept skipped/uncertain objects for this milestone. |
| `src/unified_pipeline/room_plate.py::RoomPlateGenerator.generate` | Negative boundary: do not regenerate the existing twin and do not accept its degraded Canon fallback. Lock the exact existing twin instead. |
| `src/unified_pipeline/canon_generator.py::SceneCanonGenerator.generate` | Negative boundary: Canon is already locked; preserve its Plan/Camera binding and do not regenerate. |
| `src/unified_pipeline/mesh_generators.py::{UnifiedHunyuan3DGenerator, UnifiedTrellis2Generator, UnifiedPlaceholderGenerator}` | Verify provenance. Existing approved real assets may be assembled; placeholder generator output is a hard failure. No model invocation/download is introduced. |
| `src/photo_pipeline/stages/mesh_validator.py::validate_mesh` | Reuse minimum independent textured-mesh load checks, supplemented by proof-level GLB/container/material/URI inspection. |
| `src/unified_pipeline/strict_real_handlers.py::{handle_compile, handle_automated_final_validation}` | Reuse strict Browser compile, selected-set equality, real-mesh provenance, camera/contract, room, collision, compiled asset, spawn, and movement checks. |
| `src/unified_pipeline/resource_arbiter.py::UnifiedResourceArbiter.claim` / `execute` | Use existing bounded ownership only when an already-installed local GPU operation is needed; no new owner or background process. Timeout is failure evidence, never a skipped metric. |
| `src/unified_pipeline/canon_compare.py::ThreeViewIdentityComparator.compare` / `store_evidence` | Keep existing identity/geometry/overlap/appearance gate and immutable exclusive-create evidence; add room score as a stricter sibling gate, not replacement. |
| `src/qa_evidence.py::{run_qwen_screening, AppendOnlyQALedger.append}` | Reuse strict local vision and append-only exact-submission deduplication patterns. Human evidence remains separate and last. |
| `tools/canon_decomposition_upbge_proof.py::{verify_immutable_inputs, inspect_glb, combine_contact_sheet, build_evidence, worker_main, main}` | Extend this exact bounded proof tool with reference lock, full assembly, fixed render/masks, one-iteration runner, events/checkpoint/outbox, and contact package. `main` still exits after one iteration. |
| `tools/validate_canon_decomposition_upbge_proof.py::{compare_glb, validate}` | Independently reopen all artifacts, replay scoring, compile/import/load/render evidence, and reject drift. |
| `tools/refine_recliner_art_bible.py` and `tools/validate_recliner_art_bible_refinement.py` | Retain the detailed recliner v2 generator/validator as a mandatory subcomponent gate. |
| `tests/test_refine_recliner_art_bible.py`, `src/unified_pipeline/tests/test_canon_compare.py`, and existing focused proof/strict-real tests | Add focused unit/property/integration coverage without UI or qualification changes. |

### Reference Discovery and Contract Lock

`INITIALIZE_REFERENCES` accepts no glob-selected latest file. It verifies the exact Canon path/hash above and the exact empty-twin path/hash above, checks both are regular files, rejects symlinks/aliases and duplicate candidate matches, records byte counts plus canonical pixel hashes, and includes the twin in the immutable binding set. Missing, ambiguous, substituted, or changed bytes stop the iteration before calibration.

The contract also binds: Art Bible hash, approved Plan revision/hash, CameraContract hash and every field, WorldContract input hash, selected-object/inventory/decomposition hashes, all asset hashes, source and working-tree fingerprint, Python/Blender/Browser versions, scorer source/config hash, seed, render settings, color management, and calibration-set hash. Any drift starts a separately versioned contract; scores from different contract hashes are incomparable.

### Versioned Fixed Render Protocol

Protocol `golden-room-proof-render/v1` is immutable for a run:

- Render the complete compiled 3D world, never a 2D composite or pasted reference, at full-frame `1024×768`, RGBA8 internal then explicit opaque sRGB output.
- Copy CameraContract position, target, up, projection, vertical FOV, near/far, and `4:3` aspect exactly. Reject camera reconstruction, auto crop, `ImageOps.fit`, zoom, reframing, registration, homography, per-candidate alignment, or content-aware transforms.
- Lock renderer/engine build, deterministic seed, device mode, sample count, anti-aliasing, shadows, visibility, light transforms/intensities/colors, exposure, view transform, tone mapping, alpha composite background, and texture filtering in `render-contract.json`.
- Disable auto exposure/white balance, EXIF orientation, ICC-dependent conversion, denoise/beautification, and adaptive sampling unless the exact deterministic implementation is contract-bound.
- Produce full-frame RGB, depth, normals, stable UUID/component ID, material ID, architecture/opening, and category masks from the same scene/camera. A metric resize may use only the contract's named Pillow `LANCZOS` RGB or `NEAREST` label-mask transform from the full frame, and records source/output hashes.
- Comparison/contact sheets may resize labeled copies for humans but never feed metrics.

### Calibration and Deterministic Metrics

Capability probe locks versions and executable identity. The verified CPU baseline is Pillow 12.0.0, NumPy 2.2.6, SciPy 1.18.0, and OpenCV 4.12.0. Because `cv2.quality`, scikit-image, torch, torchvision, LPIPS, and PIQ are absent in the active interpreter, the implementation may use fixed NumPy/OpenCV/SciPy structural, geometry, color, and feature metrics, but it SHALL enter `BLOCKED_UNCALIBRATED` unless an already-installed learned-perceptual implementation and exact local weight hash are explicitly discovered and replayable. No download, dependency addition, substitute qwen confidence, or naive `PSNR/100` fallback is allowed.

Calibration uses immutable renderer outputs and deterministic synthetic perturbations, not physical checkerboards/light meters and not ten hand-picked good images. Before any candidate score, create and primary-label a hash-bound set with at least: 32 exact-positive protocol replays/encodings, 64 accepted variations within locked tolerances, 64 known rejected Golden Room defects, and 160 single-category perturbations (`5 categories × 8 severity levels × 4 seeds`). Perturbations alter exactly one declared category while preserving camera/full frame and include missing/duplicate instances, opening shifts/topology defects, object translations/rotations/scales/occlusions, material hue/roughness/placeholder defects, blur/noise/lighting/structural defects. Calibration must show accepted/rejected separation and monotonic response to severity; contradiction, insufficient population, cross-category leakage, or uncertainty blocks scoring.

For every raw similarity metric `x`, immutable controls define `x100` (exact-positive median), `x95` (5th percentile accepted), and `x0` (95th percentile rejected), requiring `x100 > x95 > x0`. Normalize without rounding up:

```
Nsim(x) = 0                                      if x <= x0
          95 * (x-x0)/(x95-x0)                  if x0 < x < x95
          95 + 5 * min(1,(x-x95)/(x100-x95))    if x >= x95
```

For a lower-is-better distance `d`, use the same formula on `x=-d`. The calibration manifest stores raw distributions, anchors, formulas, floors, metric versions, and primary labels. Candidate data never changes anchors, masks, weights, or floors.

Metrics are full-frame or use only prelocked Canon/Plan/UUID masks:

- Binary/ID regions: exact count and identity; per-instance IoU; normalized area/centroid/orientation; occlusion-order graph; symmetric Hausdorff distance normalized by image diagonal. No candidate-specific mask registration.
- Architecture: shell/floor/ceiling/opening topology equality; per-opening region/edge IoU; edge distance; opening centroid/size while enforcing MetricPlan values.
- Materials: per-region CIEDE2000, locked palette/coverage, material assignment, roughness/specular/metallic metadata, texture hashes, and temporary/placeholder detectors.
- Perception: fixed three-family score—`Qstruct` from deterministic multi-scale SSIM implemented with a fixed Gaussian kernel/data range; `Qlearned` from the exact discovered local learned-perceptual implementation/weights; `QcolorFeature` from CIEDE2000 region similarity plus deterministic ORB feature/inlier statistics. If any family is absent/uncalibrated, `P` is invalid.

Category formulas use normalized `0..100` submetrics and preserve individual floors:

```
I = min over every required UUID of (count, identity, visible-presence)
Gmean = .35 shell-region + .35 opening-region + .15 architecture-edge + .15 metric-geometry
G = min(Gmean, minimum critical shell/opening submetric)
Lmean = .30 per-instance IoU + .20 centroid + .15 area + .15 orientation + .10 occlusion + .10 Hausdorff
L = min(Lmean, minimum required-instance layout score)
Mmean = .35 region color + .20 palette/coverage + .25 assignment/finish + .20 non-placeholder/durability
M = min(Mmean, minimum required-region/material score)
P = .40 Qstruct + .35 Qlearned + .25 QcolorFeature
S = .20 I + .20 G + .20 L + .15 M + .25 P
```

Exact inventory/count/UUID is a hard gate, so averaging cannot hide a missing, duplicate, or extra object. Every required UUID, opening, material region, and perceptual family has a calibration-locked critical floor. Success requires all hard gates; `I,G,L,P >= 95`, `M >= 90`, every critical floor, and `S >= 95.000000` using unrounded decimal output.

### Hard Gates

In order, before numerical success or vision:

1. Exact unique Canon/empty-twin/Art Bible/Plan/Camera/World/inventory/asset/config/source hashes.
2. Exact fixed render protocol and calibration-contract hash; learned-perceptual capability present and calibrated.
3. Complete selected inventory: exact per-UUID counts, no missing/duplicate/unapproved extra, no empty-twin remnants, placeholders, fused room/object geometry, or pasted pixels.
4. Exact Plan room shell/opening topology and WorldContract relationships/bindings.
5. Mandatory recliner v2 and unchanged common StandaloneAssetGate order.
6. Every GLB independently loads; valid GLB 2.0 lengths/chunks/buffer bounds; required meshes/components/bounds/collision; durable embedded materials/textures; no unresolved, external, absolute, traversal, or unsafe buffer/image URI.
7. Strict Browser project compile/build, import, scene/world load, selected-set and asset parity, camera binding, safe spawn/movement, and fixed-camera render smoke pass.
8. Replay A and B semantic equality for scene/component/material manifests, contract/candidate fingerprints, GLB/texture hashes, compiler output hashes, full-frame and mask canonical pixel hashes, metric records, and normalized gate verdict.

### Mandatory Recliner v2 Subcomponent

The recliner remains stable UUID `3b2cae03-3556-5c1e-a19b-ea3c1e15694c`, derived from immutable Task 11.8.4b fingerprint `d220ae78b3c8fd327a5aeb6aca523fd0ee5b132429c6947b1d413e89f5d204e9`; failed candidate `48f2e5c610f0661419a9a2c70ba5bdbe7511ef70cc0c9b830e3faaebd98ce0e6` remains read-only.

Upholstery uses deterministic subdivided soft masses: fixed bevel, subdivision level 2, normalized side/front bulge, smooth edge roll over the outer 18%, center sag, mirrored arm taper, deterministic normals, and fixed smooth shading. Frames/supports remain distinct hidden meshes. Reject non-finite/non-positive geometry, self-intersection, disconnected topology, envelope escape, or fused components.

| Component | Locked v2 local appearance profile |
|---|---|
| `base` / `base_skirt` | Base `(1.34,0.96,0.12)` at Z `0.12`; skirt `(1.70,1.13,0.28)` at Z `0.30`, bevel `0.14`; base frontage concealment `>=90%`. |
| `seat_frame` / `seat_cushion` | Hidden frame `(1.34,0.96,0.14)`; soft seat `(1.34,1.00,0.38)` at `(0,-0.24,0.76)`, `-5°`, bulge `(0.07,0.06)`, sag `0.025`. |
| left/right arms | Mirrored soft bodies `(0.46,1.08,0.60)` at X `±0.76`, bevel `0.20`, bulge `(0.10,0.07)`, sag `0.030`, inward taper `0.06`. |
| arm caps | `(0.54,0.93,0.30)` at X `±0.76`, Z `1.08`, bevel `0.15`, bulge `(0.12,0.08)`, sag `0.020`, internally overlapping bodies into pillow contours. |
| `back_frame` | `(1.48,0.20,1.23)` at `(0,0.39,1.42)`, `-17°`, separate with zero visible required-view pixels. |
| lower/upper back cushions | Lower `(1.45,0.48,0.58)`, bulge `(0.09,0.10)`, sag `0.040`; upper `(1.57,0.52,0.66)`, bulge `(0.11,0.10)`, sag `0.045`; both `-17°`. |
| footrest support/frame | Distinct hidden support `(0.88,0.42,0.11)` and frame `(1.12,0.62,0.12)`, both near `-14°`. |
| footrest cushion/shroud | Cushion `(1.08,0.72,0.27)` at `(0,-0.80,0.60)`, `-14°`, bulge `(0.08,0.07)`, sag `0.018`; separate shroud `(1.02,0.42,0.20)` bridges the hinge while preserving inspectability. |

Recliner hard measurements remain: Canon width/height ratio within `±10%` and `>=1.10×` failed ratio; height `<=1.10×` Canon and width `>=0.90×`; arm corner radius `>=15%` visible width and no straight run `>50%` arm height; visible base `<=12%` chair height; cushion rectangularity at least 10 percentage points below failed masses, bilateral bulge, sag `[2%,10%]`; upholstery coverage `>=85%`; three tan/umber/tobacco regions each `>=8%` with pairwise CIEDE2000 `>=12`; darker seams, fixed nonmetallic rough finish; footrest center offset `<=3%`, width `[75%,100%]` seat width, hinge gap `<=5%` seat depth, and zero background-connected gap/rail pixels. None can be waived by room score.

### Complete 3D Assembly and Evidence

The proof worker assembles only exact Plan/World-bound approved assets and the recliner v2 into the room shell; Canon, twin, masks, and cutouts are evidence, never image planes visible to the proof camera. It emits scene, component, material, asset, UUID, relationship, camera, light, and build manifests before rendering. `ThreeViewIdentityComparator` remains GREEN-required.

Each contract root is:

```
.kiro/specs/unified-world-pipeline/evidence/
  task-11.8.4c-golden-room-convergence/<contract-id>/
    contract/{references.json,render-contract.json,calibration-manifest.json,controls/}
    outbox/kirograph-events.jsonl
    checkpoint.json
    iterations/<iteration-id>/
      input/{snapshot.json,prior-checkpoint.json,next-change.json}
      events.jsonl
      build/{commands.jsonl,stdout/,stderr/,scene-manifest.json,component-manifests/,material-manifest.json}
      replay-a/{artifacts/,compiled/,renders/,masks/,metrics/}
      replay-b/{artifacts/,compiled/,renders/,masks/,metrics/}
      validation/{hard-gates.json,engine.json,glb.json,dual-replay.json,score.json}
      review/{contact-sheet.png,metric-overlay.png,mask-sheet.png,delta.png,qwen.json,primary.json,human.json}
      audit/{problem.json,attempt.json,solution.json}
      manifest.json
```

Every `events.jsonl` entry contains schema, sequence, iteration ID, event type, state, timestamp, payload hash, previous event hash, and event hash. Files are exclusive-created or content-addressed. `checkpoint.json` is written to a same-directory temporary file, flushed/fsynced, atomically replaced, then re-read and hash-verified; it records contract/iteration IDs, state, terminal error/verdict, command exit codes, evidence hashes, pending outbox IDs, retry eligibility, and exactly one next deterministic action.

The contact package contains labeled locked Canon, locked empty twin, previous candidate, current full-frame candidate, UUID/category/room/opening/material masks, failure and metric overlays, category/submetric table, and previous-to-current delta. All review images are watermarked `DIAGNOSTIC — NOT APPROVAL` until exact human approval. Metrics always read original full-frame/mask files, never sheets.

### Durable State Machine and One-Iteration Runner

Allowed ordered states are:

```
INITIALIZE_REFERENCES -> CALIBRATE_CONTRACT -> READY -> BUILDING
-> STRUCTURAL_VALIDATION -> DUAL_REPLAY -> RENDERING -> METRIC_VALIDATION
-> STRICT_LOCAL_VISION -> PRIMARY_ADJUDICATION
-> AWAITING_EXPLICIT_HUMAN_REVIEW -> VALIDATED_SUCCESS

any iteration failure -> FAILED_ITERATION -> CHECKPOINTED_CONTINUE -> process exit
explicit user stop -> INTERRUPTED
proven nonrecoverable authority/dependency/hardware/service failure -> HARD_ENVIRONMENT_BLOCKER
missing/inseparable calibration capability -> BLOCKED_UNCALIBRATED
```

`main` consumes one verified checkpoint, creates one cryptographically random fresh iteration ID with exclusive directory creation, executes at most one causal change under fixed time/resource budgets, checkpoints, and exits. It never sleeps/polls for another iteration and never self-loops after failure. The existing Windows-owned loop may invoke the next iteration later; this design changes no loop/task/hook configuration.

After every failure, the next-change policy is deterministic:

1. Fix the exact build/import/engine/world-load/render error first.
2. Otherwise fix the earliest failed hard gate in the locked order.
3. Otherwise choose the category or critical submetric with the lowest normalized margin `(score-floor)/(100-floor)`; ties resolve `I,G,L,M,P`, then stable UUID/name.
4. Apply one bounded causal code/config/asset change only. Never alter references, camera, calibration, metric implementation, weights, floors, or gates to improve a candidate score.

If three consecutive fresh iterations target the same bottleneck with less than `0.25` normalized-point improvement and no new causal evidence, checkpoint `CHECKPOINTED_CONTINUE` with `design_blocker=true` and exit for review. This is not success, interruption, or a hard-environment blocker and does not weaken the contract.

### KiroGraph Audit and Local Outbox

At iteration start, use KiroGraph context/memory as diagnostic context, never execution authority. Write exactly one local `problem.json` and one `attempt.json`; enqueue corresponding observations with topic keys:

- `recliner-canon-visual-refinement-fix/iteration/<iteration-id>/problem`
- `recliner-canon-visual-refinement-fix/iteration/<iteration-id>/attempt`
- `recliner-canon-visual-refinement-fix/iteration/<iteration-id>/solution` only after `VALIDATED_SUCCESS`.

Each outbox row has immutable payload, payload hash, topic key, observation kind, idempotency key `SHA256(topic_key || payload_hash)`, attempts, last result, and verification status. A bounded invocation may retry pending rows once and verify stored content; it never background-polls or promises later work. Append-only duplicate rows with the same idempotency key deduplicate semantically. KiroGraph failure cannot erase local audit history or block diagnostic iteration evidence, but a successful iteration cannot be complete until all three exact observations are verified. Failed, machine-only, best-so-far, or merely human-awaiting iterations have no Solution.

### Adjudication and Approval

Only after deterministic validation:

1. Run already-installed local `qwen2.5vl:7b` on exact hash-bound candidate/contact evidence. Require exact schema `pass: boolean`, `failed_checks: string[]`, `confidence: number`; `pass=true`, empty failures, confidence `>=0.8`. Model confidence contributes zero to `S`.
2. Independent primary adjudication checks inventory/count/identity, geometry/openings, layout/placement, materials/colors/finish, lighting, perceptual coherence, recliner v2, and absence of sparse/blocky/placeholder artifacts against the same hashes. Every category explicitly passes.
3. Present Canon, twin, candidate, overlays, masks, score/floors, delta, and all binding hashes to the human. Approval must explicitly name/confirm the candidate, world, proof pixel, contract/calibration, evidence, Canon, twin, Plan, Camera, WorldContract, asset, and recliner hashes.

Human rejection is `FAILED_ITERATION`, preserved append-only, and requires a fresh ID. Only exact approval transitions to `VALIDATED_SUCCESS` and creates Solution. Task 11.8.5 still remains blocked until the active Unified World Pipeline task owner separately records this prerequisite; this bugfix never edits task state.

### 6–8 Active-Coding-Hour MVP Path

1. `0.5h`: lock Canon/twin/Plan/Camera/World/inventory/toolchain hashes and capability probe.
2. `1.5h`: implement immutable calibration controls, CPU metrics, capability blocking, formulas, and focused boundary tests.
3. `1.5h`: extend complete assembly manifests/fixed render/masks and retain recliner v2 gate.
4. `1.5h`: add bounded runner, event chain, atomic checkpoint, outbox, and bottleneck selection.
5. `1.0h`: integrate strict compile/import/world-load/render, GLB/material/URI checks, and dual replay.
6. `1.0h`: generate contact/overlay/delta evidence and run one bounded diagnostic iteration.

Defer dashboards/UI, generalized scorer APIs, new model/dependency installation, physical calibration, broad pipeline refactors, extra render views, automated Scheduled Task changes, and non-blocking polish. If the learned-perceptual capability is unavailable, stop at evidenced `BLOCKED_UNCALIBRATED`; do not spend the milestone downloading/integrating a model or fabricate 95%.

## Testing Strategy

### Validation Approach

First characterize the immutable current proof and failed recliner without rewriting them. Then test calibration/scoring and state machinery on deterministic synthetic controls. Finally run one complete bounded iteration twice in isolated replay roots and independently revalidate all outputs. Validation is authoritative only for its exact candidate-tree fingerprint.

### Exploratory Bug Condition Checking

**Goal**: demonstrate the room-level and recliner counterexamples before fixing behavior.

**Test Cases:**
1. Verify exact Canon and twin bytes; show the existing proof does not bind the twin hash in `EXPECTED_HASHES`.
2. Run locked inventory comparison against the current proof; record missing/placeholder/identity failures individually.
3. Confirm current three-panel sheet uses fitted review panels and cannot be metric input.
4. Confirm the failed recliner violates at least one silhouette, arm/base, cushion, material, or footrest hard criterion despite qwen pass.
5. Probe metric capabilities and require `BLOCKED_UNCALIBRATED` while learned-perceptual support is absent.
6. Run existing strict compile/final validation against the current proof inputs and record the first exact unsupported/missing world binding rather than generalizing the failure.

If these do not reproduce the defect, revise the hypothesis and calibration design; do not lower gates.

### Fix Checking

```
FOR ALL iteration WHERE isBugCondition(iteration) DO
  result := runOneBoundedFreshIteration(iteration)
  ASSERT expectedBehavior(result)
      OR result.state IN {
           FAILED_ITERATION, CHECKPOINTED_CONTINUE,
           BLOCKED_UNCALIBRATED, INTERRUPTED, HARD_ENVIRONMENT_BLOCKER,
           AWAITING_EXPLICIT_HUMAN_REVIEW
         }
  ASSERT result never promotes partial success
  ASSERT next invocation requires a fresh iteration ID after failure
END FOR
```

### Preservation Checking

```
before := hash(locked references, prior evidence, task/UI/session/process files,
               git index, unrelated working-tree files)
runOneBoundedFreshIteration(candidate)
after := hash(the same preservation set)
ASSERT before == after
ASSERT allowedNewPaths are only the fresh iteration root and approved implementation/test paths
ASSERT Task11_8_4c unchecked AND Task11_8_5 == BLOCKED_NOT_STARTED
ASSERT no stage or commit occurred
```

### Unit Tests

- Reference discovery rejects absent, ambiguous, aliased, substituted, or hash-drifted Canon/twin inputs.
- Canonical pixel hashing ignores encoder metadata but detects decoded pixel, dimensions, mode, and protocol changes.
- Fixed render manifest rejects crop, camera, exposure, color-space, renderer, mask, or asset drift.
- Calibration enforces minimum populations, single-category perturbations, monotonic severity, accepted/rejected separation, immutable anchors, and `BLOCKED_UNCALIBRATED` on missing learned metric.
- Normalization formulas hit exact `0/95/100` anchors without rounding up; `S` uses exact `.20/.20/.20/.15/.25` weights.
- Exact inventory rejects every missing, duplicate, extra, wrong-UUID, invisible, or fused instance independently.
- IoU, normalized symmetric Hausdorff, area, centroid, orientation, occlusion, CIEDE2000, MS-SSIM, ORB, and category formulas pass/fail at boundaries; no per-candidate alignment is accepted.
- Recliner v2 geometry/material/measurement thresholds and common gate order remain exact.
- GLB parsing rejects bad lengths/chunks/bounds, missing components, placeholders, non-durable materials, and unsafe/external URIs.
- Event hashes detect deletion/reorder/edit; checkpoints survive interrupted temporary writes and are reverified.
- State transitions cannot skip calibration, replay, metrics, qwen, primary, or human approval; no `COMMITTED` state exists.
- Bottleneck selection prioritizes exact engine error, then hard gate, then lowest normalized margin and emits one change.
- Outbox idempotency creates exactly one semantic Problem/Attempt and no Solution before exact approval.

### Property-Based Tests

- Generate reference candidate sets and prove only one exact path/hash combination initializes.
- Generate arbitrary inventories and prove any per-UUID count/identity defect sets `I=0`/hard-fails regardless of other scores.
- Generate masks around all geometry/layout floors and prove averages cannot hide a failed UUID/opening/critical submetric.
- Generate accepted/rejected perturbation distributions and prove anchors are deterministic, candidate-independent, monotonic, finite, and order-independent.
- Generate all hard-gate/category/review truth combinations and prove only the all-pass plus exact human approval combination reaches `VALIDATED_SUCCESS`.
- Generate event/checkpoint crashes at each write boundary and prove append-only recovery plus fresh next iteration ID.
- Generate manifest mapping/order permutations and prove canonical fingerprints remain stable while any content mutation changes the hash.
- Generate KiroGraph availability/retry sequences and prove local history is lossless, retries idempotent, and Solution conditional on validated approval.
- Generate prior-worktree mutation scenarios and prove preservation validation rejects every unrelated change.

### Integration Tests

1. Independently load every candidate GLB with `trimesh`, the proof inspector, Blender import, and the qualified Browser compile/import path.
2. Run `handle_compile` and `handle_automated_final_validation`; then boundedly load the compiled world and capture one fixed-camera render smoke PNG. Record commands, exit codes, stdout/stderr, and hashes.
3. Verify selected-object equality, exact UUID counts/transforms, opening topology, real asset provenance, material/texture durability, URI safety, collision/navigation, camera hash, and compiler asset parity.
4. Execute replay A and B from byte-identical contract inputs in isolated roots and compare all semantic/artifact/pixel/metric/verdict hashes.
5. Recompute masks, raw metrics, normalized scores, category floors, and `S` from recorded immutable inputs with the independent validator.
6. Generate and hash contact, mask, overlay, score, and delta sheets; verify they are not metric inputs and remain diagnostic until approval.
7. Run strict local qwen only after machine gates, then independent primary adjudication, then verify human-awaiting state has no approval/Solution.
8. Simulate exact human approval and rejection: approval alone on the complete exact hash set reaches `VALIDATED_SUCCESS`; rejection preserves evidence and checkpoints one fresh next iteration.
9. Verify no UI/static JS/session/qualification/task/process/hook/index/commit changes and that Task 11.8.5 remains blocked.

### Design-Phase Validation

For this phase, validate Markdown structure and requirement traceability, inspect the repository diff/status, and confirm only this `design.md` changed during the call. Do not execute generators, start services, create evidence, edit tasks, stage, or commit.