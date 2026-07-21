# Requirements Document

## Introduction

This specification defines the requirements foundation for converting The Living Room from an implementation-led prototype into a spec-driven project. The decomposition preserves verified behavior, reconciles the implementation with the original prototype vision, separates cohesive capabilities from shared foundations, and establishes an evidence-backed order for creating follow-on capability specifications. This specification changes documentation and planning artifacts only; product code and released interfaces remain outside scope.

## Glossary

- **Decomposition_Program**: The planning system governed by this specification that inventories evidence, classifies behavior, defines capability boundaries, and sequences follow-on specifications.
- **Workspace_Evidence_Set**: The first-party implementation, tests, documentation, steering, hooks, manifests, release artifacts, version history, generated validation evidence, and persistent project knowledge used for decomposition.
- **Vision_Baseline**: The original product intent expressed by `PROTOTYPE_PLAN.md` and the product summary in `README.md`.
- **Source_Evidence**: A file, commit, generated artifact, test result, or persistent observation that supports a current-state finding.
- **Evidence_Status**: One of `released`, `implemented_unreleased`, `experimental`, `documented_only`, `generated_evidence`, `workspace_automation`, or `third_party`.
- **Behavior_Status**: One of `aligned`, `extended`, `narrowed`, `conflicting`, `deferred`, or `absent`, describing a behavior's relationship to the Vision_Baseline.
- **Ground_Truth_Behavior**: Existing behavior supported by implementation plus executable or release evidence, with release status recorded separately.
- **Capability**: A cohesive, independently understandable product or engineering responsibility with an observable outcome and a bounded contract.
- **Capability_Spec**: A follow-on feature specification that owns one Capability and states interfaces, invariants, dependencies, acceptance criteria, and exclusions.
- **Shared_Foundation**: A cross-cutting contract required by multiple Capability_Spec documents, such as domain models, provider policies, session state, provenance, or version compatibility.
- **Boundary_Record**: A catalog entry containing responsibility, inputs, outputs, invariants, dependencies, exclusions, evidence, and ownership for one Capability or Shared_Foundation.
- **Capability_Catalog**: The ordered collection of Boundary_Record entries recommended for follow-on specifications.
- **Traceability_Matrix**: The mapping among Vision_Baseline statements, Source_Evidence, Ground_Truth_Behavior, Behavior_Status, and Capability_Spec ownership.
- **Dependency_Graph**: A directed acyclic graph whose nodes are Capability_Spec documents and whose edges identify prerequisite contracts.
- **Sequence_Wave**: A group of Capability_Spec documents that can be created after the preceding prerequisite wave.
- **Characterization_Test**: A test that records existing observable behavior before refactoring or intentional behavior change.
- **Release_Evidence**: A fresh-session validation record that demonstrates a retained interface and workflow profile satisfy release criteria.
- **Retained_Interface**: A previously released query-versioned web interface that remains accessible and behaviorally stable.
- **Workflow_Profile**: An immutable version-specific generation contract that pins Canon generation behavior and provenance metadata.
- **Persistent_Knowledge**: Durable project observations, decisions, errors, wiki pages, and automation rules intended to survive individual development sessions.
- **Product_Code**: Runtime source, UI assets, provider integrations, generated project logic, and release behavior used by the application.
- **Canon**: The approved reference image used to establish visual intent for the generated world.
- **Blockout**: The rendered three-dimensional preview of approved metric plan geometry used to condition Canon generation.
- **World**: The generated scene graph, mesh set, browser preview, and runnable Godot project.
- **Compare**: The appearance-only Canon-versus-World revision workflow.
## Requirements

### Requirement 1: Establish a Complete Evidence Baseline

**User Story:** As a project owner, I want the decomposition grounded in the whole workspace, so that capability specifications reflect the system that currently exists.

#### Acceptance Criteria

