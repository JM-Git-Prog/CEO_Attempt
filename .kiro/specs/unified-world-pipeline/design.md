# Restart Session Continuity Fix Bugfix Design

## Overview

This design makes restart recovery deterministic and evidence-honest for the active Unified World Pipeline V16 effort. The defect is not loss of artifacts; it is incorrect reconciliation among records with different scopes and authority. A stale `llm-driven-upbge-runtime` Task 10 memory can be newer in retrieval order than authoritative task truth, a green historical test baseline can be mistaken for validation of newer working-tree repairs, and a failed or restored live session can be mistaken for release evidence.

The fix introduces a restart reconciliation model that computes five independent outputs: governing task truth, validated baseline, candidate working-tree status, critical-path next action, and release-session eligibility. It never treats chronology alone as authority and never promotes evidence beyond the exact revision or working-tree fingerprint it validated. At the original recovery checkpoint, V16 was active; `llm-driven-upbge-runtime` Tasks 1–12 were complete; old Task 10 continuity was superseded; Tasks 13–14 were inactive downstream; the 922/36/53 baseline was green only for its bound fingerprint; newer repairs were unvalidated; and no clean live zero-state V16 release pass existed. Current execution status and the first unmet gate come from the active unified-pipeline `tasks.md`, not this historical checkpoint narrative.

This correction changes specification documents only. Validated Requirements 44–48 govern the immediate milestone: inventory all local room/object evidence, bind the exact furnished and empty-room Canons, recover or produce identified objects under append-only provenance, assemble them under MetricPlan and unchanged CameraContract authority, and review one ordered aligned three-view proof plus navigable near replication. Standalone recliner approval is not a prerequisite for this room-level proof; final standalone asset gates remain required later. This design does not install or download models, add dependencies, change implementation or test code, start a live session or service, generate assets, activate Task 11.8.5, qualify a release, change any UI/version, authorize a commit, or alter retained V3–V16 interfaces.

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
- **Critical_Path**: complete `Local_Recovery_Inventory` and `Scene_Inventory` → bind the locked furnished Canon and exact hash-bound empty-room Canon or fail closed → recover suitable local assets or produce missing recognizable furniture through Picker → Mesher → Painter → assemble the complete identified room under the approved MetricPlan and unchanged CameraContract → render the ordered furnished → empty → reconstructed three-view proof → pass the fail-closed near-replication SceneVisualGate and navigable inspection → obtain exact-fingerprint human approval for the unchanged evidence set → only then make Task 11.8.5 eligible to start. This room-level milestone does not itself approve any standalone asset, Demo Ready, Release Ready, or Platform Complete.

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
   - `LOCAL_AND_SCENE_INVENTORY_COMPLETE`
   - `EXACT_FURNISHED_EMPTY_CANON_PAIR_BOUND`
   - `PROOF_ASSETS_READY_WITH_EXPLICIT_PROVISIONAL_STATES`
   - `METRICPLAN_SHELL_AND_IMMUTABLE_MATCHED_CAMERA_READY`
   - `COMPLETE_SCENE_INVENTORY_PLACED`
   - `ORDERED_THREE_VIEW_PROOF_COMPLETE`
   - `NEAR_REPLICATION_AND_NAVIGATION_GATES_GREEN`
   - `EXACT_FINGERPRINT_ROOM_PROOF_HUMAN_APPROVED`
   - `FIVE_STANDALONE_HERO_ASSETS_APPROVED`
   - `FINAL_GOLDEN_BROWSER_ROOM_ASSEMBLED_AND_VALIDATED`
   - `GAME_AND_REAL_DEMONSTRATED`
   - `DEMO_READY`
   - `SERVICES_VERIFIED_FOR_RELEASE`
   - `REPLACEMENT_ZERO_STATE_RUNNING`
   - `REPLACEMENT_ZERO_STATE_FAILED` or `REPLACEMENT_ZERO_STATE_PASSED`
   - `FRESH_ROUNDS_RUNNING`
   - `RELEASE_ELIGIBLE`
   Completed recliner bake-off work and prior standalone failures remain append-only diagnostic history and are not active states or transition prerequisites. Task 11.8.5 remains blocked until `EXACT_FINGERPRINT_ROOM_PROOF_HUMAN_APPROVED`; that approval makes standalone hero production eligible but does not complete it or confer any standalone, Demo Ready, or release approval. Any relevant tree or bound-evidence change returns to the first invalidated exact-fingerprint gate. Any failed session is append-only and permanently ineligible. A replacement release-profile session cannot start before `DEMO_READY`.
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


