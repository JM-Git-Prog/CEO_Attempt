# Requirements Document

## Introduction

This specification defines the requirements foundation for converting The Living Room from an implementation-led prototype into a spec-driven project. The decomposition preserves verified released behavior, distinguishes current experimental work from release commitments, reconciles implementation with the original prototype vision, separates cohesive capabilities from shared foundations, and establishes an evidence-backed order for follow-on capability specifications. This specification changes documentation and planning artifacts only; product code, generated product artifacts, and released interfaces remain outside scope.

This refresh reflects the current workspace: interfaces V3 through V9 are released; V8 history and telemetry and V9 camera locking are released at commit `923b0f2`; the current feature branch and dirty working tree expose experimental V9 R3 and V10 behavior without V10 release qualification. The no-query UI and requests without an application-version header default to V9, while V10 remains explicitly accessible. The refresh preserves valid prior intent while correcting stale release, default-version, evidence-index, and planning-state claims.

## Glossary

- **Decomposition_Program**: The planning system governed by this specification that inventories evidence, classifies behavior, defines capability boundaries, and sequences follow-on specifications.
- **Workspace_Evidence_Set**: First-party implementation, tests, documentation, steering, hooks, manifests, version history, generated validation artifacts, release records, and Persistent_Knowledge examined during decomposition.
- **Vision_Baseline**: Original product intent expressed by `PROTOTYPE_PLAN.md` and the product summary in `README.md`.
- **Source_Evidence**: A source path, commit, generated artifact, test result, release record, or persistent observation that supports a current-state finding.
- **Evidence_Status**: One of `released`, `implemented_unreleased`, `experimental`, `documented_only`, `generated_evidence`, `workspace_automation`, or `third_party`.
- **Release_Status**: One of `released`, `implemented_unreleased`, `experimental`, `retired`, or `unknown`, assigned independently from implementation presence.
- **Behavior_Status**: One of `aligned`, `extended`, `narrowed`, `conflicting`, `deferred`, or `absent`, describing a behavior relationship to the Vision_Baseline.
- **Ground_Truth_Behavior**: Existing behavior supported by implementation plus executable or release evidence, with Release_Status recorded separately.
- **Release_Line**: The set of interfaces and Workflow_Profile entries supported by clean release qualification; the current Release_Line contains V3 through V9.
- **Capability**: A cohesive product or engineering responsibility with one observable outcome and a bounded contract.
- **Capability_Spec**: A follow-on feature specification that owns one Capability and states interfaces, invariants, dependencies, acceptance criteria, and exclusions.
- **Shared_Foundation**: A cross-cutting contract required by multiple Capability_Spec documents.
- **Boundary_Record**: A catalog entry containing responsibility, inputs, outputs, invariants, dependencies, exclusions, evidence, ownership, and Release_Status for one Capability or Shared_Foundation.
- **Capability_Catalog**: The ordered collection of Boundary_Record entries recommended for follow-on specifications.
- **Traceability_Matrix**: The mapping among Vision_Baseline statements, Source_Evidence, Ground_Truth_Behavior, Behavior_Status, Release_Status, and Capability_Spec ownership.
- **Dependency_Graph**: A directed acyclic graph whose nodes are Capability_Spec documents and whose edges identify prerequisite contracts.
- **Sequence_Wave**: A group of Capability_Spec documents that can be created after the preceding prerequisite wave.
- **Evidence_Gap_Register**: The list of requested evidence that is missing, stale, incomplete, uncollected, or environment-specific.
- **Open_Decision_Register**: The list of unresolved product, compatibility, release, ownership, or sequencing decisions.
- **Characterization_Test**: An executable test that records observable behavior before refactoring or intentional behavior change.
- **Release_Evidence**: A clean fresh-session validation record that satisfies the release policy and identifies the evaluated commit, interface, profile, prompt, and results.
- **Validation_Evidence**: A generated script result, log, probe, or inspection record that supports a finding but does not independently qualify a release.
- **Retained_Interface**: A previously released query-versioned web interface that remains accessible and behaviorally stable.
- **Workflow_Profile**: An immutable version-specific generation contract that pins Canon generation behavior and provenance metadata.
- **Camera_Contract**: The persisted `camera-lock/v1` projection contract shared by Plan, Blockout, Canon, and initial World presentation for V9 and later interfaces.
- **Canon_Alignment_Report**: The artifact-bound measurement and decision record that compares a Canon image with the approved Blockout under a Camera_Contract.
- **Persistent_Knowledge**: Durable project observations, decisions, errors, wiki pages, and automation rules intended to survive development sessions.
- **Product_Code**: Runtime source, UI assets, provider integrations, generated project logic, and release behavior used by the application.
- **Canon**: The approved reference image used to establish visual intent for the generated world.
- **Blockout**: The rendered three-dimensional preview of approved metric plan geometry used to condition Canon generation.
- **World**: The generated scene graph, mesh set, browser preview, and runnable Godot project.
- **Compare**: The appearance-only Canon-versus-World revision workflow.


## Requirements

### Requirement 1: Establish a Complete Evidence Baseline

**User Story:** As a project owner, I want the decomposition grounded in the current workspace, so that follow-on specifications describe the system that exists.

#### Acceptance Criteria