1. WHEN decomposition begins, THE Decomposition_Program SHALL inventory first-party implementation, tests, documentation, steering, hooks, manifests, release artifacts, version history, generated validation evidence, and Persistent_Knowledge.
2. WHEN a workspace item enters the Workspace_Evidence_Set, THE Decomposition_Program SHALL assign one Evidence_Status to the workspace item.
3. THE Decomposition_Program SHALL distinguish first-party behavior from third-party vendor internals, caches, repository internals, and generated binary storage.
4. WHEN representative generated evidence is selected, THE Decomposition_Program SHALL record the selection basis and source path.
5. IF a requested evidence category contains no usable Source_Evidence, THEN THE Decomposition_Program SHALL record the evidence gap.

### Requirement 2: Reconcile Vision and Implementation

**User Story:** As a product decision-maker, I want every meaningful behavior compared with the original vision, so that preservation and change decisions are explicit.

#### Acceptance Criteria

1. WHEN Ground_Truth_Behavior is identified, THE Decomposition_Program SHALL assign one Behavior_Status to the behavior.
2. WHEN Ground_Truth_Behavior agrees with the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `aligned`.
3. WHEN Ground_Truth_Behavior adds a capability absent from the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `extended`.
4. WHEN Ground_Truth_Behavior implements a smaller scope than the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `narrowed`.
5. WHEN Ground_Truth_Behavior contradicts an authority relationship or outcome in the Vision_Baseline, THE Traceability_Matrix SHALL mark the behavior as `conflicting`.
6. IF Source_Evidence disagrees about a behavior, THEN THE Decomposition_Program SHALL record the disagreement, release status, and affected Capability_Spec.
7. THE Traceability_Matrix SHALL retain deferred and absent Vision_Baseline capabilities without representing deferred or absent capabilities as implemented.

### Requirement 3: Define Cohesive Capability Boundaries

**User Story:** As a specification author, I want each meaningful responsibility isolated, so that each follow-on specification has a stable and reviewable scope.

#### Acceptance Criteria

1. WHEN the Decomposition_Program identifies a Capability, THE Capability_Catalog SHALL create one Boundary_Record for the Capability.
2. THE Boundary_Record SHALL state one primary observable outcome.
3. THE Boundary_Record SHALL identify inputs, outputs, invariants, dependencies, exclusions, and Source_Evidence.
4. IF two responsibilities can change independently without changing a shared contract, THEN THE Decomposition_Program SHALL assign the responsibilities to separate Capability_Spec documents.
5. IF multiple responsibilities share one invariant or data contract, THEN THE Decomposition_Program SHALL assign the invariant or data contract to a Shared_Foundation.
6. THE Decomposition_Program SHALL derive Capability boundaries from behavior and contracts rather than source-directory names alone.
7. THE Capability_Catalog SHALL assign exactly one primary owner to every Ground_Truth_Behavior.

### Requirement 4: Isolate Shared Foundations

**User Story:** As an implementer, I want cross-cutting contracts specified before dependent capabilities, so that later specifications do not duplicate or contradict foundational rules.

#### Acceptance Criteria

1. THE Capability_Catalog SHALL define Shared_Foundation boundaries for domain contracts, units and coordinates, provider policies, session state, workflow profiles, provenance, compatibility, privacy, and evidence traceability.
2. WHEN a Capability_Spec consumes a Shared_Foundation, THE Boundary_Record SHALL identify the consumed contract.
3. IF two Shared_Foundation definitions conflict, THEN THE Decomposition_Program SHALL block dependent sequencing until the conflict has an explicit resolution record.
4. THE Decomposition_Program SHALL assign state-transition ownership to one Shared_Foundation.
5. THE Decomposition_Program SHALL assign artifact-identity ownership to one Shared_Foundation.

### Requirement 5: Define Dependencies and Creation Sequence

**User Story:** As a project planner, I want a dependency-aware creation order, so that specifications can be authored and implemented without circular assumptions.

#### Acceptance Criteria

