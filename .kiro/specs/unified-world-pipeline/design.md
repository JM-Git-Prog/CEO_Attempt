# Restart Session Continuity Fix Bugfix Design

## Overview

This design makes restart recovery deterministic and evidence-honest for the active Unified World Pipeline V16 effort. The defect is not loss of artifacts; it is incorrect reconciliation among records with different scopes and authority. A stale `llm-driven-upbge-runtime` Task 10 memory can be newer in retrieval order than authoritative task truth, a green historical test baseline can be mistaken for validation of newer working-tree repairs, and a failed or restored live session can be mistaken for release evidence.

The fix introduces a restart reconciliation model that computes five independent outputs: governing task truth, validated baseline, candidate working-tree status, critical-path next action, and release-session eligibility. It never treats chronology alone as authority and never promotes evidence beyond the exact revision or working-tree fingerprint it validated. At the original recovery checkpoint, V16 was active; `llm-driven-upbge-runtime` Tasks 1–12 were complete; old Task 10 continuity was superseded; Tasks 13–14 were inactive downstream; the 922/36/53 baseline was green only for its bound fingerprint; newer repairs were unvalidated; and no clean live zero-state V16 release pass existed. Current execution status and the first unmet gate come from the active unified-pipeline `tasks.md`, not this historical checkpoint narrative.

This correction changes specification documents only. It binds the photo-bound Demo Profile to the immutable Golden Room source/workflow hashes, inserts a bounded WorldMirror 2.0 feasibility decision before the recliner bake-off, and preserves the later exact-prompt Release Profile benchmark. It does not install or download HY-World, change implementation or test code, start a live session or service, generate assets, activate downstream tasks, qualify a release, change any UI/version, authorize a commit, or alter retained V3–V16 interfaces.

## Glossary

- **Bug_Condition (C)**: A recovery snapshot contains stale, conflicting, differently scoped, or unvalidated records that could be promoted into an incorrect active checkpoint or release claim.
- **Property (P)**: The reconciled result reports the governing V16 truth, separates validated and unvalidated states, selects the correct next critical-path action, and rejects ineligible release sessions.
- **Preservation**: Existing V3–V15 behavior, valid durable-session resume, append-only diagnostic evidence, exact validation counts, and exact canonical-prompt qualification rules remain unchanged.
- **Recovery_Snapshot (X)**: The complete set of task documents, continuation records, persistent memories, validation manifests, working-tree facts, service facts, and qualification-session records visible at restart.
- **Evidence_Record**: A scoped fact with source, timestamp, revision/tree fingerprint, validation class, status, and supersession links.
- **Validated_Baseline**: The newest non-superseded implementation state with green evidence bound to its exact code/tree fingerprint. It does not imply release qualification.
- **Candidate_Tree**: The current working tree, including uncommitted repairs. A candidate newer than the baseline is unvalidated until matching checks pass.
- **Diagnostic_Session**: A failed, restored, previous-version, non-canonical, non-empty, mocked, or otherwise incomplete session retained for diagnosis but permanently ineligible as release evidence.
- **Release_Eligible_Session**: A brand-new empty V16 session started from the validated candidate, using the exact canonical prompt and live required services, that completes every applicable stage without defect.
- **Canonical_Prompt**: `Danny's kitchenette — a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain.` Exactly 142 UTF-8 bytes; SHA-256 `af6759e5d516561fad3fb49b129f02ad27743e273d1345173d59430f462f32ec`.
- **Golden_Room_Appearance_Reference**: Immutable Demo Profile appearance/composition evidence binding source image SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6` and original workflow SHA-256 `0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196`; it never has spatial authority.
- **Critical_Path**: focused Task 11.8.1 counter/cabinet regression → general exploratory-geometry freeze → bounded WorldMirror 2.0 documentation/preflight/feasibility gate on one RTX 4090 → fixed-recliner bake-off (raw crop, existing Qwen amodal completion, already-available video-depth only) within 60–90 active minutes → one common visual-gate decision → five Golden Room hero approvals → one photo-bound Golden Browser room → SceneVisualGate + playability + one functional GAME interaction + one REAL read-only binding → Demo Ready → replacement clean Task 11.7.1 → five fresh headless and five fresh human-like Release Profile rounds.

## Bug Details

### Bug Condition

The bug manifests when restart recovery can produce a checkpoint that is not justified by the scope, supersession state, or validation binding of its inputs. Common triggers are an old Task 10 continuation coexisting with newer completed task truth, a dirty candidate tree coexisting with an older green baseline, or prior session artifacts coexisting with no eligible clean V16 pass.

Let `X` be a recovery snapshot and `R(X)` the currently reported restart checkpoint. Define:

`C(X) = hasConflictingScopedRecords(X) OR hasSupersededActiveClaim(X) OR hasUnvalidatedCandidate(X) OR hasIneligibleQualificationClaim(X) OR hasPrematureDownstreamActivation(X)`

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type RecoverySnapshot
  OUTPUT: boolean

  taskConflict := input contains historical active Task 10
                  AND input contains newer proof that Tasks 1-12 are complete
  sourceConflict := sources disagree about active specification, checkpoint,
                    validation state, next action, or release readiness
  unvalidatedCandidate := currentTreeFingerprint(input) != validatedTreeFingerprint(input)
                          AND current tree has changes newer than validated evidence
  ineligibleReleaseClaim := any session is claimed as release evidence
                            AND NOT isReleaseEligibleSession(session, input)
  prematureActivation := V16 critical path is incomplete
                         AND downstream Tasks 13-14 or retained-interface changes are active

  RETURN taskConflict OR sourceConflict OR unvalidatedCandidate
         OR ineligibleReleaseClaim OR prematureActivation
END FUNCTION
```

