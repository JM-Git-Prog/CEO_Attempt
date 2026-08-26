# Implementation Plan

## Overview

This plan preserves the complete Golden Room convergence workflow, its validation boundaries, and its ordered execution path.

## Tasks

## Execution boundaries

- Target one end-to-end MVP in **6–8 active coding hours**, then continue only through fresh bounded iterations until `VALIDATED_SUCCESS`, explicit `INTERRUPTED`, an evidenced `HARD_ENVIRONMENT_BLOCKER`, or a checkpointed design blocker requiring review.
- Execute tasks in order. At every stated prerequisite, **stop immediately, preserve exact diagnostic evidence, write/checkpoint the named failure, and skip all dependent tasks**. Never weaken a gate, floor, metric, reference, camera, calibration, inventory, or authority contract to continue.
- Limit implementation to the design-named proof/refinement/validator paths, focused tests, and brand-new append-only roots under `.kiro/specs/unified-world-pipeline/evidence/task-11.8.4c-golden-room-convergence/<contract-id>/`. Preserve all historical evidence, Task 11.8.4c unchecked, and Task 11.8.5 `BLOCKED_NOT_STARTED`.
- Do not change UI/pages/routes/selectors/static JavaScript/interface versions, sessions or qualification state, Scheduled Tasks/hooks/watch ownership, Comfy Desktop/port `8188` ownership, unrelated worktree files, or the git index. Do not stage, commit, download a dependency/model, start a service/watcher, use a long-running agent process, allow an agent-managed terminal to own any process, or invoke a cloud model/service.
- Local Ollama is optional only for bounded adjacent drafts: `gpt-oss:20b` or `gemma4:26b` for metric/calibration reasoning drafts, `qwen3-coder-next` for repetitive test scaffolding, `llama3.1:latest` for bounded log/error summaries, and `qwen2.5vl:7b` for the required first-pass vision screen. Send no secrets/private data; treat every output as untrusted, review it against the design, and validate locally. Architecture, correctness authority, threshold selection, final adjudication, and approval stay with the primary implementation/review path. Do not use cloud offload unless the user separately and explicitly requests it.

- [x] 1. Characterize the unfixed complete-room bug and preserve its exact first failure
  - **Property 1: Bug Condition** - Complete Golden Room convergence fails closed
  - **CRITICAL**: Before any production edit, add the exploration property to `tests/test_refine_recliner_art_bible.py` and the existing focused proof/strict-real test modules that exercise `tools/canon_decomposition_upbge_proof.py::{verify_immutable_inputs, combine_contact_sheet, build_evidence, main}` and `src/unified_pipeline/strict_real_handlers.py::{handle_compile, handle_automated_final_validation}`.
  - At test start, query KiroGraph context and relevant memory for the exact current revision, then write a read-only preservation snapshot containing git status/index observations and hashes of Canon, empty twin, Art Bible, approved MetricPlan/CameraContract/WorldContract inputs, selected inventory/decomposition, approved assets, Task 11.8.4b baseline, failed Task 11.8.4c candidate, prior proof/evidence, active task states, and unrelated hook/worktree files.
  - Scope the PBT to the deterministic known counterexamples in `isBugCondition(input)`: current sparse proof; recliner fingerprint `48f2e5c610f0661419a9a2c70ba5bdbe7511ef70cc0c9b830e3faaebd98ce0e6`; missing empty-twin binding in `EXPECTED_HASHES`; review-only `ImageOps.fit` behavior in `combine_contact_sheet`; incomplete inventory/world bindings; and absent calibrated learned-perceptual scoring.
  - Reproduce the current proof through bounded existing validation only. Record the **first exact** build/import/engine/world-load/render error or, if those start successfully, the first hard-gate/category/submetric verdict in locked order, including command/tool, exit code, evidence hash, and the qwen-pass/primary-fail recliner contradiction. Do not summarize several failures into a later or generic verdict.
  - Assert `expectedBehavior(result)` so the test **fails on unfixed code** and emits a concrete counterexample showing that sparse/blocky/incomplete/unscored output cannot become `AWAITING_EXPLICIT_HUMAN_REVIEW` or `VALIDATED_SUCCESS`. Confirm `BLOCKED_UNCALIBRATED` is returned before any 95% claim when learned-perceptual capability is absent.
  - Keep all outputs temporary or in a brand-new append-only diagnostic root; do not alter or relabel the current proof, prior candidates, evidence, tasks, hooks, index, sessions, or services.
  - **EXPECTED OUTCOME**: the exploration property fails on the unfixed revision. Document the exact counterexample and first error/verdict; do not fix code or the test during this task. If the defect does not reproduce, stop and revise the design/hypothesis rather than proceeding.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 2.12, 2.15, 2.18, 2.21, 2.25, 2.28, 2.30, 3.1, 3.2, 3.3, 3.6, 3.8, 3.12, 3.18_