1. WHEN the Capability_Catalog is complete, THE Decomposition_Program SHALL produce a Dependency_Graph covering every Capability_Spec.
2. THE Dependency_Graph SHALL contain no directed cycles.
3. WHEN one Capability_Spec requires another Capability_Spec contract, THE Dependency_Graph SHALL place the prerequisite before the consumer.
4. THE Decomposition_Program SHALL group Capability_Spec documents into numbered Sequence_Wave entries.
5. THE Sequence_Wave entries SHALL place characterization and shared contracts before behavior-changing capability work.
6. WHERE Capability_Spec documents have no unresolved dependency edge between each other, THE Decomposition_Program SHALL identify the Capability_Spec documents as parallel-authoring candidates.
7. IF a dependency is uncertain, THEN THE Decomposition_Program SHALL record the dependency as an open decision rather than infer an unverified contract.

### Requirement 6: Preserve Existing Behavior Deliberately

**User Story:** As a maintainer, I want current behavior protected during conversion, so that decomposition does not become an accidental rewrite.

#### Acceptance Criteria

1. THE Decomposition_Program SHALL treat Ground_Truth_Behavior as the preservation baseline when Ground_Truth_Behavior is aligned with the Vision_Baseline.
2. WHEN Ground_Truth_Behavior is extended, narrowed, or conflicting, THE Boundary_Record SHALL require an explicit preserve, revise, retire, or investigate disposition.
3. WHERE a Retained_Interface exists, THE Capability_Catalog SHALL preserve query-version accessibility and version-specific behavior as a compatibility contract.
4. WHERE a Workflow_Profile exists, THE Capability_Catalog SHALL preserve immutable profile identity and historical session interpretation.
5. IF a follow-on Capability_Spec intentionally changes Ground_Truth_Behavior, THEN THE Capability_Spec SHALL identify affected Retained_Interface entries, Workflow_Profile entries, artifacts, and Characterization_Test cases.
6. THE Decomposition_Program SHALL keep Product_Code changes outside this specification.

### Requirement 7: Establish Verification and Characterization Obligations

**User Story:** As a quality owner, I want every capability tied to verification, so that spec-driven development can prove preservation and new correctness.

#### Acceptance Criteria

1. WHEN a Ground_Truth_Behavior lacks an automated test, THE Capability_Catalog SHALL require a Characterization_Test before behavior refactoring.
2. WHEN a requirement varies meaningfully across generated inputs and tests first-party deterministic logic, THE Boundary_Record SHALL recommend a property-based test.
3. WHEN a requirement depends on an external provider, browser, GPU, Godot runtime, or release environment, THE Boundary_Record SHALL recommend representative integration or smoke tests.
4. WHEN a parser or serializer belongs to a Capability, THE Boundary_Record SHALL require parse, print, error, and round-trip verification.
5. THE Traceability_Matrix SHALL map every acceptance criterion in each future Capability_Spec to at least one planned verification method.
6. IF an existing evidence script is not collected by the project test runner, THEN THE Decomposition_Program SHALL classify the script as validation evidence rather than automated test coverage.
7. THE Capability_Catalog SHALL distinguish release qualification from unit, property, integration, browser, and runtime verification.

### Requirement 8: Specify Versioning, Provenance, and Release Governance

**User Story:** As a release owner, I want version and evidence rules represented as explicit capabilities, so that releases remain reproducible and prior interfaces remain stable.

#### Acceptance Criteria

1. THE Capability_Catalog SHALL define separate ownership for interface versioning, Workflow_Profile selection, immutable workflow snapshots, artifact verification, and release qualification.
2. WHEN a new user-visible interface is specified, THE interface-versioning Capability_Spec SHALL require a new query version, retained prior versions, and a new default version.
3. WHEN a release candidate is evaluated, THE release-qualification Capability_Spec SHALL require a brand-new empty session and the canonical release prompt.
4. IF a release validation defect appears, THEN THE release-qualification Capability_Spec SHALL reject the affected session as Release_Evidence.
5. WHEN Canon generation starts, THE provenance Capability_Spec SHALL require prepared and terminal generation records containing the selected Workflow_Profile, inputs, provider attempts, model identity, seed, artifact hashes, dimensions, and errors.
6. WHEN a session state is persisted, THE provenance Capability_Spec SHALL require an immutable full-state snapshot and a mutable session index.
7. THE release-qualification Capability_Spec SHALL distinguish released V3 through V7 behavior from implemented_unreleased V8 behavior.