## Canon-Aligned Navigable Near-Replication Milestone

Validated Requirements 44–48 are execution truth for the immediate Golden Room milestone. They supersede any active design sequence that makes a perfect standalone recliner, a fixed-recliner bake-off, or five standalone hero approvals a prerequisite for assembling and reviewing the room-level reconstruction. Final `StandaloneAssetGate` requirements remain binding later; this correction changes only the order needed to learn from and approve the complete room proof.

### Milestone Objective and Ordered Flow

The immediate objective is one navigable, MetricPlan-authoritative near replication reviewed in this strict order:

```text
(1) Locked_Furnished_Canon
  -> (2) exact Hash_Bound_Empty_Room_Canon
  -> (3) fresh reconstructed 3D room from the unchanged matched CameraContract
  -> complete Scene_Inventory comparison
  -> navigable in-room inspection
  -> exact-fingerprint explicit human approval
  -> Task 11.8.5 becomes eligible to start, but is not completed
```

The room proof may use explicitly provisional `Proof_Asset` instances to expose composition, placement, occlusion, material, and navigability problems before perfect standalone asset approval. No provisional asset is silently promoted, relabeled as approved, or accepted as Demo Ready or release evidence.

### Locked Canon and Empty-Room Binding

The furnished reference remains the unmodified `Locked_Furnished_Canon`:

| Evidence | Exact path | SHA-256 |
|---|---|---|
| Locked furnished Canon | `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png` | `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6` |
| Original workflow evidence | `C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json` | `0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196` |

Before recovery, generation, assembly, or proof rendering, the reconstruction harness must discover and bind exactly one `Hash_Bound_Empty_Room_Canon`. Its record includes the exact accessible path, actual file type, byte size, exact bytes by SHA-256, derivation provenance back to the locked furnished Canon, same-room identity, framing relationship, source run/session, and ownership. This design does not invent a path or hash that has not been verified from local evidence.

If the empty-room candidate is missing, inaccessible, hash-ambiguous, regenerated, silently substituted, provenance-incomplete, or not unambiguously the same room and source framing, the milestone records `FAIL_CLOSED_MISSING_OR_AMBIGUOUS_CANON` and stops. It must not regenerate, substitute, or relabel either Canon to proceed.

The furnished and empty-room Canons control appearance and correspondence only. They never authorize room dimensions, transforms, placement, architecture, openings, collision, navigation, or camera.

### Local Recovery Inventory and Scene Inventory

The first executable stage is local evidence discovery, not new geometry generation. The `Reconstruction_Harness` inspects the furnished and empty-room Canons, Canon decomposition evidence, local project and warehouse manifests, prior evidence bundles, generated-object directories, review previews, and actual local asset files.

Every append-only `Local_Recovery_Inventory` record contains exact path, actual extension/type, byte size, SHA-256, source session/run, derivation and ownership provenance, stable UUID or explicit `NOT_APPLICABLE`, preview path/hash or explicit status, independent-load result, external-resource resolution, material/texture result, visual-suitability result, approval history, intended disposition, and a supersession link when later evidence changes state. Unknown and not-applicable fields are explicit, never omitted.