### Examples

- Historical memory says Task 10 is active, while newer task truth says Tasks 1–12 are complete. Expected: Task 10 is labeled superseded; actual defective recovery can reopen it.
- The 922 unified/strict-real, 36 route, and 53 mesh suites are green for the validated baseline, while seven implementation/test files have newer uncommitted changes. Expected: baseline stays green and candidate stays unvalidated; actual defective recovery can call the candidate validated.
- Session `c4195e57` contains useful diagnostics but no clean release pass. Expected: preserve it append-only and reject it for qualification; actual defective recovery can resume or count it.
- No clean live zero-state V16 run exists. Expected: release qualification is incomplete and the next eligible attempt uses a new empty session; actual defective recovery can report release readiness.
- A source list arrives in a different order after restart. Expected: the same reconciled result; actual defective recovery can let retrieval order choose the checkpoint.

## Expected Behavior

The reconciler evaluates authority per concern rather than selecting one globally newest record:

| Concern | Governing evidence | Rule |
|---|---|---|
| Active spec and dependencies | Active spec requirements/tasks plus explicit supersession decisions | `unified-world-pipeline` V16 governs; llm-driven Tasks 13–14 stay inactive |
| Completed task truth | Newest non-superseded task state | Tasks 1–12 remain complete; historical Task 10 is not executable truth |
| Validated implementation | Validation manifest bound to exact revision/tree fingerprint | Preserve 922/36/53 and green checks only for the state they covered |
| Current candidate | Live working-tree fingerprint and diff state | Newer repairs are preserved and labeled unvalidated until matching checks pass |
| Release qualification | Eligibility predicate over one fresh live session | No restored, reused, failed, previous-version, mocked, or non-canonical session qualifies |
| Next action | First unmet gate in active `unified-world-pipeline/tasks.md` | Follow the active visual-first dependency order; never infer execution order from memory or this historical checkpoint |

**Expected-result pseudocode:**
```
FUNCTION expectedBehavior(result)
  INPUT: result of type ReconciliationResult
  OUTPUT: boolean

  RETURN result.activeSpec = "unified-world-pipeline"
         AND result.activeInterface = "V16"
         AND result.completedLlDrivenTasks = {1..12}
         AND result.supersededClaims contains "old Task 10 continuity"
         AND result.inactiveDownstreamTasks contains {13, 14}
         AND result.validatedBaseline.tests = {unifiedStrictReal: 922,
                                               routes: 36,
                                               mesh: 53}
         AND result.validatedBaseline.supportingChecks = GREEN
         AND result.candidateTree.status = UNVALIDATED
         AND result.releaseQualification.status = INCOMPLETE
         AND every result.releaseEvidence satisfies isReleaseEligibleSession
         AND result.nextAction = FIRST_UNMET_ACTIVE_TASK_GATE
END FUNCTION
```

### Preservation Requirements