### Requirement 9: Specify Privacy-Conscious Observability

**User Story:** As an operator, I want useful diagnostics without user-content leakage, so that workflow behavior can be understood safely.

#### Acceptance Criteria

1. THE Capability_Catalog SHALL define separate boundaries for interface event logging and execution telemetry.
2. WHEN an interface event is recorded, THE event-logging Capability_Spec SHALL exclude prompt text and revision-feedback text.
3. WHEN an execution substep is recorded, THE execution-telemetry Capability_Spec SHALL store stage, substep, timestamps, duration, status, and error type.
4. IF timing samples do not meet the estimator threshold, THEN THE execution-telemetry Capability_Spec SHALL report insufficient evidence instead of an estimated duration.
5. WHEN a historical artifact is served, THE historical-inspection Capability_Spec SHALL omit filesystem paths from the response.
6. IF a recorded artifact hash differs from the current artifact hash, THEN THE historical-inspection Capability_Spec SHALL block artifact delivery and return an integrity error.

### Requirement 10: Integrate Persistent Project Knowledge

**User Story:** As a future contributor, I want durable decisions and lessons connected to specifications, so that project knowledge does not remain trapped in sessions or generated output.

#### Acceptance Criteria

1. THE Capability_Catalog SHALL define a Persistent_Knowledge governance Capability_Spec.
2. WHEN a durable architecture decision, bug cause, compatibility rule, or release lesson is confirmed, THE Persistent_Knowledge Capability_Spec SHALL require one concise observation with a stable topic key.
3. WHEN a persistent observation affects a Capability_Spec, THE Traceability_Matrix SHALL link the observation to the affected Boundary_Record.
4. IF a persistent observation conflicts with a newer decision, THEN THE Persistent_Knowledge Capability_Spec SHALL require an explicit relation and adjudication result.
5. WHEN durable documentation exists, THE Persistent_Knowledge Capability_Spec SHALL require wiki ingestion or an explicit decision to retain the documentation at the source path.
6. IF the project wiki contains zero pages, THEN THE Decomposition_Program SHALL record the wiki as an active configuration with an unpopulated knowledge surface.

### Requirement 11: Produce Reviewable Decomposition Deliverables

**User Story:** As a reviewer, I want a concise but complete decomposition package, so that the team can approve boundaries before design or implementation begins.

#### Acceptance Criteria

1. THE Decomposition_Program SHALL produce the Traceability_Matrix, Capability_Catalog, Dependency_Graph, Sequence_Wave plan, evidence-gap register, and open-decision register.
2. THE Capability_Catalog SHALL assign a kebab-case name to every recommended Capability_Spec.
3. THE Capability_Catalog SHALL state whether each recommended Capability_Spec preserves released behavior, captures implemented_unreleased behavior, or defines future behavior.
4. WHEN a Current-State finding is included, THE Decomposition_Program SHALL cite at least one Source_Evidence path or commit.
5. IF a Current-State finding relies on generated evidence, THEN THE Decomposition_Program SHALL label the finding as environment-specific.
6. THE Decomposition_Program SHALL identify the next recommended Capability_Spec to create after this specification.

### Requirement 12: Maintain Scope and Decision Discipline

**User Story:** As a product owner, I want decomposition decisions separated from product redesign, so that this effort creates a reliable planning foundation.

#### Acceptance Criteria

1. THE Decomposition_Program SHALL limit repository modifications to specification artifacts for `spec-driven-project-decomposition`.
2. THE Decomposition_Program SHALL record future capabilities from the Vision_Baseline without presenting future capabilities as current requirements for behavior preservation.
3. IF evidence cannot establish whether behavior is intentional, THEN THE Decomposition_Program SHALL classify the behavior as an open decision.
4. WHEN a follow-on Capability_Spec begins, THE Specification_Governance SHALL permit returning to this decomposition specification when a boundary or dependency gap is discovered.
5. THE Decomposition_Program SHALL avoid release, commit, dependency, provider, and generated-artifact mutations during requirements creation.

## Current-State Evidence Baseline