1. WHEN decomposition begins, THE Decomposition_Program SHALL inventory first-party implementation, tests, documentation, steering, hooks, manifests, version history, generated validation artifacts, release records, and Persistent_Knowledge.
2. IF part of the evidence inventory fails, THEN THE Decomposition_Program SHALL continue with successfully inventoried Source_Evidence and record the failed portion in the Evidence_Gap_Register.
3. WHEN a workspace item enters the Workspace_Evidence_Set, THE Decomposition_Program SHALL assign one Evidence_Status to the workspace item.
4. IF an evidence index fails, THEN THE Decomposition_Program SHALL continue assigning Evidence_Status from corroborated direct Source_Evidence.
5. THE Decomposition_Program SHALL distinguish first-party behavior from third-party vendor internals, caches, repository internals, browser profiles, and generated binary storage.
6. WHEN representative generated evidence is selected, THE Decomposition_Program SHALL record the selection basis and source path.
7. IF a requested evidence category contains no usable Source_Evidence, THEN THE Evidence_Gap_Register SHALL record the missing category and resulting confidence limit.
8. IF an evidence index reports pending files or a failed refresh, THEN THE Decomposition_Program SHALL corroborate affected findings with direct Source_Evidence and record the index limitation.

### Requirement 2: Separate Implementation State from Release Authority

**User Story:** As a release owner, I want implementation presence separated from release qualification, so that experimental behavior is not represented as a supported contract.

#### Acceptance Criteria

1. WHEN Ground_Truth_Behavior is recorded, THE Traceability_Matrix SHALL assign one Release_Status independently from one Behavior_Status.
2. WHEN release policy identifies a clean fresh-session pass for an interface, THE Decomposition_Program SHALL require the evaluated commit and Release_Evidence before assigning `released`.
3. IF the evaluated commit differs from the target release commit, THEN THE Decomposition_Program SHALL block release assignment until matching-commit Release_Evidence exists.
4. IF source code, logs, or generated sessions exist without a clean release record, THEN THE Decomposition_Program SHALL assign `implemented_unreleased` or `experimental` according to Source_Evidence.
5. WHEN the current release baseline is recorded, THE Traceability_Matrix SHALL identify V3 through V9 as the Release_Line at commit `923b0f2`.
6. WHEN V9 profile behavior is recorded, THE Traceability_Matrix SHALL identify `v9-camera-locked-photoreal-r2` as the released historical profile and `v9-camera-locked-photoreal-r3` as experimental.
7. WHEN V10 behavior is recorded, THE Traceability_Matrix SHALL classify `v10-bounded-review-r1`, V10 query-version routes and presentation, strict plan validation, and bounded Canon review as experimental without Release_Evidence.
8. IF a current default interface lacks clean release qualification, THEN THE Open_Decision_Register SHALL record the conflict with the UI versioning and release policy.
9. IF active profile selection for a Retained_Interface differs from historical profile selection, THEN THE Open_Decision_Register SHALL record the compatibility risk and affected profile identifiers.

### Requirement 3: Reconcile Vision and Implementation

**User Story:** As a product decision-maker, I want every meaningful behavior compared with the original vision, so that preservation and change decisions are explicit.

#### Acceptance Criteria

1. WHEN Ground_Truth_Behavior is identified, THE Decomposition_Program SHALL assign one Behavior_Status to the behavior.
2. WHEN Ground_Truth_Behavior agrees with the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `aligned`.
3. WHEN Ground_Truth_Behavior adds a Capability absent from the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `extended`.
4. WHEN Ground_Truth_Behavior implements a smaller scope than the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `narrowed`.
5. WHEN Ground_Truth_Behavior contradicts an authority relationship or outcome in the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `conflicting`.
6. IF Source_Evidence disagrees about a behavior, THEN THE Decomposition_Program SHALL record the disagreement, Release_Status, affected Capability_Spec, and required decision.
7. THE Traceability_Matrix SHALL retain deferred and absent Vision_Baseline capabilities without representing deferred or absent capabilities as implemented.

### Requirement 4: Define Cohesive Capability Boundaries

**User Story:** As a specification author, I want each meaningful responsibility isolated, so that each follow-on specification has a stable and reviewable scope.

#### Acceptance Criteria

1. WHEN the Decomposition_Program identifies a Capability, THE Capability_Catalog SHALL create one Boundary_Record for the Capability.
2. THE Boundary_Record SHALL state one primary observable outcome.
3. THE Boundary_Record SHALL identify inputs, outputs, invariants, dependencies, exclusions, Source_Evidence, Behavior_Status, and Release_Status.
4. IF two responsibilities have an identified shared contract and can change independently without changing the identified shared contract, THEN THE Decomposition_Program SHALL assign the responsibilities to separate Capability_Spec documents.
5. IF multiple responsibilities share one invariant or data contract, THEN THE Decomposition_Program SHALL assign the invariant or data contract to a Shared_Foundation.
6. THE Decomposition_Program SHALL derive Capability boundaries from behavior and contracts rather than source-directory names alone.
7. THE Capability_Catalog SHALL assign exactly one primary owner to every Ground_Truth_Behavior.

### Requirement 5: Isolate Shared Foundations

**User Story:** As an implementer, I want cross-cutting contracts specified before dependent capabilities, so that later specifications do not duplicate or contradict foundational rules.

#### Acceptance Criteria

1. THE Capability_Catalog SHALL define Shared_Foundation boundaries for domain contracts, units and coordinates, provider policies, session state, Camera_Contract rules, Workflow_Profile rules, provenance, compatibility, privacy, evidence traceability, release qualification, and Persistent_Knowledge.
2. WHEN a Capability_Spec consumes a Shared_Foundation, THE Boundary_Record SHALL identify the consumed contract.
3. IF two Shared_Foundation definitions conflict, THEN THE Decomposition_Program SHALL block dependent sequencing until the Open_Decision_Register contains a resolution.
4. WHEN the Open_Decision_Register receives a resolution for a Shared_Foundation conflict, THE Decomposition_Program SHALL resume eligible dependent sequencing without a separate restart action.
5. IF conflict detection does not execute, THEN THE Decomposition_Program SHALL permit sequencing from available verified dependencies and record the missing conflict check in the Evidence_Gap_Register.
6. THE Decomposition_Program SHALL assign state-transition ownership to one Shared_Foundation.
7. THE Decomposition_Program SHALL assign artifact-identity ownership to one Shared_Foundation.
8. THE Decomposition_Program SHALL assign camera projection, image-frame identity, and reset semantics to one Shared_Foundation.