**Unchanged Behaviors:**
- V3–V15 remain accessible at their existing selectors/routes and behave exactly as before.
- A valid durable V16 checkpoint with no superseding revision still resumes idempotently under one worker lease and one approval writer.
- Diagnostic sessions `8f24afd0`, `8b5057d3`, `473caae9`, `fb163c47`, `b7dd26d5`, `32c30b0f`, and `c4195e57` remain append-only and inspectable, but never qualify a release.
- The exact green baseline remains 922 unified/strict-real tests, 36 V14/V16 route tests, 53 mesh-focused tests, plus green diagnostics, compile, workflow JSON, and diff checks.
- Qualification uses the exact canonical prompt, including apostrophe, em dash, object counts, punctuation, and weather phrase.
- Any qualification defect is recorded; its session is discarded as release evidence; the cause is fixed; qualification restarts with another brand-new empty V16 session.

**Scope:**
All snapshots where `isBugCondition` is false remain behaviorally unchanged. This includes normal durable resume, historical diagnostic inspection, retained-version access, and reporting a clean baseline whose validation fingerprint exactly matches the current candidate.

## Hypothesized Root Cause

1. **Single-record continuation model**: Recovery can treat one narrative memory or continuation file as the checkpoint instead of reconciling scoped facts.
   - Retrieval recency is mistaken for authority.
   - Supersession is prose rather than a first-class relation.

2. **Conflated readiness dimensions**: Implementation validation, candidate validation, service readiness, and release qualification can collapse into one green/not-green status.
   - A green suite is allowed to imply a clean live run.
   - Historical evidence is not bound to the exact tree it tested.

3. **Missing release-session eligibility predicate**: Session identifiers and artifacts can be present without structured facts proving zero-state origin, exact V16/prompt identity, live execution, and uninterrupted clean completion.

4. **No monotonic critical-path state machine**: Restart recovery can jump from a dirty tree to qualification, or from incomplete V16 qualification to downstream Tasks 13–14.

5. **Insufficient provenance on recovery output**: Conclusions may omit the source, fingerprint, superseded records, rejected evidence, and reason for the chosen next action, making stale merges hard to detect.

## Correctness Properties

Property 1: Bug Condition - Restart Recovery Reconciles Conflicting Evidence

_For any_ recovery snapshot where the bug condition holds (`isBugCondition` returns true), reconciliation SHALL be independent of source retrieval order; identify Unified World Pipeline V16 as active; classify llm-driven Tasks 1–12 complete, old Task 10 continuity superseded, and Tasks 13–14 inactive; bind validation only to its exact revision/tree fingerprint; label newer repairs unvalidated; report release qualification incomplete unless an eligible clean session exists; and select the first unmet V16 critical-path gate.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**

Property 2: Preservation - Non-Bug Recovery and Release Evidence Remain Stable

_For any_ recovery snapshot where the bug condition does NOT hold (`isBugCondition` returns false), the reconciler SHALL produce the same resume and reporting behavior as the original valid path, preserving V3–V15 access and behavior, idempotent durable V16 resume, append-only diagnostic evidence, the exact 922/36/53 baseline and supporting checks, the exact canonical prompt, and full restart-on-defect qualification semantics.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

Assuming the root-cause analysis is correct, the implementation phase should make the smallest recovery-boundary change possible. No implementation change is made in this design phase.

**Component**: Restart continuity reconciliation boundary

**Specific Changes**:
1. **Normalized Recovery Snapshot**: Parse task, memory, continuation, validation, tree, service, and session facts into typed `Evidence_Record` values with scope, timestamp, source digest, revision/tree fingerprint, and supersession relation.
2. **Concern-Specific Authority Rules**: Resolve task truth, validation, candidate state, and qualification independently; never use one source as universal authority and never let input order affect the result.
3. **Explicit Supersession**: Materialize the old Task 10 continuation as superseded history while retaining it for audit. Do not delete or rewrite diagnostic records.
4. **Validation Binding**: Associate each green result with the exact code revision or working-tree fingerprint. Any later relevant change demotes only the candidate to `UNVALIDATED`; it does not erase the last green baseline.
5. **Release Eligibility Evaluator**: Require V16, a brand-new empty session ID, exact canonical prompt, validated candidate fingerprint, live required services, no restore/reuse, no mocked qualification stages, every applicable Brief/Plan/Blockout/Canon/World/Compare inspection, and no recorded defect.
6. **Monotonic Critical-Path State Machine**:
   - `RECOVERED_UNVALIDATED_CANDIDATE`
   - `TASK_11_8_REPAIR_VALIDATED`
   - `EXPLORATORY_GEOMETRY_FROZEN`
   - `FIXED_RECLINER_BAKEOFF_COMPLETE`
   - `FIVE_STANDALONE_ASSETS_APPROVED`
   - `GOLDEN_BROWSER_ROOM_ASSEMBLED`
   - `DEMO_READY`
   - `SERVICES_VERIFIED_FOR_RELEASE`
   - `REPLACEMENT_ZERO_STATE_RUNNING`
   - `REPLACEMENT_ZERO_STATE_FAILED` or `REPLACEMENT_ZERO_STATE_PASSED`
   - `FRESH_ROUNDS_RUNNING`
   - `RELEASE_ELIGIBLE`
   Any relevant tree change returns to exact-fingerprint candidate validation. Any failed session is append-only and permanently ineligible. Repair returns to the first invalidated milestone, but a replacement release-profile session cannot start before `DEMO_READY`.