| Area | Current behavior | Vision relationship | Status and principal evidence |
|---|---|---|---|
| Domain contracts and pipeline | Pydantic models connect Brief, Floor Plan, Scene Graph, physics, materials, lights, openings, and a persisted session state machine. `WorldBuilder` executes interpretation, plan, Canon, scene graph, assets, assembly, and revision stages. | Aligned core pipeline; extended with explicit session/version/provenance state. | Released plus implemented_unreleased changes: `src/models.py`, `src/pipeline.py`. |
| Description interpretation | A local-first LLM adapter converts plain text into `SceneConcept`; provider order is Ollama, OpenAI-compatible API, then deterministic mock. JSON parsing has one repair retry. | Aligned with local orchestration; extended with API fallback; narrowed because semantic adequacy is not independently validated. | Released: `src/orchestrator/interpreter.py`, `src/orchestrator/llm.py`, `src/orchestrator/mock_llm.py`. |
| Metric plan and Blockout | The user reviews a metric Floor Plan and rendered Blockout before Canon. Plan geometry is normalized and later treated as authoritative. | Extended with an approval stage; conflicting with the original Canon-first authority flow. | Released: `src/floor_plan/*`, `src/pipeline.py`, `src/web/app.py`; release evidence in `.kiro/release-checklist.md`. |
| Canon generation | Canon supports mock, API, ComfyUI, and plan-conditioned workflows. Immutable profiles preserve V3–V8 generation contracts. | Aligned with approval and regeneration; extended with profile pinning; narrowed because annotation overlay behavior is absent. | Released V3–V7 and implemented_unreleased V8 profile: `src/canon_image/generator.py`, `src/workflow_provenance.py`. |
| Spatial scene construction | The LLM adds appearance, physics, and lighting while approved Floor Plan geometry overwrites authored room, object, door, and window geometry. Validation currently emits warnings for some out-of-room positions. | Aligned with a structured Scene Graph; conflicting with the vision's approved-Canon/VLM spatial authority; narrowed because invalid spatial output can remain usable. | Released: `src/scene_graph/builder.py`. |
| Asset production | Every Scene Object and door receives a GLB generated from boxes, cylinders, spheres, or a custom procedural stool. | Aligned with Godot-compatible output; narrowed because TripoSR, Shap-E, segmentation, UV processing, decimation, watertight validation, and file-size validation are absent. | Released: `src/asset_factory/mesh_generator.py`. |
| Godot assembly and runtime | The assembler emits a complete project, room shell, meshes, lights, physics bodies, a first-person controller, grabbing, and door behavior. | Aligned with the walkable physics-first world outcome. | Released: `src/assembler/godot_project.py`; generated projects under `output/*/godot_project`. |
| World revision and Compare | A vision model compares a World render with Canon and applies bounded appearance-only material and lighting patches while preserving geometry. | Extended beyond the original MVP and partially implements deferred iteration; narrowed to appearance-only revisions. | Released API behavior: `src/scene_graph/refiner.py`, `src/pipeline.py`, `src/web/app.py`. |
| Web workflow | FastAPI and browser JavaScript expose session creation, approvals, rejection, plan revision, world revision, status, artifacts, browser 3D preview, and project download. Polling drives progress. | Aligned with the conversation front door; extended with browser preview and download; narrowed because direct Godot launch, annotation overlay, SSE, and WebSocket progress are absent. | Released: `src/web/app.py`, `src/web/static/app.js`, `src/web/templates.py`. |
| Interface versioning | Query versions V3–V7 are retained; the current working tree adds V8 as the default without changing earlier templates by intent. | Extended engineering governance absent from the original vision. | Released V3–V7 commits and `ui-versioning.md`; implemented_unreleased V8 in current working tree. |
| Provenance and history | Sessions persist mutable state plus immutable snapshots and Canon manifests. V8 adds session indexing, stage replay, hash verification, legacy warnings, and sanitized historical APIs. | Extended reproducibility and inspection capability. | Released provenance: `src/workflow_provenance.py`; implemented_unreleased history: `src/web/history.py`, V8 routes in `src/web/app.py`. |
| Observability and privacy | Versioned append-only event logs omit prompt and feedback text. V8 adds substep timing, heartbeat, sample-backed ETA, and telemetry APIs. | Extended operational capability. | Released event logs: `src/web/event_log.py`; implemented_unreleased telemetry: `src/telemetry.py`. |
| Release qualification | Releases require a fresh zero-state session, canonical prompt, stage inspection, browser checks, failure discard, and retained-version validation. | Extended release governance. | Released policy and evidence: `.kiro/steering/ui-versioning.md`, `.kiro/release-checklist.md`, `output/run_v7_release.py`, `output/v7_responsive_check.py`. |
| Test coverage | `test_comfyui.py` is a direct executable integration probe with import-time execution. V7/V8 evidence scripts perform release and browser checks outside a conventional collected test suite. | Narrowed from a maintainable verification foundation; the graph coverage report cannot establish meaningful coverage because public exports are not modeled. | `test_comfyui.py`, `output/run_v7_release.py`, `output/v7_responsive_check.py`, `output/v8_live_clickthrough.py`, `pyproject.toml`. |
| Persistent knowledge and automation | KiroGraph memory contains seven release decisions/errors across two sessions. Hooks request sync, memory capture, wiki ingestion, wiki lint, and watchmen synthesis. The configured wiki contains zero pages. | Extended development-system capability with an unpopulated wiki gap. | `.kirograph/config.json`, `.kiro/hooks/*`, KiroGraph memory status, KiroGraph wiki status. |
| Product and interface versions | The Python package declares `0.1.0`, released UI history reaches V7, and the working tree defaults to V8. | Extended multi-axis versioning with an unresolved relationship among package, interface, and Workflow_Profile versions. | `pyproject.toml`, `src/web/templates.py`, `src/workflow_provenance.py`, git history. |