### Requirement 6: Define Dependencies and Creation Sequence

**User Story:** As a project planner, I want a dependency-aware creation order, so that specifications can be authored without circular assumptions.

#### Acceptance Criteria

1. WHEN the Capability_Catalog is complete, THE Decomposition_Program SHALL produce a Dependency_Graph covering every Capability_Spec.
2. THE Dependency_Graph SHALL contain no directed cycles.
3. IF the Dependency_Graph contains a directed cycle, THEN THE Decomposition_Program SHALL reject the Capability_Catalog as incomplete until a reviewer resolves the cycle.
4. WHEN one Capability_Spec requires another Capability_Spec contract, THE Dependency_Graph SHALL place the prerequisite before the consumer.
5. THE Decomposition_Program SHALL group Capability_Spec documents into numbered Sequence_Wave entries.
6. THE Sequence_Wave entries SHALL place characterization, domain contracts, Camera_Contract rules, session state, and provenance before behavior-changing capability work.
7. WHERE Capability_Spec documents have no unresolved dependency edge between each other, THE Decomposition_Program SHALL identify the Capability_Spec documents as parallel-authoring candidates.
8. IF a dependency is uncertain, THEN THE Open_Decision_Register SHALL record the dependency instead of the Dependency_Graph representing an unverified prerequisite.


### Requirement 7: Preserve Released Behavior Deliberately

**User Story:** As a maintainer, I want released behavior protected during conversion, so that decomposition does not become an accidental rewrite.

#### Acceptance Criteria

1. WHEN released Ground_Truth_Behavior is `aligned` or has an approved extension disposition, THE Decomposition_Program SHALL treat the Ground_Truth_Behavior as the preservation baseline.
2. WHEN Ground_Truth_Behavior is `extended`, `narrowed`, or `conflicting`, THE Boundary_Record SHALL require one `preserve`, `revise`, `retire`, or `investigate` disposition.
3. WHERE a Retained_Interface exists, THE Capability_Catalog SHALL preserve query-version accessibility and released version-specific behavior as a compatibility contract.
4. WHERE a Workflow_Profile exists, THE Capability_Catalog SHALL preserve immutable persisted profile identity and historical session interpretation.
5. IF a follow-on Capability_Spec intentionally changes released Ground_Truth_Behavior, THEN THE Capability_Spec SHALL identify affected Retained_Interface entries, Workflow_Profile entries, artifacts, and Characterization_Test cases.
6. IF active V9 behavior differs from released V9 R2 behavior, THEN THE Decomposition_Program SHALL block progression of the differing behavior until either a new interface release exists or the Open_Decision_Register contains an explicit compatibility disposition.
7. THE Decomposition_Program SHALL keep Product_Code changes outside this specification.

### Requirement 8: Establish Verification and Characterization Obligations

**User Story:** As a quality owner, I want every capability tied to verification, so that spec-driven development can prove preservation and new correctness.

#### Acceptance Criteria

1. WHEN released Ground_Truth_Behavior lacks an automated test, THE Capability_Catalog SHALL require a Characterization_Test before behavior refactoring.
2. WHEN a requirement varies meaningfully across generated inputs and tests first-party deterministic logic, THE Boundary_Record SHALL recommend a property-based test.
3. WHEN a requirement depends on an external provider, browser, GPU, Godot runtime, or release environment, THE Boundary_Record SHALL recommend representative integration or smoke tests.
4. WHEN a parser or serializer belongs to a Capability, THE Boundary_Record SHALL require parse, print, error, and round-trip verification.
5. THE Traceability_Matrix SHALL map every acceptance criterion in each future Capability_Spec to at least one planned verification method.
6. IF an evidence script is not collected by the project test runner, THEN THE Decomposition_Program SHALL classify the script as Validation_Evidence rather than automated test coverage.
7. THE Capability_Catalog SHALL distinguish unit, property, integration, browser, runtime, compatibility, and release-qualification verification.
8. WHEN release qualification is explicitly specified, THE release-qualification Boundary_Record SHALL require a brand-new empty session, the canonical prompt, affected-stage inspection, retained-version checks, and rejection of every defective session before qualification proceeds.
9. IF an explicitly specified release qualification lacks any required qualification element, THEN THE release-qualification Boundary_Record SHALL block qualification.
10. IF generated logs show partial or failed execution without a clean pass record, THEN THE Decomposition_Program SHALL exclude the logs from Release_Evidence.

### Requirement 9: Specify Versioning, Provenance, and Historical Inspection

**User Story:** As a release owner, I want version and evidence rules represented as explicit capabilities, so that releases remain reproducible and prior interfaces remain stable.

#### Acceptance Criteria

1. THE Capability_Catalog SHALL define separate ownership for interface versioning, Workflow_Profile selection, immutable workflow snapshots, artifact verification, historical inspection, and release qualification.
2. WHEN a user-visible interface change is proposed, THE interface-versioning Boundary_Record SHALL require a new query version, retained prior versions, a declared default version, and release qualification before release classification.
3. WHEN Canon generation starts, THE provenance Boundary_Record SHALL require prepared and terminal generation records containing the selected Workflow_Profile, inputs, provider attempts, model identity, seed, artifact hashes, dimensions, Camera_Contract, and errors.
4. WHEN a session state is persisted, THE provenance Boundary_Record SHALL require an immutable full-state snapshot and a mutable session index.
5. WHEN a historical artifact is served, THE historical-inspection Boundary_Record SHALL require artifact-integrity verification and sanitized response metadata.
6. IF a recorded artifact hash differs from the current artifact hash, THEN THE historical-inspection Boundary_Record SHALL return an integrity error immediately and prevent successful completion of artifact delivery.
7. THE interface-versioning Boundary_Record SHALL define the relationship among package version `0.1.0`, interface versions, release commits, and Workflow_Profile identifiers.
8. IF a Workflow_Profile release record contains no release commit, THEN THE Evidence_Gap_Register SHALL record the missing profile-to-commit binding.