7. **Auditable Recovery Report**: Emit accepted facts, rejected/stale facts, supersession reasons, evidence fingerprints, candidate status, release status, and exactly one next action. Never silently merge contradictory records.
8. **Compatibility Boundary**: Keep the change outside V3–V15 runtime behavior and the normal durable-session reconciliation path except for added evidence classification.

## Testing Strategy

### Validation Approach

Testing follows the bug-condition method: first surface counterexamples on the unfixed recovery path, then prove fix checking for `C(X)` and differential preservation checking for `¬C(X)`. Because this phase changes documents only, these tests are planned for the implementation phase and are not claimed as executed evidence.

### Exploratory Bug Condition Checking

**Goal**: Demonstrate that the unfixed path can revive stale work, overstate validation, or accept an ineligible session before implementing the fix. A refuted hypothesis requires revising the root-cause section before code changes.

**Test Plan**: Build recovery snapshots from immutable fixtures, vary source order and timestamps independently from authority, and run the existing recovery/reporting path.

**Test Cases**:
1. **Superseded Task 10**: Old active-Task-10 memory plus newer Tasks 1–12 completion truth (expected to expose stale activation on unfixed code).
2. **Dirty Candidate After Green Baseline**: Exact 922/36/53 baseline plus newer working-tree repairs (expected to expose validation overstatement).
3. **Diagnostic Session Reuse**: Each listed diagnostic session presented as the most recent session (expected to expose missing eligibility rejection if present).
4. **No Clean Live Pass**: Green suites and route checks but no live zero-state evidence (expected to expose release-status conflation).
5. **Source-Order Permutation**: The same evidence records in every generated order (may expose order-dependent recovery).
6. **Premature Downstream Work**: Incomplete V16 qualification plus pending Tasks 13–14 (expected to expose dependency bypass).

**Expected Counterexamples**:
- Recovery output changes when source order changes.
- Task 10 or Tasks 13–14 become active.
- Uncommitted repairs inherit an older validation result.
- A diagnostic session becomes resumable or release-eligible.
- Release status becomes green without one complete clean live zero-state session.

### Fix Checking

**Goal**: Verify that every buggy snapshot produces the reconciled result defined by Property 1.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := reconcileRestartState_fixed(input)
  ASSERT expectedBehavior(result)
  ASSERT reconcileRestartState_fixed(permutation(input.records)) = result
END FOR
```

### Preservation Checking

**Goal**: Verify that non-bug snapshots preserve original valid behavior and all explicit compatibility rules.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT reconcileRestartState_original(input) =
         reconcileRestartState_fixed(input)
END FOR
```

**Testing Approach**: Property-based differential testing is preferred because it can generate valid durable checkpoints, retained versions, source permutations, unrelated dirty files, and exact tree/evidence matches while ensuring the fix does not broaden its scope.

**Test Cases**:
1. **Normal Durable Resume**: Matching revision, valid external job, no superseding revision, one worker and approval writer.
2. **Retained Interface Preservation**: V3–V15 routes/selectors and representative behavior remain byte- or behavior-equivalent.
3. **Diagnostic Evidence Preservation**: Listed session artifacts remain unchanged and inspectable while eligibility remains false.
4. **Exact Baseline and Prompt**: Counts, supporting checks, and canonical prompt compare exactly.
5. **Defect Reset**: A defect at any qualification stage records failure and requires a different new empty session ID.