## Explicit Vision Reconciliation

### Aligned behavior to preserve

- Plain-language interior description becomes a structured scene concept.
- Canon generation supports user rejection and regeneration.
- A structured Scene Graph carries room, object, material, light, opening, and physics data.
- Procedural meshes and Godot assembly produce a walkable first-person project.
- Movable objects receive rigid physics while fixed architecture receives static physics.
- Lighting intent flows from the interpreted scene into Canon and World construction.
- Local Ollama and ComfyUI integrations coexist with an offline mock path.
- The prototype remains single-room and does not implement Warehouse, game mode, real mode, multiplayer, or multi-room navigation.

### Implemented extensions to preserve or decide explicitly

- Metric Floor Plan creation, normalization, revision, approval, SVG rendering, and Blockout rendering precede Canon.
- Approved plan geometry overrides scene-graph geometry.
- Browser Three.js preview and project download supplement the Godot output.
- Query-versioned interfaces, immutable Workflow_Profile entries, immutable state snapshots, and Canon lifecycle manifests preserve historical behavior.
- Append-only privacy-conscious interface logging captures lifecycle, process, click, and validation events.
- Appearance-only World refinement compares a captured render with Canon.
- V8 introduces historical run selection, stage/revision replay, artifact hash checks, live telemetry, heartbeat, and sample-backed ETA, but V8 remains implemented_unreleased in the current working tree.

### Narrowed or absent vision behavior to retain as gaps

- Asset generation is procedural rather than image-to-3D reconstruction and lacks segmentation, decimation, UV, watertightness, scale-tolerance, and file-size gates.
- Scene Graph construction does not analyze the approved Canon with a VLM for object positions or depth.
- Canon feedback is text-based; an image annotation overlay is absent.
- Progress uses HTTP polling; SSE and WebSocket progress are absent.
- The web workflow provides download rather than a direct Godot launch action.
- Scene validation warns about some geometry defects instead of rejecting all invalid layouts.
- Automated unit, property, integration, and contract coverage is not organized as a conventional collected suite.
- The configured persistent wiki is empty.

### Conflicts requiring explicit disposition