### Requirement 10: Represent Camera, Geometry, and Alignment Evolution

**User Story:** As a spatial-pipeline owner, I want released camera behavior and experimental geometry behavior separated, so that follow-on specifications preserve V9 while evaluating V10 independently.

#### Acceptance Criteria

1. WHEN V9 behavior is cataloged, THE camera-and-frame Boundary_Record SHALL own the persisted right-handed perspective Camera_Contract, vertical field of view, 4:3 frame, `1024×768` raster, near and far planes, stable contract identifier, projected landmarks, World initialization, orbit, and exact reset.
2. WHEN released V9 Canon behavior is cataloged, THE canon-image Boundary_Record SHALL bind Canon normalization and alignment evidence to the approved Blockout, plan revision, Camera_Contract identifier, Canon hash, and attempt number.
3. WHEN experimental articulated Blockout behavior is cataloged, THE plan-and-blockout Boundary_Record SHALL identify `v9-camera-locked-photoreal-r3` as experimental and preserve released V9 R2 as the historical interpretation.
4. WHEN V10 plan validation is cataloged, THE metric-plan Boundary_Record SHALL identify rotation-aware footprints, bounded placement search, structured blockers, and approval blocking as experimental behavior.
5. WHEN V10 Canon review is cataloged, THE canon-image Boundary_Record SHALL identify `aligned`, `misaligned`, and `inconclusive` outcomes, bounded retries, immutable binding data, and explicit acceptance of an inconclusive result as experimental behavior.
6. IF geometry validation code exists outside version control, THEN THE Evidence_Gap_Register SHALL record the version-control gap and block release attribution without constraining the stability classification supported by direct Source_Evidence.
7. IF V10 becomes the current default without a clean V10 release pass, THEN THE Open_Decision_Register SHALL require either V10 qualification or restoration of a released default.

### Requirement 11: Specify Privacy-Conscious Observability and Persistent Knowledge

**User Story:** As an operator and future contributor, I want safe diagnostics and durable decisions, so that workflow behavior can be understood without user-content leakage or session-only knowledge.

#### Acceptance Criteria

1. THE Capability_Catalog SHALL define separate boundaries for interface event logging, execution telemetry, and Persistent_Knowledge governance.
2. WHEN an interface event is recorded, THE event-logging Boundary_Record SHALL exclude prompt text and revision-feedback text.
3. WHEN an execution substep is recorded, THE execution-telemetry Boundary_Record SHALL store stage, substep, timestamps, duration, status, and error type.
4. IF timing samples do not meet the estimator threshold, THEN THE execution-telemetry Boundary_Record SHALL report insufficient evidence instead of an estimated duration.
5. WHEN a durable architecture decision, bug cause, compatibility rule, or release lesson is confirmed, THE Persistent_Knowledge Boundary_Record SHALL require one concise observation with a stable topic key.
6. WHEN a persistent observation affects a Capability_Spec, THE Traceability_Matrix SHALL link the observation to the affected Boundary_Record.
7. IF a persistent observation conflicts with a newer decision, THEN THE Persistent_Knowledge Boundary_Record SHALL require an explicit relation and adjudication result.
8. IF the configured project wiki contains zero pages, THEN THE Evidence_Gap_Register SHALL record the wiki as enabled but unpopulated.
9. WHEN a hook is cataloged, THE workspace-automation Boundary_Record SHALL distinguish configured intent from verified successful execution.
10. IF a hook contains an empty command or platform-specific command syntax, THEN THE Evidence_Gap_Register SHALL record the automation limitation regardless of execution evidence.

### Requirement 12: Produce Reviewable Deliverables and Maintain Scope

**User Story:** As a reviewer, I want a complete decomposition package without product mutations, so that the team can approve boundaries before design or implementation begins.

#### Acceptance Criteria

1. THE Decomposition_Program SHALL produce the Traceability_Matrix, Capability_Catalog, Dependency_Graph, Sequence_Wave plan, Evidence_Gap_Register, and Open_Decision_Register within this requirements document.
2. THE Capability_Catalog SHALL assign a kebab-case name to every recommended Capability_Spec.
3. THE Capability_Catalog SHALL state whether each recommended Capability_Spec preserves released behavior, captures implemented_unreleased or experimental behavior, or defines future behavior.
4. WHEN a current-state finding is included, THE Decomposition_Program SHALL cite at least one Source_Evidence path, commit, generated session, or persistent observation.
5. IF a current-state finding relies on generated evidence, THEN THE Decomposition_Program SHALL label environment-specific limits.
6. THE Decomposition_Program SHALL identify the next recommended Capability_Spec after this specification.
7. WHEN this requirements refresh modifies specification artifacts, THE Decomposition_Program SHALL preserve `.config.kiro`, `design.md`, and `tasks.md` without modification.
8. IF evidence cannot establish whether behavior is intentional, THEN THE Open_Decision_Register SHALL record the behavior.
9. WHEN a follow-on Capability_Spec discovers a boundary or dependency gap, THE Decomposition_Program SHALL permit a requirements-only correction to this specification.
10. THE Decomposition_Program SHALL leave release, commit, dependency, provider, generated-artifact, design-document, task-document, and Product_Code mutations outside this refresh.


## Current-State Traceability Matrix