### Unit Tests

- Test source normalization, supersession, per-concern precedence, and deterministic tie rejection.
- Test tree-fingerprint binding and candidate demotion after any relevant change.
- Test every release-ineligibility reason independently, including restored, reused, prior-version, non-empty, wrong-prompt, mocked, failed, and incomplete sessions.
- Test exact canonical-prompt equality and exact baseline counts.
- Test critical-path transitions and fail-closed invalid transitions.

### Property-Based Tests

- Generate conflicting evidence graphs and permutations; reconciliation must be deterministic and satisfy Property 1.
- Generate candidate and validation fingerprints; evidence may validate only an exact matching candidate.
- Generate session histories and qualification-stage defects; only one wholly clean, new, empty, exact-prompt V16 session may become eligible.
- Generate non-bug snapshots and compare original versus fixed outputs to satisfy Property 2.
- Generate retained version identifiers V3 through V15 and verify route/behavior preservation.

### Integration Tests

- Simulate process and agent-session restart with task, memory, continuation, validation, tree, and session stores populated by the known checkpoint.
- Validate the current candidate, restart again, and verify progression to service verification without erasing the prior baseline.
- Execute a failed zero-state attempt, verify append-only diagnostic retention, repair the exact cause, complete the visual-first Demo Ready gates, and only then require a different brand-new replacement session ID.
- Execute the clean exact-prompt V16 path and inspect Brief, Plan, Blockout, Canon, World, and Compare as applicable before fresh round qualification.
- Run the relevant page, API route, and static JavaScript checks if the implementation exposes recovery status in the interface; any user-visible interface change requires a new query version while retaining all prior versions.

# Appendix: Existing Unified World Pipeline Design (Preserved)


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
- Qualification starts from a fresh zero-state session only after Demo Ready, records exact stage artifact hashes/source fingerprints, distinguishes mocked from live evidence, and restarts with a different new session after any failure.

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


## Hash-Bound Golden Room Demo Milestone Correction

This section is the active document-only design for work after the failed Task 11.7 evidence. It supersedes older kitchenette-as-demo, fixed-chair, and five-kitchenette-asset design text while preserving completed implementation history, V3–V16 behavior, failed-session ineligibility, and the later exact-prompt Release Profile benchmark.

### Product Architecture Versus HY-World Backend Scope

HY-World 2.0 and this product occupy the same broad category: persistent, navigable 3D asset and world creation. They are not interchangeable architectures. The Unified World Pipeline owns the conversational front door, Brief and ArtBible, approved MetricPlan as sole metric/spatial authority, deterministic relationship-solved WorldContract, per-object append-only warehouse, human approval gates, engine-neutral Browser/Godot/UPBGE compilation, and persistent per-room GAME/REAL overlays. HY-World is evaluated only as a reconstruction or generation backend candidate behind those contracts and gates.

Official HY-World 2.0 supports text, single-image, multi-view, and video inputs and can emit persistent 3DGS or meshes. Its full worldgen chain is HY-Pano 2.0 → WorldNav → WorldStereo 2.0 → WorldMirror 2.0 + 3DGS. That full chain is off the local critical path: official guidance recommends at least four GPUs, reports testing on eight H20 GPUs, and uses external vLLM. WorldMirror 2.0, an approximately 1.2B-parameter feed-forward multi-view/video reconstruction component, is the only bounded first target on the single RTX 4090. Full worldgen may later be an optional remote/high-end backend, but no cloud or external data transmission is allowed without explicit permission.

### Immutable Appearance Reference and Authority Boundary

The Demo Profile binds one immutable `Golden_Room_Appearance_Reference`:

| Evidence | Authoritative path | SHA-256 |
|---|---|---|
| Photoreal source image | `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png` | `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6` |
| Original Comfy workflow | `C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json` | `0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196` |
| Shared-input mirror | `C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png` | `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6` |

The two image copies are verified byte-identical. Any future missing file or hash mismatch fails closed and becomes a documented blocker rather than silently selecting a different image. This reference owns appearance, object/set-dressing identity, lighting balance, and composition evidence only. It cannot authorize dimensions, transforms, placement, architecture, openings, collision, navigation, or camera. The approved normalized MetricPlan remains the sole spatial authority, and CameraContract remains Plan-derived.