- [x] 2. Lock observation-first preservation properties on the unfixed revision
  - **Property 2: Preservation** - Authorities, evidence, scope, ownership, and downstream blocking
  - **IMPORTANT**: Before production edits, extend `tests/test_refine_recliner_art_bible.py` and `src/unified_pipeline/tests/test_canon_compare.py` with preservation properties built from the task 1 snapshot; run them on unfixed code and require them to pass.
  - Observe and encode byte/hash/chronology/verdict stability for the Task 11.8.4b baseline, failed Task 11.8.4c candidate, all earlier proof/evidence, Canon, Art Bible, exact empty twin, approved contracts, inventory/decomposition, and asset files.
  - Prove the negative boundaries remain unchanged: never call `src/unified_pipeline/plan_generator.py::revise`, `src/unified_pipeline/room_plate.py::RoomPlateGenerator.generate`, or `src/unified_pipeline/canon_generator.py::SceneCanonGenerator.generate`; never use `src/unified_pipeline/mesh_generators.py::UnifiedPlaceholderGenerator`; never let `src/unified_pipeline/object_isolator.py::ObjectIsolator.segment` replace Plan/World UUID identity.
  - Generate manifest-order, prior-file mutation/addition/deletion, index change, task-state change, and unrelated-hook/worktree mutation cases; require preservation validation to reject each without rollback or rewriting. Preserve the existing StandaloneAssetGate order and `src/unified_pipeline/object_manifest.py::build_plan_bound_selected_manifest`/`load_selected_manifest` semantics.
  - Assert no UI/version/session/qualification/process-owner/service/hook/index/commit changes, Task 11.8.4c remains unchecked, Task 11.8.5 remains `BLOCKED_NOT_STARTED`, and only a new allowed implementation/test path or fresh iteration evidence may differ later.
  - **EXPECTED OUTCOME**: preservation properties pass on unfixed code. If the baseline cannot be captured unambiguously or any pre-existing drift is unexplained, stop and record the blocker before production edits.
  - _Requirements: 2.7, 2.8, 2.9, 2.14, 2.30, 2.31, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.14, 3.15, 3.16, 3.17, 3.18_