- The Vision_Baseline makes approved Canon the spatial source before Scene Graph construction; current behavior makes approved Floor Plan geometry authoritative before Canon generation.
- The Vision_Baseline defers iteration without regeneration; current behavior implements appearance-only World revision without rebuilding geometry or assets.
- The original demo text alternates between one pendant and later release evidence requiring exactly three pendants; the canonical release prompt currently governs release evidence rather than general product semantics.
- The package version, interface version, and Workflow_Profile identity evolve independently without a documented cross-version policy.

## Recommended Capability Spec Catalog and Sequence

| Order | Recommended spec | Kind | Primary boundary | Depends on | Preservation status |
|---:|---|---|---|---|---|
| 1 | `behavior-characterization-and-traceability` | Shared_Foundation | Evidence inventory, Traceability_Matrix, test taxonomy, baseline fixtures, and intentional-change records. | This decomposition spec | Released and implemented_unreleased behavior |
| 2 | `shared-domain-contracts-and-spatial-units` | Shared_Foundation | Pydantic contracts, coordinate system, dimensions, IDs, materials, physics, lights, openings, and serialization invariants. | 1 | Released behavior |
| 3 | `provider-runtime-and-offline-fallbacks` | Shared_Foundation | Ollama, vision, OpenAI-compatible, ComfyUI, image API, timeout, retry, readiness, and mock fallback policies. | 1, 2 | Released behavior |
| 4 | `interface-and-workflow-version-compatibility` | Shared_Foundation | Query versions, defaults, Retained_Interface rules, immutable Workflow_Profile catalog, and package/interface/profile version relationships. | 1, 2 | Released plus open decision |
| 5 | `session-lifecycle-state-and-persistence` | Shared_Foundation | Session creation, restoration, state transitions, revisions, errors, mutable indexes, progress messages, and output isolation. | 2, 4 | Released behavior |
| 6 | `workflow-provenance-and-artifact-integrity` | Shared_Foundation | Immutable snapshots, Canon lifecycle manifests, artifact metadata, hashes, legacy interpretation, and integrity failures. | 2, 4, 5 | Released plus implemented_unreleased behavior |
| 7 | `scene-brief-interpretation` | Capability | Description-to-`SceneConcept` interpretation, structured JSON repair, fallback semantics, and brief presentation. | 2, 3, 5 | Released behavior |
| 8 | `metric-floor-plan-authoring-and-validation` | Capability | Metric room, items, openings, camera, normalization, warnings, stable IDs, revision, and approval. | 2, 3, 5, 7 | Released extension with authority conflict |
| 9 | `plan-and-blockout-artifact-rendering` | Capability | Floor Plan JSON/SVG and Blockout PNG generation, opening visibility, camera projection, artifact identity, and revision binding. | 6, 8 | Released extension |
| 10 | `canon-image-generation-and-approval` | Capability | Prompt construction, profile-selected generation, Blockout conditioning, provider attempts, rejection, approval, and Canon artifacts. | 3, 4, 5, 6, 7, 9 | Released behavior with narrowed feedback UX |
| 11 | `spatial-scene-graph-and-physics-planning` | Capability | Appearance, physics, lighting, approved-plan constraints, validation, Canon authority decision, and Scene Graph output. | 2, 3, 8, 10 | Released behavior with authority conflict |
| 12 | `procedural-mesh-asset-factory` | Capability | Primitive and stool GLB generation, material colors, scale, naming, validation, and future reconstruction boundary. | 2, 11 | Released narrowed behavior |
| 13 | `godot-project-assembly-and-runtime` | Capability | Project files, room shell, imported meshes, bodies, collisions, lights, controller, grabbing, doors, and runnable output. | 2, 11, 12 | Released aligned behavior |
| 14 | `world-revision-and-canon-comparison` | Capability | Render upload, vision comparison, geometry-safe patches, similarity report, revision history, and reassembly. | 3, 5, 6, 10, 11, 13 | Released extension |
| 15 | `web-workflow-api-and-artifact-delivery` | Capability | FastAPI workflow commands, approval gates, status, artifact serving, mesh serving, download, errors, and polling contracts. | 5 through 14 | Released behavior |
| 16 | `versioned-web-experience-and-accessibility` | Capability | Conversation UI, stage rail, Three.js preview, responsive splitter, keyboard behavior, version navigation, and Retained_Interface isolation. | 4, 15 | Released V3–V7 behavior |
| 17 | `historical-run-stage-and-revision-inspection` | Capability | Session index, read-only historical mode, stage availability, revision selection, verified serving, and legacy warnings. | 6, 15, 16 | Implemented_unreleased V8 behavior |
| 18 | `privacy-conscious-event-logging` | Shared_Foundation | Sanitized click, lifecycle, process, API, and validation event records with user-content exclusions. | 4, 5, 15, 16 | Released extension |
| 19 | `execution-telemetry-heartbeat-and-eta` | Shared_Foundation | Substep timing, heartbeat, sample persistence, confidence thresholds, failure states, and telemetry APIs. | 3, 5, 15, 16 | Implemented_unreleased V8 behavior |
| 20 | `release-qualification-and-evidence` | Shared_Foundation | Canonical prompt, fresh-session gate, stage inspection, local vision QA, browser/runtime checks, defect discard, and release records. | 1 through 19 as applicable | Released governance |
| 21 | `persistent-project-knowledge-and-automation` | Shared_Foundation | Memory observations, topic keys, conflict handling, wiki lifecycle, hooks, watchmen, sync, and durable spec links. | 1, 20 | Workspace automation with knowledge gap |