The final Scene Canon is not the imported photoreal source. It is produced honestly in normative product order from the approved MetricPlan, Blockout, and immutable CameraContract, with the Golden Room reference used only as a visual convergence target:

```text
approved MetricPlan + approved Blockout + immutable CameraContract
                              |
                              v
             geometry-conditioned final Scene Canon
                              ^
                              |
Golden Room image + original workflow hashes (appearance/composition evidence only)
```

### Evidence Precedence and Readiness

Restart reconciliation resolves concerns in this order: active unified-pipeline requirements/tasks, exact-fingerprint validation evidence, then profile-eligible session evidence. KiroGraph memory and the former `llm-driven-upbge-runtime` Task 10 continuation remain historical context only. A validated implementation is not automatically Demo Ready; photo-bound Demo Ready is not prompt-driven Release Ready; Release Ready is not Platform Complete.

```text
Photo-bound Demo Ready
  = immutable Golden Room image/workflow hashes + verified identical mirror
  + five hero StandaloneAssetGate approvals
  + complete fidelity/set-dressing inventory
  + one GREEN SceneVisualGate on the Golden Browser room
  + browser playability
  + one UUID-bound GAME state-changing interaction
  + one UUID-bound REAL read-only surface binding
  + one exact candidate fingerprint

Prompt-driven Release Ready
  = Photo-bound Demo Ready
  + replacement clean Task 11.7.1 Release Profile run
  + five fresh headless rounds
  + five fresh human-like rounds
  + final release checkpoint

Platform Complete
  = Release Ready
  + explicitly deferred production/platform capabilities
```

### Normative Product and Milestone Flow

```text
Prompt
  -> Dream Preview (mood evidence)
  -> MetricPlan solve/validate + Blockout approval (sole spatial authority)
  -> geometry-conditioned final Scene Canon
       + converge visually on immutable Golden Room appearance/composition evidence
       + never import source image as Canon or spatial authority
  -> object production

Task 11.8.1 focused counter/cabinet semantic regression + exact-fingerprint revalidation
  -> bind and verify immutable Golden Room source/workflow/mirror hashes
  -> freeze MiniMax / DA3 / MoGe / Anima and other general exploratory geometry
  -> WorldMirror 2.0 bounded local feasibility gate
       Phase A: official license/redistribution + disk/VRAM/RAM/CUDA/Python/native-build inventory
       Phase A: measured download/storage estimate + local-only data proof + reversible isolation plan
       STOP: no install/download until explicit user confirmation of measured cost and cleanup
       Phase B only after confirmation: one local Golden Room reconstruction, <=60 active minutes
       verdict: PASS into approved evidence evaluation | FAIL/DEFER directly to recliner bake-off
  -> fixed-recliner bake-off, 60–90 active minutes total
       lanes: raw crop | existing Qwen amodal | already-available video-depth only
  -> apply one common StandaloneAssetGate and choose the visually best pass
  -> produce/approve recliner, refrigerator, CRT television, wooden TV stand, bookshelf
  -> complete mandatory set dressing and recognizable shell/composition
  -> assemble one Golden Browser room
  -> SceneVisualGate + playability + GAME proof + REAL proof
  -> write photo-bound Demo Ready record
  -> replacement brand-new empty Task 11.7.1 with exact kitchenette prompt
  -> Tasks 11.9, 11.10, 11.11
```

The counter/cabinet defect remains a required focused semantic regression and exact-fingerprint revalidation prerequisite, but counter/cabinet is not a Golden Room hero asset.

The WorldMirror gate is a bounded backend decision, not authority transfer. Phase A is documentation and preflight only: inspect official license and redistribution terms; inventory exact disk, VRAM, RAM, CUDA, Python, compiler, and native-build requirements; estimate repository, model, environment, cache, and output storage; prove local-only data handling; and specify a reversible isolated environment and cleanup. Phase A cannot install or download anything. Only explicit user confirmation of those measured facts may unlock Phase B. Phase B receives local Golden Room evidence only and may emit candidate depth, normals, cameras, point clouds, 3DGS, TSDF, or mesh. Those outputs remain non-authoritative evidence until aligned, validated, contract-bound, gated, and human-approved. MetricPlan remains sole authority for dimensions, transforms, placement, architecture, openings, collision, navigation, and CameraContract; a TSDF or mesh cannot silently replace Plan architecture or collision.