The record uses only Requirement 44's enumerated values: `DISCOVERED`, `VERIFIED`, `CONFLICTED`, `BLOCKED`, or `REJECTED` for inventory status; `VERIFIED`, `PARTIAL`, `UNKNOWN`, or `CONFLICTED` for provenance; `PRESENT_HASH_BOUND`, `MISSING`, `INVALID`, or `NOT_APPLICABLE` for previews; `PASS`, `FAIL`, `NOT_TESTED`, or `NOT_APPLICABLE` for independent load; `EMBEDDED`, `RESOLVABLE`, `UNRESOLVED`, or `NOT_APPLICABLE` for resources; `RESOLVED`, `PARTIAL`, `MISSING`, or `NOT_APPLICABLE` for materials/textures; and `SUITABLE`, `UNSUITABLE`, `REVIEW_REQUIRED`, or `NOT_EVALUATED` for visual suitability.

The `Scene_Inventory` identifies the shell, floor, walls, ceiling, doors, window, lighting sources, all five Golden Room hero objects, every required fidelity item, and every additional clearly visible object whose omission would materially reduce near replication. Each identified object keeps or receives a stable UUID, expected count, furnished-Canon region, role, support and occlusion relationships, and exactly one disposition: `RECOVER_LOCALLY`, `GENERATE`, `PROCEDURAL_SIMPLE_ARCHITECTURE`, `GROUPED_MINOR_SET_DRESSING`, or `BLOCKED`.

Conflicting claims about UUID, identity, bytes, hash, provenance, derivation, approval, or disposition are retained, marked `CONFLICTED`, and blocked from reuse until an append-only resolution identifies the authoritative record. The stage ends with an `Inventory_Completion_Summary` binding inspected roots, inventory hashes, status/disposition counts, exact Canon records, conflicts, missing fields, blocked objects, and either `COMPLETE` or `FAIL_CLOSED_INCOMPLETE`. Only `COMPLETE` may feed milestone-qualifying assembly.

### Controlled Demo Recovery and Object Production

A prior local asset is evaluated, never assumed reusable. Its recovery record binds stable UUID, exact path/hash, source and derivation provenance, source session/run, hash-bound preview, independent-load evidence, every buffer/image/texture/material/sidecar resource, material/texture evidence, visual suitability, approval history, and the inventory record that admitted it.

A recovered asset fails independent load if any required resource is missing, unresolved, session-relative, or silently substituted. Demo reuse requires the same applicable technical, material, visual, independent-load, and human-review criteria as newly produced work. Until every criterion passes, the asset may be inspected only as diagnostic or provisional evidence and cannot claim approved Demo reuse, standalone approval, Demo Ready, release evidence, or completion of this milestone.

When recognizable furniture lacks a suitable recoverable candidate, the preferred production path is:

```text
stable Scene_Inventory UUID + selected description bytes/hash + source Canon region
  -> Picker(inputs, candidate set, configuration, decision)
  -> Mesher(inputs, configuration, output path/hash)
  -> Painter(inputs, configuration, material/texture paths and hashes)
  -> hash-bound picker, mesh, painted, and room-proof previews
```

Every Picker → Mesher → Painter attempt records exact lineage and preserves prior failed, rejected, or superseded attempts append-only. Deterministic primitive or parametric geometry is permitted only for simple architecture or non-hero construction when visually suitable from the matched Canon view. Grossly blocky, generic, or identity-breaking primitive substitutes are rejected for recognizable hero furniture, upholstered furniture, and distinctive props.

Every `Proof_Asset` carries exactly one visible state: `PROVISIONAL_RECOVERED`, `PROVISIONAL_GENERATED`, `DIAGNOSTIC_ONLY`, `TEMPORARY_MATERIAL`, `FAILED`, `HUMAN_REJECTED`, or `APPROVED_DEMO_REUSE`. State changes require a new append-only gate record. Assembly does not relabel a provisional asset, and room-level human approval does not confer standalone or warehouse approval.

### MetricPlan-Authoritative Room Assembly

The approved normalized MetricPlan remains the sole authority for the coordinate frame, room dimensions, walls, floor, ceiling, doors, windows, collision, navigation, object transforms, scale, support, and circulation. The assembler records the approved MetricPlan revision/hash and, for every shell element and opening, stable identity, source Plan field, exact transform/dimensions, declared tolerance, collision/navigation binding, and measured conformance.