## Sequence Waves

1. **Wave 0 — Baseline control:** `behavior-characterization-and-traceability`.
2. **Wave 1 — Shared contracts:** `shared-domain-contracts-and-spatial-units`, `provider-runtime-and-offline-fallbacks`, `interface-and-workflow-version-compatibility`.
3. **Wave 2 — State and evidence:** `session-lifecycle-state-and-persistence`, `workflow-provenance-and-artifact-integrity`.
4. **Wave 3 — Intent and plan:** `scene-brief-interpretation`, then `metric-floor-plan-authoring-and-validation`, then `plan-and-blockout-artifact-rendering`.
5. **Wave 4 — Canon and spatial world:** `canon-image-generation-and-approval`, then `spatial-scene-graph-and-physics-planning`.
6. **Wave 5 — Assets and runtime:** `procedural-mesh-asset-factory`, then `godot-project-assembly-and-runtime`.
7. **Wave 6 — Iteration and API:** `world-revision-and-canon-comparison`, then `web-workflow-api-and-artifact-delivery`.
8. **Wave 7 — Experience and observability:** `versioned-web-experience-and-accessibility` and `privacy-conscious-event-logging` can begin in parallel after their prerequisites; `historical-run-stage-and-revision-inspection` and `execution-telemetry-heartbeat-and-eta` follow for V8.
9. **Wave 8 — Operational governance:** `release-qualification-and-evidence`, then `persistent-project-knowledge-and-automation`.

## Evidence Gaps and Open Decisions

- Decide whether Floor Plan or approved Canon owns spatial truth; current implementation and original vision assign authority differently.
- Decide whether implemented_unreleased V8 behavior becomes a release target, remains experimental, or is split into history and telemetry releases.
- Define a formal relationship among package version `0.1.0`, interface query versions, release commits, and Workflow_Profile IDs.
- Replace or wrap direct evidence scripts with a collected test architecture while retaining expensive provider and browser checks as integration or release suites.
- Define strict Scene Graph and Floor Plan failure criteria beyond warning emission.
- Decide whether the future asset-factory spec preserves procedural-only output or reintroduces the Vision_Baseline reconstruction pipeline.
- Decide whether Canon annotation, direct Godot launch, event-stream progress, and VLM spatial analysis remain deferred or become future Capability_Spec documents.
- Populate the configured project wiki with approved architecture and process knowledge, or document why source-linked memory is sufficient.

## Recommended Next Specification

Create `behavior-characterization-and-traceability` first. That specification should establish executable baseline fixtures and a durable Traceability_Matrix before any capability design changes, with special coverage for version retention, session restoration, plan authority, Canon profile selection, provenance immutability, artifact integrity, and the released V7 zero-state workflow.