| Area | Current behavior | Vision relationship | Release status and principal evidence |
|---|---|---|---|
| Domain contracts and pipeline | Pydantic models connect Brief, metric Floor Plan, Camera_Contract, Scene Graph, physics, materials, lights, openings, validation reports, provenance, and persisted session state. `WorldBuilder` orchestrates interpretation through Compare. | Aligned core pipeline; extended with explicit plan, camera, version, validation, and evidence state. | Released core plus experimental branch changes: `src/models.py`, `src/floor_plan/models.py`, `src/pipeline.py`. |
| Description interpretation | A local-first adapter uses Ollama, an OpenAI-compatible provider, and deterministic fallback. V8 and later structured stages use a 30-second total deadline and schema-correct fallback. | Aligned with local orchestration; extended with provider fallback; narrowed because semantic adequacy has no independent validator. | Released through V9: `src/orchestrator/*`, `src/pipeline.py`, clean V8 session `output/c1128426/`. |
| Metric plan and Blockout | Users review and revise a metric Floor Plan and rendered Blockout before Canon. Released normalization supplies authoritative geometry. Experimental V10 adds rotation-aware blockers and bounded placement; experimental R3 adds articulated sub-part Blockout detail. | Extended with approval and cheap spatial validation; conflicts with Canon-first spatial authority in the Vision_Baseline. | Released V3–V9 base behavior; experimental branch behavior: `src/floor_plan/*`, `src/pipeline.py`, `src/workflow_provenance.py`. `src/floor_plan/geometry.py` is untracked workspace evidence. |
| Camera and frame consistency | V9 persists `camera-lock/v1` across Blockout, Canon, and initial live and retained World, normalizes Blockout and Canon to `1024×768`, measures edge registration, permits orbit, and resets exactly to the contract. | Extended governance that resolves projection drift; still conflicts with Canon-as-spatial-source vision. | Released V9 R2 at `923b0f2`: `src/camera_contract.py`, `src/web/static/app.js`, clean session `output/246bc783/`, `.kiro/release-checklist.md`. |
| Canon generation | Canon supports mock, image API, ComfyUI, blockout conditioning, profile-pinned graphs, rejection, and regeneration. Released V9 uses historical R2. Current active V9 selection points to experimental articulated R3; V10 adds bounded three-state alignment review. | Aligned with approval and regeneration; extended with profiles and camera evidence; narrowed because image annotation is absent. | Released through V9 R2; R3 and V10 experimental: `src/canon_image/generator.py`, `src/workflow_provenance.py`. |
| Spatial scene construction | The LLM adds appearance, physics, and lighting while approved Floor Plan geometry overwrites room, object, opening, and fixture geometry. | Aligned with structured Scene Graph; conflicting with approved-Canon/VLM spatial authority. | Released through V9: `src/scene_graph/builder.py`. Experimental stricter upstream geometry validation remains outside the Release_Line. |
| Asset production | Each Scene Object and door receives procedural GLB geometry based on primitives or custom procedural construction. | Aligned with Godot-compatible output; narrowed because reconstruction, segmentation, UV, decimation, watertightness, scale-tolerance, and file-size gates remain absent. | Released: `src/asset_factory/mesh_generator.py`. Research evaluates future CAD-backed alternatives: `.kiro/research/gift-image-to-cad-workflow-assessment.md`. |
| Godot assembly and runtime | The assembler emits a complete project, room shell, meshes, lights, physics bodies, first-person controller, grabbing, and door behavior. | Aligned with the walkable physics-first outcome. | Released: `src/assembler/godot_project.py`; generated projects under `output/*/godot_project/`. |
| World revision and Compare | A vision model compares a World render with Canon and applies bounded appearance-only material and lighting patches while preserving geometry. | Extended beyond the original MVP and partially implements deferred iteration; narrowed to appearance-only revisions. | Released API behavior: `src/scene_graph/refiner.py`, `src/pipeline.py`, `src/web/app.py`. |
| Web workflow | FastAPI and browser JavaScript expose creation, approvals, plan revision, Canon rejection, World revision, status, history, telemetry, artifact delivery, browser preview, and download. Progress remains polling-based. | Aligned with the conversation front door; extended with history and preview; narrowed because direct Godot launch, annotations, SSE, and WebSocket progress are absent. | V3–V9 released at `923b0f2`; V10 routes and presentation are experimental: `src/web/app.py`, `src/web/static/app.js`, `src/web/templates.py`. |
| Interface and profile versioning | Query versions V3–V10 are accessible in the current branch. V3–V9 form the Release_Line. The no-query UI and absent application-version header default to V9; invalid text also resolves to V9, while unsupported positive numeric versions above V9 normalize to V10. Persisted sessions retain embedded profiles; released new-session V9 maps to R2, current active V9 maps to experimental R3, and current historical V9 maps to R2. | Extended engineering governance absent from the original vision. | Released V3–V9 at `923b0f2`; V10 and the V9 active-map change are experimental. Evidence: `.kiro/steering/ui-versioning.md`, `src/web/app.py`, `src/web/templates.py`, `src/workflow_provenance.py`, and `git show 923b0f2:src/workflow_provenance.py`. |
| Provenance and history | Sessions persist mutable indexes, immutable snapshots, Canon lifecycle manifests, camera/alignment data, artifact hashes, legacy warnings, and sanitized stage APIs. | Extended reproducibility and inspection capability. | Released V8 and V9: `src/workflow_provenance.py`, `src/web/history.py`, `src/web/app.py`, clean sessions `output/c1128426/` and `output/246bc783/`. |
| Observability and privacy | Versioned append-only logs omit prompt and feedback text. V8 and later expose substep timing, heartbeat, sample-backed ETA, and telemetry APIs. | Extended operational capability. | Released V8 and V9: `src/web/event_log.py`, `src/telemetry.py`, `output/logs/v8.jsonl`, `output/logs/v9.jsonl`. V10 logs are Validation_Evidence only. |
| Release qualification | Policy requires a fresh empty session, canonical prompt, affected-stage inspection, retained-version checks, browser checks, failed-session discard, and a complete clean pass before commit. | Extended release governance. | Released V8/V9 records: `.kiro/steering/ui-versioning.md`, `.kiro/release-checklist.md`, `output/v9_live_clickthrough.py`, sessions `c1128426` and `246bc783`. No V10 clean-pass record or V10 release harness exists. |
| Test coverage | `test_comfyui.py` executes at import time and is not a conventional collected assertion suite. V7–V9 release/browser scripts remain ad hoc Validation_Evidence. The `llm-driven-upbge-runtime` plan marks one characterization-fixture task complete, but the indexed workspace still exposes no conventional collected first-party suite. | Narrowed from a maintainable verification foundation. | `test_comfyui.py`, `output/v9_live_clickthrough.py`, `pyproject.toml`, `.kiro/specs/llm-driven-upbge-runtime/tasks.md`; no first-party test directory is present. |
| Persistent knowledge | KiroGraph memory contains 14 observations across four sessions, including V8/V9 release decisions, failure records, and current characterization findings. The wiki is enabled with zero pages and zero sources. Watchmen reports zero pending observations against a threshold of five. | Extended development-system capability with an unpopulated wiki. | `.kirograph/config.json`, KiroGraph memory status, wiki status, and watchmen status collected during this refresh. |
| Steering and hooks | Steering defines UI release and local-model policies. Stop hooks request graph sync, memory capture, watchmen synthesis, wiki ingestion, and wiki lint. The vendor setup hook is enabled with an empty command. | Extended workspace automation. | Configuration only unless execution evidence exists: `.kiro/steering/*`, `.kiro/hooks/*`. KiroGraph reports 24 files pending synchronization; the sync, watchmen, and wiki command hooks use POSIX shell syntax on a Windows workspace, so successful hook execution is not established. |
| Product and repository versions | The package remains `0.1.0`; released interfaces reach V9; the current branch exposes V10 while defaulting absent interface selection to V9 and selecting experimental R3 for new V9 sessions. HEAD is `580fb34` on `feat/articulated-blockout-r3`, ahead of `main`, with modified, deleted, and untracked workspace items including `src/floor_plan/geometry.py` and follow-on specification artifacts. | Extended multi-axis versioning with unresolved release and compatibility relationships. | `pyproject.toml`, git history/status collected during this refresh, `src/web/app.py`, `src/web/templates.py`, `src/workflow_provenance.py`. |
| Specification planning state | This decomposition has an existing design and an empty task document. `llm-driven-upbge-runtime` has requirements, design, tasks, and one checked characterization task; `gift-cad-world-assets` currently has requirements only. These artifacts span multiple recommended boundaries and do not establish released product behavior. | Extended planning work outside the original product vision. | Documented-only planning evidence: `.kiro/specs/spec-driven-project-decomposition/`, `.kiro/specs/llm-driven-upbge-runtime/`, and `.kiro/specs/gift-cad-world-assets/`. |