The 60-minute WorldMirror pass requires a reversible isolated environment, a local model load or documented official reduced-memory/offload mode viable within 24GB, one OOM-free reconstruction under safe process ownership, locally loadable output, materially improved approved-camera resemblance, and at least one materially improved novel view versus current source-only/depth evidence. It records hashes, provenance, timing, peak VRAM/RAM, and disk. Multi-GPU-only requirements, no official viable 24GB mode, CUDA/native-build or license blockers, loss of local-only execution, exceeded setup/time/storage budgets, unloadable output, or no material visual gain produce FAIL/DEFER. Placeholders and cloud demos never pass. FAIL/DEFER freezes WorldMirror and returns directly to the recliner bake-off; it cannot expand into HY-Pano, WorldNav, WorldStereo, MoVerse, One2Scene, or unrelated exploration.

The recliner bake-off budget is a decision boundary, not a target to expand. Missing video-depth at bake-off start removes that lane. No model download, adapter integration, or capability preflight may extend the recliner milestone. The same gate evaluates every lane: independent load, recognizable silhouette/identity, absence of fused scene geometry or reconstruction artifacts, durable non-temporary materials, neutral multi-angle turntable, and explicit human approval.

### Hero Manifest and Fidelity Inventory

The five UUID-bound standalone hero assets are:

1. recliner
2. refrigerator
3. CRT television
4. wooden TV stand
5. bookshelf

All remaining source-room elements are mandatory SceneVisualGate fidelity/set-dressing inventory: ceiling fan, wall mirror, area rug, telephone side table, table lamp, foreground sofa, trophy shelf/trophies, and paintings. The shell/composition must remain recognizable as a long warm room with wood-plank floor, cream walls, rear and right wooden doors, a right-side street-facing window, warm lamp/daylight balance, and the approved Plan-derived camera composition.

Set dressing may use approved, procedural, or non-hero assets, but mandatory elements may not be missing, gross placeholders, fused remnants, or visually identity-breaking substitutes.

### Fail-Closed Visual Gates

`StandaloneAssetGate(asset)` passes only when the exact hero asset hash loads independently, uses non-placeholder geometry and durable approved materials, has neutral turntable evidence, and receives human approval bound to source lane, candidate fingerprint, and Golden Room reference hashes. Placeholder geometry and temporary Pass-1-only material states are hard failures.

`SceneVisualGate(room)` passes only when one Browser assembly preserves Plan-consistent shell/openings/transforms, contains all five approved hero assets and all mandatory set dressing, and is immediately recognizable as the photoreal source room from the approved camera. It must also hold up as the same coherent room from at least one navigable first-person viewpoint, without claiming pixel identity from navigable views. Fused remnants, missing inventory, gross placeholders, temporary Pass-1-only materials, identity-breaking substitutions, or an unacceptable human visual verdict fail closed. Structural/hash/parity success cannot compensate for visual failure, and visual success cannot compensate for structural failure.

The minimal GAME proof is one user action on a UUID-bound object that changes persistent room GAME state and produces visible score, success, or progress feedback. The REAL proof is at least one existing read-only UUID-bound surface display. Mode switching changes behavior only.

### Profiles and Warehouse Policy

| Profile | Reference/reuse policy | Evidence authority |
|---|---|---|
| diagnostic | May inspect prior evidence; all outputs remain non-authoritative | Never Demo or release evidence |
| demo | Binds Golden Room reference; may use only hash-verified, human-approved assets that pass StandaloneAssetGate | May support photo-bound Demo Ready only |
| fresh-benchmark | No pre-generation warehouse reuse | Benchmark evidence, not Demo or release evidence |
| release | Exact kitchenette prompt; every qualifying asset fresh to the new empty session | Eligible only after all release gates |

Profile and immutable appearance reference are recorded per run. Changing either creates a new run identity. This narrow photo-bound Demo reuse allowance does not weaken the Release Profile always-fresh rule. The exact release prompt remains 142 UTF-8 bytes with SHA-256 `af6759e5d516561fad3fb49b129f02ad27743e273d1345173d59430f462f32ec`.

### Failure, Ownership, and Document-Only Boundaries

Failed Task 11.7 sessions stay append-only and permanently ineligible. Task 11.8 repairs and revalidates, performs the bounded WorldMirror decision, and continues toward Demo Ready without creating a replacement session. Task 11.7.1 remains deferred until photo-bound Demo Ready. Windows continues to own the Ratchet watch; Comfy Desktop owns port 8188; no agent-managed terminal owns either long-running process. V3–V16 and unrelated working-tree changes remain untouched. This correction starts no session or service, installs or downloads no HY-World component, generates no asset, changes no production/test code or UI/version, marks no implementation task complete, and authorizes no commit.