- [ ] 3. Implement the complete Golden Room convergence MVP (6–8 active coding hours)
  - Complete 3.1–3.11 in order. Each subtask consumes only verified outputs from its predecessors. On any failed prerequisite, preserve the current attempt append-only, checkpoint the exact failure, skip all later subtasks, and do not advertise a score or request review.
  - _Bug_Condition: `isBugCondition(input)` from design is true whenever references/calibration/world/recliner/build/replay/visual/review validity is incomplete or failed._
  - _Expected_Behavior: `expectedBehavior(result)` from design requires one fresh complete fixed-camera 3D-world result with exact replay, all machine and score gates, qwen, primary, exact-hash human approval, durable audit, no staging/commit, and Task 11.8.5 still blocked._
  - _Preservation: Preserve every authority, prior byte/verdict, StandaloneAssetGate, UI/session/process/task/index boundary, and unrelated worktree change listed in design._
  - _Requirements: 2.1–2.31, 3.1–3.18_

  - [~] 3.1 Lock exact references, authorities, inventory, assets, and toolchain (target: 0.5h)
    - Extend `tools/canon_decomposition_upbge_proof.py::verify_immutable_inputs` and its immutable tables so `EXPECTED_HASHES` includes the exact Canon path/hash and exact empty-twin path `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-02-twin_00002_.png`, byte count `1,372,293`, SHA-256 `2f67a5f3d3b44a4fb1eacf1ada5e57d4fbf401662358b01ccf087c4a83a59103`.
    - Reject missing/non-regular/symlinked/aliased/ambiguous/substituted/drifted references; never glob-select “latest,” regenerate with `RoomPlateGenerator.generate`, or derive Plan/Camera changes from Canon/twin.
    - Using `build_plan_bound_selected_manifest` and `load_selected_manifest`, create `references.json` that binds Art Bible, approved Plan revision/hash, every CameraContract field/hash, WorldContract input hash, exact inventory/decomposition and stable UUID counts (including built-in counter), every selected approved asset hash/provenance, source/working-tree fingerprint, Python/Blender/Browser versions, seed, renderer settings, and scorer/config source hash.
    - Verify existing assets do not originate from `UnifiedPlaceholderGenerator`; treat skipped/uncertain `ObjectIsolator.segment` evidence or any authority/UUID/asset ambiguity as a blocker.
    - Independently reopen and rehash the lock in `tools/validate_canon_decomposition_upbge_proof.py::validate`.
    - **STOP/SKIP**: on any mismatch, emit exact `INITIALIZE_REFERENCES` failure, write no calibration/candidate/score, and skip 3.2–3.11.
    - _Requirements: 2.1, 2.7, 2.8, 2.9, 2.14, 2.16, 2.21, 2.28, 2.30, 3.1, 3.2, 3.3, 3.4, 3.5, 3.14, 3.16, 3.18_

  - [ ] 3.2 Probe capability and freeze the immutable calibration/render contract (target: 1.25h)
    - Add a bounded capability probe in `tools/canon_decomposition_upbge_proof.py` and independent replay in `tools/validate_canon_decomposition_upbge_proof.py::validate`; lock executable identity and installed Pillow `12.0.0`, NumPy `2.2.6`, SciPy `1.18.0`, and OpenCV `4.12.0` versions/hashes.
    - Discover a learned-perceptual implementation only if already installed, replayable, and backed by an exact local code/weight hash. Do not install/download anything and do not substitute qwen confidence, PSNR scaling, another model, or a two-family `P` score.
    - Implement immutable `golden-room-proof-render/v1` and `calibration-manifest.json`: exact CameraContract, `1024×768` full frame, RGBA8-to-opaque-sRGB handling, fixed renderer/device/samples/AA/lights/exposure/tone mapping/visibility/seed/filtering, canonical decoded-pixel hash, named Pillow `LANCZOS` RGB and `NEAREST` mask resize only, and rejection of crop/fit/registration/reframe/auto-exposure/auto-white-balance/ICC/EXIF/beautification/per-candidate tuning.
    - Generate deterministic pre-candidate controls: at least 32 exact positives, 64 accepted variations, 64 known rejected defects, and 160 synthetic single-category perturbations (`I/G/L/M/P × 8 severities × 4 seeds`). Use optional `gpt-oss:20b` or `gemma4:26b` only to draft test vectors; review all vectors and generate/validate them locally.
    - Calibrate immutable `x0/x95/x100` anchors and critical floors; prove accepted/rejected separation, monotonic severity, finite/order-independent normalization, and no cross-category leakage or candidate-derived tuning. Primary adjudication must approve calibration separation before scoring.
    - **STOP/SKIP**: if learned capability is absent/unhashed, populations are insufficient, controls contradict/leak, primary calibration review is uncertain, or protocol/contract drift exists, checkpoint `BLOCKED_UNCALIBRATED`, calculate/advertise no percentage, and skip 3.3–3.11.
    - _Requirements: 1.8, 2.14, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.23, 2.28, 2.30, 3.15, 3.16_

  - [ ] 3.3 Build the complete fixed-camera 3D assembly, manifests, renders, and masks (target: 1.5h)
    - Extend `tools/canon_decomposition_upbge_proof.py::worker_main` and `build_evidence` to assemble only exact Plan/World-bound approved room shell, openings, complete object/set-dressing inventory, durable materials/lights, and mandatory recliner v2. Emit scene/component/material/asset/UUID/relationship/camera/light/build manifests before render.
    - Integrate `tools/refine_recliner_art_bible.py` and `tools/validate_recliner_art_bible_refinement.py` as a mandatory subgate: preserve stable UUID `3b2cae03-3556-5c1e-a19b-ea3c1e15694c`, separate inspectable components/frames/upholstery, fixed v2 soft-mass geometry/material profile, all clauses 2.2–2.7 measurements, and unchanged common StandaloneAssetGate order.
    - Render the complete compiled 3D world at exact `1024×768` from CameraContract and the same scene/camera into full-frame RGB/depth/normals/stable UUID/component/material/architecture/opening/category masks. Canon, twin, cutouts, masks, and prior renders must never appear as visible image planes or pasted pixels.
    - Add canonical pixel hashes and provenance that prove `proofOrigin == "complete_3d_world_fixed_camera_render"`; reject recliner-only, empty-twin-only, 2D composited/pasted, placeholder/blockout, sparse, fused, or incomplete output.
    - Keep `src/unified_pipeline/canon_compare.py::ThreeViewIdentityComparator.compare` GREEN-required and `store_evidence` immutable; room scoring is a stricter sibling, never a replacement.
    - Add focused deterministic geometry/render/mask/manifest tests; optional `qwen3-coder-next` may draft repetitive fixtures only, which must be reviewed and run locally later.
    - **STOP/SKIP**: on missing/duplicate/extra UUID, Plan/World binding drift, placeholder/fused/2D origin, failed recliner criterion, missing mask, nonfinite geometry, or render/hash failure, checkpoint the earliest exact hard gate and skip 3.4–3.11.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.11, 2.15, 2.17, 2.20, 2.21, 2.27, 2.28, 2.30, 3.4, 3.5, 3.6, 3.8, 3.18_

  - [ ] 3.4 Implement deterministic `I/G/L/M/P` scoring, hard gates, and independent recomputation (target: 1.25h)
    - In `tools/canon_decomposition_upbge_proof.py::build_evidence`, implement contract-bound raw metrics and normalization exactly as designed: per-UUID count/identity/visibility; shell/opening topology and region/edge agreement; per-instance IoU/area/centroid/orientation/occlusion/Hausdorff; CIEDE2000/palette/coverage/assignment/roughness/specular/placeholder checks; fixed MS-SSIM, exact-hash learned-perceptual metric, and CIEDE2000+ORB color/feature family.
    - Implement unrounded category formulas and `S = .20I + .20G + .20L + .15M + .25P`; require hard gates first, every critical floor, `I/G/L/P >= 95`, `M >= 90`, and `S >= 95.000000`. Never drop/reweight an unavailable metric, round up, average over a failed UUID/opening/region/family, align per candidate, or recalibrate on candidate data.
    - Extend `tools/validate_canon_decomposition_upbge_proof.py::{compare_glb, validate}` to reopen immutable full-frame/mask inputs and independently recompute raw metrics, anchors, category scores, floors, composite, contract hash, and verdict without trusting producer summaries.
    - Add boundary and property tests for exact `0/95/100` anchors, monotonicity, order independence, synthetic perturbations, every missing/duplicate/extra UUID, every critical floor, category truth combinations, and scorer/contract drift.
    - **STOP/SKIP**: on unavailable/unseparated/nonfinite metric, producer/validator disagreement, contract drift, hard-gate failure, floor failure, or `S < 95.000000`, preserve diagnostic score evidence, enter `FAILED_ITERATION`, and skip 3.5–3.11 for that iteration.
    - _Requirements: 1.8, 2.18, 2.19, 2.20, 2.21, 2.22, 2.27, 2.28, 2.29, 2.30, 3.15, 3.16_

  - [ ] 3.5 Add append-only events, atomic checkpoints, KiroGraph outbox, and one-iteration execution (target: 1.0h)
    - Extend `tools/canon_decomposition_upbge_proof.py::main` so one invocation verifies one checkpoint, exclusive-creates one cryptographically fresh never-reused iteration ID, snapshots immutable inputs/prior checkpoint/one next change, enforces fixed time/resource budgets, executes at most one attempt, atomically checkpoints, and exits without sleep, polling, recursion, or a second attempt.
    - Implement the designed state transitions, including `BLOCKED_UNCALIBRATED`, and forbid skipped gates or any `COMMITTED` state. Every failure must pass through `FAILED_ITERATION -> CHECKPOINTED_CONTINUE`; a later invocation must use a fresh ID.
    - Hash-chain `events.jsonl`; exclusive-create/content-address artifacts; implement fsync + atomic replace + reread/hash verification for `checkpoint.json`; record exact command/error/verdict/exit codes/hashes/retry eligibility/pending outbox IDs and exactly one next deterministic action.
    - At each iteration, obtain KiroGraph context/relevant memory as diagnostic context, then create exactly one local `audit/problem.json` and `audit/attempt.json`; reserve `audit/solution.json` exclusively for exact approved `VALIDATED_SUCCESS`. Append idempotent outbox rows for stable topic keys `recliner-canon-visual-refinement-fix/iteration/<id>/{problem,attempt}`; retry each pending row at most once per bounded invocation and verify stored payload. Create/enqueue `solution` only after the same iteration reaches exact approved `VALIDATED_SUCCESS`.
    - Use `src/qa_evidence.py::AppendOnlyQALedger.append` as the append-only/deduplication pattern. KiroGraph outage must retain exact local audit/outbox state; diagnostic work may checkpoint, but success is incomplete until all required observations verify.
    - Add crash-boundary, event tamper, checkpoint recovery, fresh-ID, one-change, one-invocation, KiroGraph availability/retry/idempotency, and no-premature-Solution properties. Optional `llama3.1:latest` may summarize a bounded log for diagnosis, but the stored Problem must preserve the exact error/verdict and evidence hash.
    - **STOP/SKIP**: on event/checkpoint/outbox integrity failure or reused ID, preserve the root if safe, report the exact durability failure, and skip 3.6–3.11.
    - _Requirements: 1.9, 2.9, 2.23, 2.24, 2.25, 2.26, 2.29, 2.31, 3.6, 3.12, 3.15, 3.17_

  - [ ] 3.6 Integrate bounded game-engine, artifact, world-load, render, and dual-replay validation (target: 1.0h)
    - Reuse `src/photo_pipeline/stages/mesh_validator.py::validate_mesh`, `tools/canon_decomposition_upbge_proof.py::inspect_glb`, and `tools/validate_canon_decomposition_upbge_proof.py::{compare_glb, validate}` to independently verify GLB 2.0 magic/length/chunks/buffer bounds, mesh names/components/bounds/collision, real provenance, durable embedded materials/textures, and zero unresolved/external/absolute/traversal/unsafe image or buffer URIs.
    - Invoke `src/unified_pipeline/strict_real_handlers.py::{handle_compile, handle_automated_final_validation}` through existing bounded ownership; add bounded Browser project build/import, compiled scene/world load, selected-set/asset parity, Plan/Camera/World/opening/relationship/binding checks, safe spawn/movement, and exact fixed-camera render smoke evidence. Use `UnifiedResourceArbiter.claim`/`execute` only for already-installed bounded GPU work; timeout is failure evidence.
    - Execute isolated replay A and replay B from byte-identical contract inputs. Compare scene/component/material manifests, contract/candidate fingerprints, GLB/texture/compiler hashes, full-frame/mask canonical pixel hashes, metric records, and normalized gate verdict; normalize only declared timestamps/output-root paths.
    - Record every command, exit code, stdout/stderr hash, engine version, artifact hash, and first exact failure. Do not start/retain a server or watcher in an agent terminal.
    - **STOP/SKIP**: on the first build/import/engine/world-load/render/GLB/material/URI/authority/replay failure, preserve both replay roots, set `FAILED_ITERATION`, record that exact failure as Problem, checkpoint it as the sole next bottleneck, and skip 3.7–3.11.
    - _Requirements: 1.11, 2.9, 2.10, 2.11, 2.14, 2.17, 2.21, 2.23, 2.24, 2.28, 2.29, 2.30, 2.31, 3.5, 3.6, 3.7, 3.11, 3.17_

  - [ ] 3.7 Generate the hash-bound diagnostic comparison package (target: 0.5h)
    - Replace scoring use of `tools/canon_decomposition_upbge_proof.py::combine_contact_sheet` with original full-frame/mask inputs; retain resized sheets only as human diagnostics.
    - Generate and hash labeled locked Canon, locked empty twin, previous candidate (first iteration uses the immutable current sparse proof), current `1024×768` candidate, UUID/category/room/opening/material masks, metric/failure overlays, full submetric/category/floor/composite table, and previous-to-current delta.
    - Watermark every preview/sheet/overlay/delta `DIAGNOSTIC — NOT APPROVAL`; record that sheets are not metric inputs. A preview may open only after render completion and cannot alter state or eligibility.
    - Independently verify package labels, source hashes, canonical pixel hashes, metric-source separation, and delta baseline in `tools/validate_canon_decomposition_upbge_proof.py::validate`.
    - **STOP/SKIP**: on missing/mislabeled/mismatched panels, sheet-as-metric-input, absent delta/mask/overlay/table, or hash failure, retain diagnostics, set the exact evidence gate failure, and skip 3.8–3.11.
    - _Requirements: 1.10, 2.9, 2.17, 2.22, 2.27, 2.28, 2.29, 2.30, 3.6, 3.15_

  - [ ] 3.8 Run one complete bounded MVP invocation and ordered adjudication (target: 0.5h active supervision)
    - From a verified checkpoint, invoke `tools/canon_decomposition_upbge_proof.py::main` exactly once. It must create one fresh iteration, perform no more than one bounded causal change, run 3.1–3.7 gates in order, checkpoint, and exit. Do not run a long-lived process or automatically start a second iteration.
    - Only after all machine gates, exact replay, floors, and `S >= 95.000000` pass, call `src/qa_evidence.py::run_qwen_screening` with already-installed local `qwen2.5vl:7b` on the exact hash-bound candidate/contact evidence. Require exact schema, `pass=true`, empty `failed_checks`, and confidence `>=0.8`; confidence contributes zero to scoring.
    - After qwen, perform independent primary adjudication of inventory/count/identity, geometry/openings, layout/placement, materials/colors/finish, lighting, perceptual coherence, recliner v2, and absence of sparse/blocky/placeholder artifacts against the same hashes. Do not offload this authority.
    - Only after primary passes, enter `AWAITING_EXPLICIT_HUMAN_REVIEW` and present Canon/twin/candidate/masks/overlays/table/floors/composite/delta plus every design-required binding hash. Exact human rejection is a failed diagnostic iteration requiring a fresh next ID. Exact approval alone permits `VALIDATED_SUCCESS` and creation/verification of Solution.
    - **STOP/SKIP**: qwen unavailable/malformed/uncertain/failing, primary uncertainty/failure, or absent/mismatched human approval must preserve evidence, create no Solution, keep Task 11.8.5 blocked, and skip success verification.
    - _Requirements: 2.12, 2.13, 2.14, 2.21, 2.22, 2.23, 2.24, 2.25, 2.27, 2.28, 2.29, 2.30, 2.31, 3.8, 3.9, 3.11, 3.15, 3.17_

  - [ ] 3.9 Verify the original bug-condition exploration property now passes
    - **Property 1: Expected Behavior** - Complete Golden Room convergence or exact fail-closed continuation
    - Re-run the **same** Property 1 exploration test from task 1; do not replace it with a new happy-path test.
    - Require the bounded runner either to satisfy `expectedBehavior(result)` for an exact approved `VALIDATED_SUCCESS`, or to produce only one of the design-permitted exact fail-closed/checkpointed states without promotion, score fabrication, ID reuse, premature review, or premature Solution.
    - Verify the original sparse-proof, missing-twin-hash, fitted-sheet, incomplete-world, optimistic-qwen, and uncalibrated counterexamples are all rejected at their exact gates.
    - **STOP/SKIP**: if any old counterexample can promote or any exact approved success fails the property, preserve evidence and return to the earliest causal implementation task; do not weaken the property.
    - _Requirements: 2.1, 2.9, 2.12, 2.13, 2.15, 2.16, 2.18, 2.21, 2.22, 2.23, 2.24, 2.25, 2.28, 2.29, 2.30_

  - [ ] 3.10 Verify preservation properties still pass
    - **Property 2: Preservation** - Authorities, evidence, scope, ownership, and downstream blocking
    - Re-run the **same** observation-first preservation properties from task 2; do not author substitute tests after seeing implementation output.
    - Rehash every preservation-snapshot member and verify only explicitly allowed implementation/test files and fresh append-only contract/iteration evidence changed; verify the git index, unrelated hooks/worktree, UI/version/session/qualification/process ownership, historical evidence, and Task 11.8.4c/11.8.5 states are unchanged.
    - Verify `plan_generator.py::revise`, `RoomPlateGenerator.generate`, `SceneCanonGenerator.generate`, placeholder generation, model/dependency download, cloud calls, and long-running agent ownership were not used.
    - **STOP/SKIP**: on any preservation drift, do not roll it back automatically or claim success; record the exact drift, preserve evidence, and block 3.11 and later iteration claims until resolved with the owner.
    - _Requirements: 2.7, 2.8, 2.9, 2.14, 2.30, 2.31, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.14, 3.15, 3.16, 3.17, 3.18_

  - [ ] 3.11 Validate the MVP implementation at its exact candidate-tree fingerprint
    - Run the focused property/unit tests, independent validator, strict Browser compile/import/world-load/render checks, GLB/material/URI checks, dual replay, score recomputation, and preservation checks relevant to changed paths; bind commands/results to the exact source/working-tree/candidate-tree fingerprint.
    - Confirm no UI/static-JS/API/session/qualification/service/watch/hook/index/commit validation was needed because those paths are unchanged; do not start a server or qualification session.
    - Record the clean machine result or exact earliest remaining blocker in the checkpoint. A later relevant code/contract/asset change invalidates this candidate validation and requires a new fresh iteration.
    - **STOP/SKIP**: any failure leaves this iteration diagnostic and prevents a success claim, human approval request, or downstream progression.
    - _Requirements: 2.9, 2.10, 2.11, 2.13, 2.14, 2.21, 2.22, 2.28, 2.29, 2.30, 3.6, 3.7, 3.8, 3.12, 3.15, 3.16_