The `CameraContract_Factory` derives and freezes one matched `CameraContract` from that approved MetricPlan. Proof rendering uses its exact bytes and hash unchanged. Post-render camera nudging, crop compensation, independent-axis scaling, perspective warping, mirroring, and mutation are forbidden. If the current MetricPlan and derived camera cannot reproduce the locked composition within the near-replication gate, the failed revision and localized discrepancy evidence are appended; a new MetricPlan revision is validated and a new immutable camera is derived before rerendering. The Canon never gains camera or spatial authority.

Each object placement record binds stable UUID and exact Proof/approved asset hash; MetricPlan revision and source fields; position, rotation, scale, dimensions, and tolerances; support-surface UUID, contact relationship, containment, collision intent, and circulation; furnished-Canon region, projected correspondence, count/order/adjacency/occlusion expectations; and placement-evidence hash.

The `Placement_Gate` fails closed for out-of-tolerance transforms, unrelated penetration, unsupported floating objects, blocked openings/routes, wrong count/UUID/identity/hash, or materially incorrect projected regions. Failure evidence names the responsible UUID or shell element, expected and actual bindings, measured delta when reliable, localized world coordinates or Canon region, and hash-bound render evidence.

### Ordered Aligned Three-View Manifest

The proof renderer emits three separately addressable full-resolution images and one contact sheet in exactly this order:

1. unmodified `Locked_Furnished_Canon`;
2. exact `Hash_Bound_Empty_Room_Canon`;
3. fresh reconstructed 3D room containing the complete `Scene_Inventory`, rendered from the unchanged matched `CameraContract`.

Each image manifest records ordinal, role, exact path, actual file type, byte size, SHA-256, source/render provenance, and candidate fingerprint. View 3 additionally binds the reconstruction, complete inventory hash, every UUID-to-asset-hash binding, MetricPlan revision/hash, CameraContract bytes/hash, WorldContract hash where available, transforms, materials/textures, lighting, renderer/version, render configuration, environment identity, and reproducibility inputs/outputs.

The contact sheet references those immutable image records rather than unbound copies. All panels use one declared raster, aspect ratio, orientation, framing convention, padding policy, and color-management policy. Original source bytes remain separately addressable and are never silently cropped, mirrored, stretched, warped, or reframed. Any necessary padding or color conversion creates a separately hash-bound derived panel with its exact transformation and source hash disclosed.

Missing or ambiguous image bytes, order, provenance, label, inventory binding, common framing declaration, camera binding, or reproducibility field yields `FAIL_CLOSED_INCOMPLETE_THREE_VIEW_PROOF`. Incomplete evidence is retained append-only and cannot be presented for milestone approval.

### Near-Replication SceneVisualGate and Navigation

For this immediate milestone, the room-level `SceneVisualGate` is the fail-closed `Near_Replication_Visual_Gate`. It compares View 1 to View 3 for room proportions and shell identity; floor/wall/ceiling appearance; door/window identity; unchanged-camera composition; complete visible inventory and counts; projected placement and relative scale; silhouettes and object identity; materials/colors; lighting/shadows; support/adjacency/occlusion; and foreground/background composition. It separately compares View 2 to View 3 for same-room shell identity, opening placement, major architectural boundaries, empty-room perspective, and absence of fused furnished-room remnants.

A per-object verdict matrix is keyed by stable UUID and exact asset hash. Every applicable object receives explicit `PASS` or `FAIL` for presence, count, identity, projected Canon region, transform/relative scale, silhouette, material/color intent, support/contact, adjacency, and occlusion. `NOT_APPLICABLE` requires a reason and cannot suppress a required check. A failed category or object is never averaged away; evidence records the UUID or shell element, expected and actual state, relevant Canon region, measured delta when reliable or localized discrepancy otherwise, and hash-bound comparison artifact.

The gate passes only when every required category and per-object verdict passes and View 3 is immediately recognizable as a near replication of the locked furnished Canon. Missing inventory, wrong counts, gross hero placeholders, identity-breaking silhouettes, materially wrong placement, unresolved temporary materials, fused remnants, or major camera, shell, lighting, or composition mismatch fail closed.