## Explicit Vision Reconciliation

### Aligned released behavior to preserve

- Plain-language interior description becomes a structured scene concept.
- Canon generation supports rejection, feedback, regeneration, and approval.
- A structured Scene Graph carries room, object, material, light, opening, and physics data.
- Procedural meshes and Godot assembly produce a walkable first-person project.
- Movable objects receive rigid physics while fixed architecture receives static physics.
- Local provider integrations coexist with deterministic offline fallbacks.
- The prototype remains single-room and excludes Warehouse, game mode, real mode, multiplayer, and multi-room navigation.

### Released extensions to preserve or decide explicitly

- Metric Floor Plan creation, normalization, revision, approval, SVG rendering, and Blockout rendering precede Canon.
- Approved plan geometry overrides model-authored Scene Graph geometry.
- Browser preview and project download supplement Godot output.
- V8 releases history, stage and revision replay, artifact verification, telemetry, heartbeat, and sample-backed ETA.
- V9 releases a persisted Camera_Contract, fixed image frame, Blockout-to-Canon registration, initial World camera locking, user orbit, exact reset, and retained-stage camera evidence.
- Query-versioned interfaces, immutable Workflow_Profile entries, immutable snapshots, and Canon lifecycle manifests preserve historical interpretation.
- Append-only privacy-conscious event logging captures lifecycle, process, click, and validation events.
- Appearance-only World refinement compares a captured render with Canon.

### Experimental or implemented-unreleased behavior

- New V9 sessions currently select articulated profile R3 while historical V9 sessions select released R2.
- V10 is accessible through `?v=10` and linked from version navigation without a clean V10 release pass; absent or invalid textual interface selection defaults to released V9.
- V10 adds rotation-aware plan blockers, bounded placement, blocked plan approval, three-state Canon alignment classification, bounded retries, and explicit review acceptance for inconclusive results.
- Current branch changes and untracked geometry code provide workspace evidence but do not extend the Release_Line.

### Narrowed or absent vision behavior to retain as gaps

- Asset generation remains procedural rather than image-to-3D reconstruction and lacks segmentation, decimation, UV, watertightness, scale-tolerance, and file-size gates.
- Scene Graph construction does not use an approved-Canon VLM to establish object positions or depth.
- Canon feedback remains text-based; an image annotation overlay is absent.
- Progress uses HTTP polling; SSE and WebSocket progress are absent.
- The web workflow provides download rather than direct Godot launch.
- Conventional collected unit, property, integration, and contract coverage is absent.
- The enabled project wiki remains empty.

### Conflicts requiring explicit disposition