- [ ] 4. Continue durable fresh iterations using the deterministic bottleneck checkpoint
  - For every nonterminal checkpoint after task 3, let only a later explicit bounded invocation or the **existing Windows-owned loop under its unchanged Scheduled Task/keepalive ownership** consume `checkpoint.json`. The consumer command reads/verifies the checkpoint, invokes `tools/canon_decomposition_upbge_proof.py::main` once, waits for that bounded process to exit, and leaves the next checkpoint for a future invocation; it never edits loop/task/hook configuration and never keeps an agent terminal alive.
  - Before each iteration, verify all contract/input/checkpoint/event/outbox hashes and use KiroGraph context/memory diagnostically. Exclusive-create a fresh iteration ID after every build, structural, replay, metric, qwen, primary, or human failure; never resume a failed ID or reuse its artifact as passing evidence.
  - Select exactly one next bounded causal change in this order: (1) exact engine/build/import/world-load/render error; (2) earliest failed hard gate in locked order; (3) lowest normalized category/critical-submetric margin `(score-floor)/(100-floor)`, tie-breaking `I,G,L,M,P`, then stable UUID/name. Never alter references, authority, camera, calibration, scorer, weights, floors, masks, or gates to improve the score.
  - Preserve every iteration append-only; create exactly one Problem and Attempt locally/outbox/KiroGraph, and no Solution before complete exact approval. Use optional local `llama3.1:latest` only for bounded error triage/comparison summaries, `gpt-oss:20b` or `gemma4:26b` for bounded adjacent reasoning drafts, and `qwen3-coder-next` for reviewed boilerplate/tests; all resulting changes still require local validation and primary judgment.
  - If three consecutive fresh IDs target the same bottleneck with less than `0.25` normalized-point improvement and no new causal evidence, checkpoint `CHECKPOINTED_CONTINUE` with `design_blocker=true` and exit for review. This is neither success, `INTERRUPTED`, nor `HARD_ENVIRONMENT_BLOCKER`.
  - Continue until exact approved `VALIDATED_SUCCESS`, explicit user `INTERRUPTED`, evidenced nonrecoverable `HARD_ENVIRONMENT_BLOCKER`, or the checkpointed design blocker. Best-so-far/partial/machine-only output remains diagnostic; thresholds never weaken; Task 11.8.5 remains blocked.
  - _Requirements: 2.9, 2.10, 2.23, 2.24, 2.25, 2.26, 2.29, 2.30, 2.31, 3.6, 3.8, 3.11, 3.15, 3.16, 3.17_