**Validates: Requirements 38.1–38.12, 39.1–39.14, 40.1–40.9, 41.1–41.7, 42.1–42.10, 43.1–43.14**

## Diagnostic Design: Canon-to-Geometry Visual-Quality Spike (Non-Blocking, Historical/Frozen)

### Scope and Authority

This bounded experiment consumes only the immutable `canon.png` and `brief.json` from permanently ineligible session `11bdb38d-9064-4633-ab3b-09673f70c36d`. It never resumes that pipeline and cannot produce qualification or release evidence. All generated video, frames, depth, camera estimates, masks, point clouds, and GLBs are diagnostic evidence. The approved normalized MetricPlan remains the sole spatial authority; no generated motion, depth, bbox, point cloud, or candidate mesh may define dimensions, placement, transforms, architecture, openings, collision, navigation, or camera.

### Historical Capability Record and Active Freeze

The capability-first MiniMax/depth spike below is retained as diagnostic design history, not active critical-path work. MiniMax, DA3, MoGe, Anima, HY-Pano, WorldNav, WorldStereo, MoVerse, One2Scene, and other open-ended exploratory geometry/model work are frozen. Do not download, integrate, preflight, or execute them for Demo Ready. The bounded WorldMirror gate in Requirement 43 is a separate explicit exception with a preflight-only first phase and no download until renewed user confirmation. The only other exception is consuming video-depth evidence that already exists for the recliner at fixed-recliner bake-off start; it is one bounded lane and remains non-authoritative. Comfy Desktop and Windows process-ownership rules remain unchanged.

### Historical Diagnostic Chain

```text
historical only: immutable Scene Canon + Brief
  -> MiniMax video
  -> temporal gate
  -> depth/camera evidence
  -> UUID-bound segmentation and point clouds
  -> candidate completion and turntable validation

active bounded exception: already-available video-depth recliner evidence
  -> fixed-recliner bake-off common gate
  -> accept or reject within the shared 60–90 minute budget
```

The video keeps the Canon aspect ratio and exact fixed inventory through one continuous approximately five-second camera move. Cuts, object motion, count/identity drift, architecture/opening drift, material/lighting instability, implausible camera jumps, and morphing fail the temporal gate. Frame sampling persists hashes and per-check verdicts. Only passing frames enter depth/tracking.

The historical spike's round table, chair-1, chair-2, counter, and coffee maker remain bound by their Brief UUIDs for that frozen diagnostic record only; they do not define the Golden Room Demo manifest. Every historical UUID receives a deterministic outcome record even when rejected. Measurements include mask/frame coverage, one uniform scale anchor, and silhouette/depth/color reprojection diagnostics; independent-axis and min-max normalization are rejected. Hunyuan work is sequential and coverage-aware. A candidate counts only if it is non-placeholder, has non-temporary materials, loads independently, and receives neutral-view/turntable evidence.

### Resource and Evidence Ownership

Comfy Desktop remains the sole port-8188 process owner. Ollama is unloaded before MiniMax/Hunyuan work, and the diagnostic permits one substantial GPU owner at a time. The evidence bundle records source/model/workflow/input/output hashes, seeds, process/GPU preflight, frame hashes, masks, depth maps, camera confidence, point clouds, coverage and reprojection metrics, candidate validation, and per-stage/per-UUID accepted or rejected status. Bundle serialization and comparison ordering are deterministic.

### Verdict and MVP Decision

`SUCCESS` requires the complete evidence bundle, clear outcomes for all five UUIDs, and at least one independently loaded, neutral-view/turntable-validated high-quality object candidate. Otherwise the result is `PARTIAL` or `FAILURE` at the exact furthest completed stage with the blocker and integrate/revise/reject recommendation. The spike is non-blocking unless later production evidence justifies integration; it does not complete Task 11.7, start Tasks 11.9/11.10, alter UI, weaken gates, or authorize a commit. The final record explicitly assesses whether the path still supports the 6-8 active-coding-hour MVP constraint.

**Validates: Requirements 37.1-37.13, 31.1-31.7, 34.1-34.11, 35.11, 36.1-36.3**