- The Vision_Baseline makes approved Canon the spatial source; released behavior makes approved Floor Plan geometry authoritative before Canon generation.
- The Vision_Baseline defers iteration without regeneration; released behavior implements appearance-only World revision without geometry or asset rebuilding.
- The original demo alternates between one pendant and the canonical release prompt requirement of exactly three pendants; release evidence does not define general product semantics.
- Package version, interface version, release commit, and Workflow_Profile identity evolve without a documented cross-version policy.
- Current V9 active profile R3 differs from released historical V9 R2 despite the retained-interface stability policy.
- Current retained-interface navigation exposes V10 without V10 Release_Evidence or a release commit, although absent interface selection still defaults to V9.


## Recommended Capability Spec Catalog and Sequence

| Order | Recommended spec | Kind | Primary boundary | Depends on | Preservation status |
|---:|---|---|---|---|---|
| 1 | `behavior-characterization-and-traceability` | Shared_Foundation | Evidence inventory, Traceability_Matrix, test taxonomy, baseline fixtures, release-status rules, and intentional-change records. | This decomposition spec | Released and experimental evidence |
| 2 | `shared-domain-contracts-and-spatial-units` | Shared_Foundation | Pydantic contracts, coordinate systems, dimensions, IDs, materials, physics, lights, openings, validation reports, and serialization invariants. | 1 | Released plus experimental schema additions |
| 3 | `camera-frame-and-view-consistency` | Shared_Foundation | Camera_Contract, projection math, raster identity, landmarks, image normalization, Blockout/Canon registration, World initialization, orbit, and exact reset. | 1, 2 | Released V9 behavior |
| 4 | `provider-runtime-and-offline-fallbacks` | Shared_Foundation | Ollama, vision, OpenAI-compatible, ComfyUI, image API, deadlines, retries, cancellation, readiness, and deterministic fallback policies. | 1, 2 | Released behavior |
| 5 | `interface-and-workflow-version-compatibility` | Shared_Foundation | Query versions, defaults, Retained_Interface rules, immutable Workflow_Profile catalog, active/historical mappings, and package/interface/profile/release relationships. | 1, 2 | Released V3–V9 plus experimental V9 R3/V10 decisions |
| 6 | `session-lifecycle-state-and-persistence` | Shared_Foundation | Session creation, restoration, state transitions, revisions, errors, mutable indexes, progress, and output isolation. | 2, 5 | Released behavior |
| 7 | `workflow-provenance-and-artifact-integrity` | Shared_Foundation | Immutable snapshots, Canon lifecycle manifests, camera/alignment bindings, metadata, hashes, legacy interpretation, and integrity failures. | 2, 3, 5, 6 | Released V8/V9 behavior |
| 8 | `scene-brief-interpretation` | Capability | Description-to-`SceneConcept` interpretation, structured repair, deadlines, fallback semantics, and brief presentation. | 2, 4, 6 | Released behavior |
| 9 | `metric-floor-plan-authoring-and-validation` | Capability | Metric room, items, openings, camera intent, normalization, stable IDs, revisions, approval, released warnings, and experimental V10 blockers. | 2, 3, 4, 6, 8 | Released extension plus experimental V10 validation |
| 10 | `plan-and-blockout-artifact-rendering` | Capability | Floor Plan JSON/SVG, primitive and articulated Blockout PNG, opening visibility, camera projection, artifact identity, and revision binding. | 3, 7, 9 | Released V9 primitive behavior plus experimental R3 articulation |
| 11 | `canon-image-generation-and-approval` | Capability | Prompt construction, profile-selected generation, Blockout conditioning, providers, bounded retries, rejection, approval, artifacts, and experimental three-state alignment review. | 3, 4, 5, 6, 7, 8, 10 | Released V9 R2 plus experimental V10 behavior |
| 12 | `spatial-scene-graph-and-physics-planning` | Capability | Appearance, physics, lighting, approved-plan constraints, validation, spatial-authority decision, and Scene Graph output. | 2, 4, 9, 11 | Released behavior with authority conflict |
| 13 | `procedural-mesh-asset-factory` | Capability | Primitive and custom GLB generation, materials, scale, naming, validation, and future reconstruction/CAD boundary. | 2, 12 | Released narrowed behavior |
| 14 | `godot-project-assembly-and-runtime` | Capability | Project files, room shell, meshes, bodies, collisions, lights, controller, grabbing, doors, and runnable output. | 2, 3, 12, 13 | Released aligned behavior |
| 15 | `world-revision-and-canon-comparison` | Capability | Render upload, vision comparison, geometry-safe patches, similarity report, revision history, and reassembly. | 4, 6, 7, 11, 12, 14 | Released extension |
| 16 | `web-workflow-api-and-artifact-delivery` | Capability | FastAPI commands, approval gates, status, history, telemetry routing, verified artifact serving, mesh serving, download, errors, and polling. | 6 through 15 as applicable | Released V3–V9 plus experimental V10 routes |
| 17 | `versioned-web-experience-and-accessibility` | Capability | Conversation UI, stage rail, history controls, telemetry display, camera frame, Three.js preview, splitter, keyboard behavior, version navigation, and retained isolation. | 3, 5, 16 | Released V3–V9 plus experimental V10 presentation |
| 18 | `historical-run-stage-and-revision-inspection` | Capability | Session index, read-only history, stage availability, revision selection, verified serving, and legacy warnings. | 7, 16, 17 | Released V8/V9 behavior |
| 19 | `privacy-conscious-event-logging` | Shared_Foundation | Sanitized click, lifecycle, process, API, and validation records with user-content exclusions. | 5, 6, 16, 17 | Released behavior |
| 20 | `execution-telemetry-heartbeat-and-eta` | Shared_Foundation | Substep timing, heartbeat, samples, confidence thresholds, cancellation, failures, and telemetry APIs. | 4, 6, 16, 17 | Released V8/V9 behavior |
| 21 | `release-qualification-and-evidence` | Shared_Foundation | Canonical prompt, fresh-session gate, affected-stage inspection, local vision screening, browser/runtime checks, compatibility regression, defect discard, and release records. | 1 through 20 as applicable | Released governance; V10 evidence absent |
| 22 | `persistent-project-knowledge-and-automation` | Shared_Foundation | Memory observations, topic keys, conflicts, wiki lifecycle, hooks, watchmen, graph sync, platform compatibility, and durable spec links. | 1, 21 | Workspace automation with verification gaps |