Navigable inspection binds candidate fingerprint, WorldContract hash where available, MetricPlan revision, collision configuration, safe-spawn UUID/transform, movement/look controls, locomotion mode, and exact inspection routes/viewpoints. It verifies a safe non-intersecting spawn, first-person movement/look, MetricPlan-consistent collision, traversable routes, and ordinary in-room viewpoints sufficient to inspect the shell, every hero object, every required fidelity item, and every materially important additional inventory object.

Unsafe spawn, broken controls, collider mismatch, blocked routes, a camera-only facade, severe off-axis breakage, floating/intersecting objects, missing back/side geometry, or a room recognizable only from the proof camera fails navigation. Evidence records route/viewpoint, world location, responsible UUID/collider, expected and observed behavior, and hash-bound screenshots, captures, or logs.

### Exact-Fingerprint Human Approval and Task 11.8.5 Block

Human review occurs only after inventory, Canon binding, placement, ordered proof, visual matrix, and navigation checks all pass. The `Human_Approval_Record` binds the exact hashes of all three images, every derived panel, the contact sheet, candidate fingerprint, `Inventory_Completion_Summary`, `Local_Recovery_Inventory`, `Scene_Inventory`, approved MetricPlan revision/hash, unchanged CameraContract bytes/hash, WorldContract where available, every bound `Proof_Asset`, placement evidence, visual verdict matrix, navigation evidence, and all gate results.

Approval is explicit; file creation, preview opening, comparative praise, or prior rejected evidence never counts. Any changed byte, hash, contract, inventory entry, asset, transform, render, verdict, or navigation artifact makes approval inapplicable and requires a complete new review.

Task 11.8.5 remains `BLOCKED_NOT_STARTED` until one unchanged candidate and complete evidence set pass every non-human criterion and receive this exact-fingerprint human approval. That approval makes Task 11.8.5 eligible to start only. It does not complete Task 11.8.5, approve a standalone asset, establish Demo Ready, establish Release Ready, or imply Platform Complete.

### Profile Boundaries

| Profile | Recovery/reuse policy | Evidence authority |
|---|---|---|
| diagnostic | May inspect prior evidence; all outputs stay explicitly diagnostic | Never milestone, Demo, or release evidence |
| demo | May evaluate local prior assets only through controlled exact-hash recovery; provisional Proof_Assets remain provisional | May support this room-level milestone only after all exact-fingerprint gates |
| fresh-benchmark | No pre-generation warehouse reuse or prior-session substitution | Benchmark evidence only |
| release | Exact kitchenette prompt; every qualifying asset fresh to the new empty session | Eligible only after all later release gates |

Changing profile or immutable reference creates a new run identity; existing evidence is never relabeled. Controlled Demo recovery does not weaken always-fresh benchmark or release profiles.

### Authority, Preservation, and Document-Only Boundaries

MetricPlan remains sole spatial authority; the unchanged matched CameraContract remains camera authority; WorldContract remains final binding authority. Canons, masks, cutouts, previews, recovered assets, and generated `Proof_Asset` geometry are appearance/correspondence evidence or candidates only.

Failed, rejected, conflicting, and superseded evidence remains append-only. No failed Task 11.7 session is restored, resumed, repaired in place, or counted as qualification evidence. V3–V16 behavior, selectors/routes, shared version navigation, unrelated working-tree content, Windows ownership of the Ratchet watch, and Comfy Desktop ownership of port 8188 remain unchanged.

This document-only correction performs no cloud call, model download, dependency addition, installation, service/session startup, asset generation, production/test/UI edit, interface-version change, staging, or commit. Work prioritizes the shortest visual-first path compatible with the 6–8 active-coding-hour MVP target; non-blocking polish, broad tooling, and unrelated model exploration are deferred.

**Validates: Requirements 44.1–44.11, 45.1–45.12, 46.1–46.10, 47.1–47.11, 48.1–48.14**

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