- [ ] 5. Final clean checkpoint - record status without advancing Unified World Pipeline work
  - Require all focused tests and exact-fingerprint validations to pass for the final candidate tree; require replay A/B equality, all hard gates/floors/scores, strict qwen, independent primary adjudication, exact-hash human approval, verified Problem/Attempt/Solution observations, and unchanged preservation snapshot before recording `VALIDATED_SUCCESS`.
  - If success is not exact and complete, record the next bottleneck/terminal state and preserve all evidence; do not call it complete. If validation changed after approval, invalidate approval and start a fresh iteration.
  - Confirm Task 11.8.4c is still unchecked and Task 11.8.5 remains `BLOCKED_NOT_STARTED`; do **not** mark the Unified World Pipeline task complete, start Demo Ready/zero-state/release qualification, modify UI/version/session/service ownership, stage, or commit.
  - Ask the user for direction only when state is explicit `INTERRUPTED`, an evidenced `HARD_ENVIRONMENT_BLOCKER`, a preservation conflict, or `design_blocker=true`; otherwise leave the verified checkpoint for the existing bounded consumer.
  - _Requirements: 2.13, 2.14, 2.22, 2.23, 2.24, 2.25, 2.26, 2.29, 2.30, 2.31, 3.6, 3.8, 3.9, 3.10, 3.11, 3.12, 3.15, 3.16, 3.17, 3.18_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 1, "tasks": ["1"], "gate": "Bug-condition exploration is complete on the unfixed revision" },
    { "id": 2, "tasks": ["2"], "dependsOn": ["1"], "gate": "Observation-first preservation properties pass on the unfixed revision" },
    { "id": 3, "tasks": ["3", "3.1"], "dependsOn": ["1", "2"], "gate": "Both preimplementation prerequisites feed task 3; implementation starts with subtask 3.1" },
    { "id": 4, "tasks": ["3.2"], "dependsOn": ["3.1"], "gate": "Capability and the immutable calibration/render contract are frozen" },
    { "id": 5, "tasks": ["3.3"], "dependsOn": ["3.2"], "gate": "The complete fixed-camera 3D assembly, manifests, renders, and masks are built" },
    { "id": 6, "tasks": ["3.4"], "dependsOn": ["3.3"], "gate": "Deterministic I/G/L/M/P scoring, hard gates, and independent recomputation are implemented" },
    { "id": 7, "tasks": ["3.5"], "dependsOn": ["3.4"], "gate": "Append-only events, atomic checkpoints, KiroGraph outbox, and one-iteration execution are implemented" },
    { "id": 8, "tasks": ["3.6"], "dependsOn": ["3.5"], "gate": "Bounded game-engine, artifact, world-load, render, and dual-replay validation is integrated" },
    { "id": 9, "tasks": ["3.7"], "dependsOn": ["3.6"], "gate": "The hash-bound diagnostic comparison package is generated" },
    { "id": 10, "tasks": ["3.8"], "dependsOn": ["3.7"], "gate": "One complete bounded MVP invocation and ordered adjudication are run" },
    { "id": 11, "tasks": ["3.9"], "dependsOn": ["3.8"], "gate": "The original bug-condition exploration property passes" },
    { "id": 12, "tasks": ["3.10"], "dependsOn": ["3.9"], "gate": "The original preservation properties still pass" },
    { "id": 13, "tasks": ["3.11"], "dependsOn": ["3.10"], "gate": "The MVP implementation is validated at its exact candidate-tree fingerprint" },
    { "id": 14, "tasks": ["4"], "dependsOn": ["3"], "gate": "Task 3 feeds durable fresh iterations through the deterministic bottleneck checkpoint when exact validated success has not been reached" },
    { "id": 15, "tasks": ["5"], "dependsOnAny": ["4", "VALIDATED_SUCCESS"], "gate": "Task 4 or exact validated success feeds the final clean checkpoint" }
  ]
}
```

## Notes

- Tasks 1 and 2 are preimplementation prerequisites; both feed task 3.
- Task 3 is the parent implementation task; subtasks 3.1 through 3.11 execute sequentially.
- Task 3 feeds iterative task 4 when exact validated success has not already been reached; task 4 or exact validated success feeds checkpoint task 5.
- The dependency graph is descriptive. The task text, execution boundaries, stop/skip rules, requirement references, and checkpoints above remain authoritative.