## Sequence Waves

1. **Wave 0 — Baseline control:** `behavior-characterization-and-traceability`.
2. **Wave 1 — Shared contracts:** `shared-domain-contracts-and-spatial-units`, then `camera-frame-and-view-consistency`; `provider-runtime-and-offline-fallbacks` can begin after the domain contract.
3. **Wave 2 — Compatibility, state, and evidence:** `interface-and-workflow-version-compatibility`, then `session-lifecycle-state-and-persistence`, then `workflow-provenance-and-artifact-integrity`.
4. **Wave 3 — Intent and plan:** `scene-brief-interpretation`, then `metric-floor-plan-authoring-and-validation`, then `plan-and-blockout-artifact-rendering`.
5. **Wave 4 — Canon and spatial world:** `canon-image-generation-and-approval`, then `spatial-scene-graph-and-physics-planning`.
6. **Wave 5 — Assets and runtime:** `procedural-mesh-asset-factory`, then `godot-project-assembly-and-runtime`.
7. **Wave 6 — Iteration and API:** `world-revision-and-canon-comparison`, then `web-workflow-api-and-artifact-delivery`.
8. **Wave 7 — Experience and operations:** `versioned-web-experience-and-accessibility`, `historical-run-stage-and-revision-inspection`, `privacy-conscious-event-logging`, and `execution-telemetry-heartbeat-and-eta` can proceed according to the Dependency_Graph.
9. **Wave 8 — Governance:** `release-qualification-and-evidence`, then `persistent-project-knowledge-and-automation`.

## Evidence Gap Register

- KiroGraph reports 24 files pending synchronization; direct file reads and version-control evidence corroborate affected findings, but the graph cannot be treated as complete.
- Workflow_Profile documents for released interfaces contain `release_commit: None`, so profile-to-release commit binding is implicit rather than encoded.
- No conventional first-party collected test suite establishes unit, property, contract, or integration coverage.
- `test_comfyui.py` executes an integration probe at import time without assertions.
- V7–V9 browser and release scripts are standalone Validation_Evidence rather than collected tests.
- No V10 release harness, clean V10 fresh-session record, or V10 release commit is present.
- `output/logs/v10.jsonl` contains execution activity but does not establish a complete clean pass.
- `src/floor_plan/geometry.py` is untracked; current repository status also includes modified files and deleted spike-spec files.
- Hook configuration expresses intended automation, but successful cross-platform execution is not established; the sync hook uses `/dev/null` syntax and the vendor setup hook has an empty command.
- The configured wiki contains zero pages and zero sources; Watchmen reports zero pending observations against its threshold of five, so no synthesis is ready.
- KiroGraph reports zero dependencies because Python dependencies are not represented by the current security manifest scan, while `pyproject.toml` declares runtime and development dependencies.

## Open Decision Register

- Decide whether approved Floor Plan or approved Canon owns spatial truth.
- Decide whether active V9 profile R3 must move to a new interface version, revert to released R2 for new V9 sessions, or receive an explicit compatibility exception.
- Decide whether V10 remains linked and directly accessible during development or is hidden until V10 completes the zero-state release loop; the absent-version default remains released V9.
- Decide whether V10 strict geometry validation and Canon alignment review release together or as separate interface increments.
- Define a formal relationship among package version `0.1.0`, interface query versions, release commits, and Workflow_Profile identifiers.
- Bind each released Workflow_Profile to an immutable release commit in profile metadata or document an alternative authoritative mapping.
- Replace or wrap direct evidence scripts with a collected test architecture while retaining expensive provider, browser, GPU, and Godot checks as integration or release suites.
- Define product-wide spatial failure criteria beyond released warning behavior and experimental V10 blockers.
- Decide whether the future asset-factory specification preserves procedural output, adopts the researched GIFT/CAD path, or reintroduces Vision_Baseline reconstruction tools.
- Decide whether Canon annotation, direct Godot launch, event-stream progress, and VLM spatial analysis remain deferred or become future Capability_Spec documents.
- Decide whether exactly three pendants is only a canonical release-fixture rule or a product requirement for diner prompts.
- Map `llm-driven-upbge-runtime` and `gift-cad-world-assets` to the Capability_Catalog and Dependency_Graph before treating either cross-cutting proposal as a substitute for prerequisite Shared_Foundation specifications.
- Populate the project wiki with approved architecture and process knowledge or document why source-linked memory is sufficient.
- Correct, replace, disable, or verify platform-sensitive and empty hooks.
- Reconcile the deleted `world-cad-geometry-backend-spike` artifacts with the current `gift-cad-world-assets` requirements before treating the CAD research as an approved capability commitment.

## Recommended Next Specification

Create `behavior-characterization-and-traceability` as the next decomposition-aligned Capability_Spec. The specification should consolidate the characterization already recorded by `llm-driven-upbge-runtime` task 1.1 into executable baseline fixtures and a durable Traceability_Matrix before additional product implementation. Priority coverage remains V3–V9 retention, V9 R2 released new-session interpretation, V8/V9 session restoration, Camera_Contract identity and exact reset, plan authority, provenance immutability, artifact integrity, the V9 clean zero-state workflow, and explicit separation of experimental V9 R3/V10 behavior. Existing `llm-driven-upbge-runtime` and `gift-cad-world-assets` planning artifacts SHALL remain separate proposals until their cross-boundary dependencies and preservation obligations are mapped to the Capability_Catalog.