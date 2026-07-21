# Requirements Document

## Introduction

This specification defines an offline experiment for an optional, reversible, per-object parametric CAD geometry backend within World asset generation. The experiment begins only after Canon approval and Scene_Graph creation. It evaluates whether isolated eligible-object Canon crops and SceneObject metadata can produce safe CadQuery programs, valid solids, dimensionally correct GLB assets, and evidence sufficient for a later disposable integration spike. Plan and Blockout remain room-geometry and placement authorities; Canon remains visual authority; the deterministic trimesh backend remains the default and fallback. The experiment does not change application code, production behavior, or user interfaces.

## Glossary

- **World_Pipeline**: Existing workflow that turns an approved Canon and Scene_Graph into an assembled interactive World.
- **Experiment_Orchestrator**: Offline controller that enforces phase gates, routes eligible per-object trials, and records evidence.
- **Eligibility_Classifier**: Deterministic policy component that classifies SceneObjects for CAD experimentation.
- **CAD_Sidecar**: Isolated disposable process that invokes a permitted model and executes generated CadQuery.
- **CAD_Coder_Baseline**: Released CAD-Coder model selected for Phase_1 evaluation, subject to license and provenance approval.
- **GIFT_Adapter**: Tiny self-owned GIFT-inspired model-improvement adapter evaluated only in Phase_2; GIFT is not a runtime image-to-mesh component.
- **Canon**: Approved reference image and visual authority for object appearance.
- **Canon_Crop**: Isolated 448 by 448 pixel image containing one eligible object, prepared in clean-render or Canon-like form.
- **Canon_Like**: Crop condition that approximates production Canon noise, lighting, background, perspective, and partial visibility while retaining an eligible object.
- **Plan**: Approved floor-plan data that authoritatively defines room dimensions, openings, and placements.
- **Blockout**: Plan-derived spatial rendering that authoritatively represents room geometry and placement.
- **Scene_Graph**: Structured World description created after Canon approval and containing SceneObjects, room shell, doors, windows, and lights.
- **SceneObject**: Existing per-object record containing identity, transform, dimensions, material, physics, type, and visual description.
- **Eligible_Object**: Single, mostly one-piece hard-surface SceneObject suitable for parametric solid construction, such as a shade, vessel, pedestal, bracket, or simple fixture.
- **Excluded_Object**: SceneObject unsuitable for the experiment, including upholstered or organic furniture, articulated objects, assemblies, doors, joints, texture-dependent objects, or severely occluded objects.
- **Prohibited_Target**: Text, Plan, Blockout, Canon generation, scene layout, floor plan, room shell, opening, or whole furnished-room reconstruction.
- **CadQuery_Program**: Model-generated source text limited to the approved CadQuery subset and import allowlist.
- **Valid_Solid**: CadQuery result that executes successfully and passes non-empty, finite, positive-volume solid validation.
- **Tessellator**: Offline converter that turns a Valid_Solid into a triangle mesh and exports GLB.
- **STEP_Artifact**: ISO 10303 boundary-representation file exported from an accepted Valid_Solid as the conversion input to tessellation.
- **GLB_Asset**: Binary glTF object mesh handed to the existing World assembler.
- **Deterministic_Trimesh_Backend**: Existing procedural trimesh object generator and mandatory default/fallback path.
- **World_Assembler**: Existing component that assembles object meshes with Scene_Graph metadata into the World.
- **Warehouse**: Reusable asset store whose records preserve object identity, metadata, provenance, and compatibility.
- **Test_Pair**: Self-owned reference pair containing an input render, CadQuery ground truth, expected solid, dimensions, and provenance.
- **Evaluation_Corpus**: Versioned collection of 20 to 30 self-owned Test_Pairs with disjoint development and held-out partitions.
- **Single_Shot**: One generated CadQuery candidate for one Test_Pair.
- **Best_Of_4**: Four independently generated candidates scored by the same documented selector, with the highest-scoring valid candidate retained.
- **Normalized_IoU**: Intersection-over-union of generated and reference solids after both are normalized to a common unit bounding box and evaluated by a documented fixed-resolution occupancy method.
- **Scaled_Dimension_Error**: Median across axes of absolute generated-versus-SceneObject dimension error divided by the corresponding positive target dimension.
- **Manifoldness**: Mesh property requiring every edge to have exactly two incident faces and a consistently closed surface.
- **Executable_Valid_Solid_Rate**: Percentage of trials whose CadQuery_Program executes and produces a Valid_Solid.
- **GLB_Conversion_Rate**: Percentage of Valid_Solids that produce parseable GLB_Assets.
- **Determinism**: Equality of status, selected candidate, metrics, and artifact hashes across repeated trials with identical immutable inputs, configuration, software versions, and seed.
- **Sandbox_Violation**: Attempted network access, disallowed import, write outside disposable output, mutation of read-only input, subprocess creation, or resource-limit bypass.
- **Evidence_Bundle**: Immutable phase report containing corpus version, configuration, versions, seeds, per-trial artifacts, metrics, failures, provenance, license decisions, and gate results.
- **Phase_Gate**: Machine-checkable criteria that authorize progression to the next experiment phase.
- **Phase_1_Primary_Result**: Clean_Render Best_Of_4 cohort used for the Phase_1 pass-or-fail decision.
- **Production_Gate**: Approval requiring documented quality, security, latency, Peak_VRAM, and licensing thresholds to pass before any production, shipping, or UI work.
- **Clean_Render**: Controlled 448 by 448 pixel render of one Test_Pair object with an unobstructed silhouette and neutral background.
- **Severe_Occlusion**: Test-pair condition in which less than 60 percent of the reference object silhouette is visible in the Canon_Crop.
- **Held_Out_Partition**: Test_Pairs excluded from adapter training, candidate selection tuning, and threshold tuning.
- **IoU_Error**: One minus Normalized_IoU.
- **Compile_Failure**: Generated CadQuery_Program that cannot be parsed, imported under the allowlist, or executed to completion.
- **Latency**: Wall-clock seconds from sidecar request acceptance through final trial result.
- **Peak_VRAM**: Maximum accelerator memory allocated during one trial, measured in mebibytes.
- **Triangle_Count**: Number of triangles in the exported GLB_Asset.
- **Sandbox**: Enforced execution boundary with no network, read-only input, disposable output, import allowlist, and CPU, RAM, and time limits.
- **Stop_Condition**: Condition requiring the current phase to halt without progression.
- **Validation_Harness**: Offline test component that generates bounded inputs and checks correctness properties over repeated trials.
- **Artifact_Hash**: Cryptographic digest of canonicalized source, solid, metric, or GLB bytes used for deterministic comparison.
- **Numeric_Tolerance**: Maximum absolute floating-point difference of 0.00001 for metadata and normalized-coordinate comparisons.

## Requirements

### Requirement 1: Preserve Pipeline Authorities and Scope

**User Story:** As a World pipeline maintainer, I want the experiment confined to per-object geometry generation, so that approved upstream decisions remain authoritative.

#### Acceptance Criteria

1. THE Experiment_Orchestrator SHALL operate after Canon approval and Scene_Graph creation.
2. THE Experiment_Orchestrator SHALL preserve Plan as the authority for room dimensions, openings, and placements.
3. THE Experiment_Orchestrator SHALL preserve Blockout as the Plan-derived authority for room geometry and placement.
4. THE Experiment_Orchestrator SHALL preserve Canon as the visual authority for generated object geometry.
5. IF a request targets a Prohibited_Target, THEN THE Experiment_Orchestrator SHALL reject the request before model invocation.
6. THE Experiment_Orchestrator SHALL accept exactly one SceneObject and one corresponding Canon_Crop per CAD trial.
7. THE Experiment_Orchestrator SHALL leave Text interpretation, Plan generation, Blockout generation, Canon generation, Scene_Graph creation, and scene layout outside the experiment boundary.
8. THE Experiment_Orchestrator SHALL leave floor plans, room shells, openings, and furnished-room reconstruction outside the experiment boundary.

### Requirement 2: Classify Eligible Objects

**User Story:** As an experiment operator, I want deterministic object eligibility decisions, so that the model is tested only on the intended hard-surface slice.

#### Acceptance Criteria

1. WHEN a SceneObject represents a single mostly one-piece hard-surface shade, vessel, pedestal, bracket, or simple fixture, THE Eligibility_Classifier SHALL classify the SceneObject as an Eligible_Object.
2. WHEN a SceneObject represents upholstered furniture, organic furniture, an articulated object, an assembly, a door, a joint, or a texture-dependent object, THE Eligibility_Classifier SHALL classify the SceneObject as an Excluded_Object.
3. WHEN a Canon_Crop has Severe_Occlusion, THE Eligibility_Classifier SHALL classify the SceneObject as an Excluded_Object.
4. WHEN a candidate represents a floor plan, layout, room shell, opening, or whole furnished room, THE Eligibility_Classifier SHALL classify the candidate as a Prohibited_Target.
5. WHEN identical classification inputs and policy versions are provided, THE Eligibility_Classifier SHALL return the same classification and reason code.
6. IF required SceneObject metadata or a corresponding Canon_Crop is absent, THEN THE Eligibility_Classifier SHALL return an ineligible reason code.

### Requirement 3: Preserve Default and Fallback Behavior

**User Story:** As a World pipeline maintainer, I want deterministic trimesh generation to remain authoritative by default, so that the experiment is reversible and non-disruptive.

#### Acceptance Criteria

1. THE World_Pipeline SHALL select the Deterministic_Trimesh_Backend as the default object-geometry backend.
2. IF a SceneObject is not an Eligible_Object, THEN THE Experiment_Orchestrator SHALL route the SceneObject to the Deterministic_Trimesh_Backend.
3. IF CAD generation, validation, tessellation, scaling, or GLB export fails, THEN THE Experiment_Orchestrator SHALL route the unchanged SceneObject to the Deterministic_Trimesh_Backend.
4. WHEN fallback occurs, THE Experiment_Orchestrator SHALL record the failure stage and reason code in the Evidence_Bundle.
5. WHEN the CAD option is disabled after a trial, THE World_Pipeline SHALL generate the same deterministic trimesh result as the pre-trial path for identical Scene_Graph input.
6. WHILE a Production_Gate remains incomplete, THE Experiment_Orchestrator SHALL restrict CAD outputs to offline or disposable Phase_3 locations.

### Requirement 4: Prepare the Phase 1 Evaluation Corpus

**User Story:** As an evaluation owner, I want a small self-owned benchmark with clean and production-like inputs, so that baseline capability and degradation are measured legally and separately.

#### Acceptance Criteria

1. THE Evaluation_Corpus SHALL contain between 20 and 30 Test_Pairs inclusive.
2. THE Evaluation_Corpus SHALL contain only Test_Pairs with recorded self-ownership provenance.
3. THE Evaluation_Corpus SHALL provide one Clean_Render and one Canon_Like Canon_Crop at 448 by 448 pixels for each Test_Pair.
4. THE Evaluation_Corpus SHALL provide CadQuery ground truth, reference solid, positive target dimensions, and eligibility label for each Test_Pair.
5. THE Evaluation_Corpus SHALL define versioned development and Held_Out_Partition membership before Phase_1 execution.
6. THE Experiment_Orchestrator SHALL report Clean_Render and Canon_Like metrics as separate cohorts.
7. THE Experiment_Orchestrator SHALL report Canon_Like degradation relative to Clean_Render for every shared metric.

### Requirement 5: Execute the Released CAD-Coder Baseline

**User Story:** As a research engineer, I want Phase 1 to test the released baseline under controlled decoding modes, so that later adapter work has an honest comparison point.

#### Acceptance Criteria

1. WHILE Phase_1 is active, THE CAD_Sidecar SHALL invoke only the approved CAD_Coder_Baseline.
2. WHILE official GIFT code or checkpoints remain unavailable, THE Experiment_Orchestrator SHALL exclude official GIFT execution from Phase_1.
3. WHEN a Phase_1 Test_Pair is evaluated, THE Experiment_Orchestrator SHALL run both Single_Shot and Best_Of_4 modes with documented immutable generation settings.
4. WHEN Best_Of_4 mode is evaluated, THE Experiment_Orchestrator SHALL generate exactly four candidate CadQuery_Programs.
5. WHEN Best_Of_4 candidates are available, THE Experiment_Orchestrator SHALL retain the highest-scoring Valid_Solid under the documented selector.
6. WHEN no Best_Of_4 candidate produces a Valid_Solid, THE Experiment_Orchestrator SHALL record a failed Best_Of_4 trial.
7. THE Experiment_Orchestrator SHALL prevent Phase_1 artifacts from modifying model weights or application code.

### Requirement 6: Enforce the CAD Sandbox

**User Story:** As a security reviewer, I want generated programs executed within strict resource and capability boundaries, so that model output cannot affect the host or external systems.

#### Acceptance Criteria

1. WHILE a CadQuery_Program executes, THE Sandbox SHALL deny all network access.
2. WHILE a CadQuery_Program executes, THE Sandbox SHALL expose trial inputs through a read-only mount.
3. WHILE a CadQuery_Program executes, THE Sandbox SHALL permit writes only within a unique disposable output location.
4. WHILE a CadQuery_Program executes, THE Sandbox SHALL permit imports only from a versioned allowlist containing CadQuery and explicitly approved standard-library modules.
5. WHILE a CadQuery_Program executes, THE Sandbox SHALL enforce configured CPU, RAM, and wall-clock limits.
6. IF a CadQuery_Program requests a disallowed import, subprocess, external path, network operation, or resource-limit bypass, THEN THE Sandbox SHALL terminate the trial and record a Sandbox_Violation.
7. WHEN a trial completes or terminates, THE Sandbox SHALL destroy the disposable execution environment after evidence capture.
8. THE Sandbox SHALL prevent generated source from executing in the World_Pipeline process.

### Requirement 7: Validate, Tessellate, Scale, and Export

**User Story:** As a World asset engineer, I want generated solids converted into bounded GLB assets, so that successful results can be assessed and later handed to the existing assembler.

#### Acceptance Criteria

1. WHEN a CadQuery_Program completes, THE CAD_Sidecar SHALL verify that the result is a Valid_Solid before tessellation.
2. IF solid validation fails, THEN THE CAD_Sidecar SHALL reject the candidate before GLB export.
3. WHEN a Valid_Solid is accepted, THE CAD_Sidecar SHALL export one parseable STEP_Artifact.
4. WHEN a STEP_Artifact is accepted, THE Tessellator SHALL generate a finite triangle mesh.
5. WHEN a triangle mesh is generated, THE Tessellator SHALL scale the mesh to the SceneObject dimensions while preserving axis correspondence.
6. WHEN scaling completes, THE Tessellator SHALL export one parseable GLB_Asset for the SceneObject.
7. WHEN GLB export completes, THE Tessellator SHALL measure Manifoldness and Triangle_Count.
8. IF any SceneObject target dimension is non-positive or non-finite, THEN THE CAD_Sidecar SHALL reject the trial with an invalid-dimensions reason code.
9. IF the STEP_Artifact cannot be parsed, THEN THE CAD_Sidecar SHALL reject the candidate before tessellation.
10. IF the GLB_Asset contains non-finite coordinates or has zero triangles, THEN THE CAD_Sidecar SHALL reject the GLB_Asset.

### Requirement 8: Preserve SceneObject and World Contracts

**User Story:** As a World assembler maintainer, I want CAD geometry to substitute only the object mesh, so that all existing World semantics remain stable.

#### Acceptance Criteria

1. WHEN a GLB_Asset is handed to the World_Assembler, THE Experiment_Orchestrator SHALL preserve the SceneObject identifier without modification.
2. WHEN a GLB_Asset is handed to the World_Assembler, THE Experiment_Orchestrator SHALL preserve SceneObject position, rotation, scale, and dimensions without modification.
3. WHEN a GLB_Asset is handed to the World_Assembler, THE Experiment_Orchestrator SHALL preserve SceneObject material and physics metadata without modification.
4. WHEN a GLB_Asset is handed to the World_Assembler, THE Experiment_Orchestrator SHALL preserve SceneObject lighting relationships without modification.
5. WHEN a GLB_Asset is handed to the World_Assembler, THE Experiment_Orchestrator SHALL preserve the shared object identity used by real and game modes.
6. WHEN a GLB_Asset is stored in the Warehouse, THE Experiment_Orchestrator SHALL attach generator, model, corpus, license, source, and metric provenance.
7. WHEN a Warehouse GLB_Asset is reused, THE World_Assembler SHALL consume the same object and metadata contract used by deterministic trimesh assets.
8. THE Experiment_Orchestrator SHALL prevent CAD geometry from changing room-shell reconstruction or object placement.

### Requirement 9: Measure Phase 1 Outcomes and Apply Gates

**User Story:** As an experiment decision owner, I want complete quantitative evidence and explicit thresholds, so that progression depends on reproducible capability rather than visual anecdotes.

#### Acceptance Criteria

1. WHEN each Phase_1 trial completes, THE Experiment_Orchestrator SHALL record execution status, solid-validity status, STEP-to-GLB conversion status, Normalized_IoU, Scaled_Dimension_Error, Manifoldness, Triangle_Count, Latency, Peak_VRAM, Determinism result, and Sandbox_Violation count.
2. WHEN Phase_1 execution completes, THE Experiment_Orchestrator SHALL compute Executable_Valid_Solid_Rate over all attempted trials for each input cohort and generation mode.
3. WHEN Phase_1 execution completes, THE Experiment_Orchestrator SHALL compute GLB_Conversion_Rate over all Valid_Solids for each input cohort and generation mode.
4. WHEN Phase_1 execution completes, THE Experiment_Orchestrator SHALL compute median Normalized_IoU and median Scaled_Dimension_Error for each input cohort and generation mode.
5. WHEN the Phase_1_Primary_Result achieves at least 95 percent Executable_Valid_Solid_Rate, at least 90 percent GLB_Conversion_Rate, median Normalized_IoU of at least 0.75, median Scaled_Dimension_Error of at most 0.05, zero Sandbox_Violations, and zero Determinism mismatches, THE Phase_Gate SHALL mark Phase_1 quality and security criteria as passed.
6. IF any Phase_1 threshold is missed, THEN THE Phase_Gate SHALL mark Phase_1 as failed and prohibit Phase_2 progression.
7. WHEN Phase_1 evaluation completes, THE Experiment_Orchestrator SHALL publish an Evidence_Bundle with per-cohort distributions and failure categories.
8. THE Experiment_Orchestrator SHALL retain Canon_Like results as a separate degradation report rather than merging Canon_Like results into Clean_Render gate values.

### Requirement 10: Enforce License and Provenance Gates

**User Story:** As a compliance reviewer, I want every model, dataset, and derived artifact approved before use, so that experimental evidence cannot create unlicensed shipping risk.

#### Acceptance Criteria

1. WHEN CAD_Coder_Baseline loading is requested, THE Experiment_Orchestrator SHALL require a recorded source URL, version, checksum, weight license, code license, permitted-use decision, and reviewer approval.
2. IF the CAD_Coder_Baseline license or provenance record is absent, ambiguous, incompatible, or unapproved, THEN THE Experiment_Orchestrator SHALL stop Phase_1 before model invocation.
3. WHEN GenCAD-derived artifact access is requested, THE Experiment_Orchestrator SHALL require a recorded source, transformation lineage, applicable license, permitted-use decision, and reviewer approval.
4. IF a GenCAD-derived artifact lacks approved license and provenance evidence, THEN THE Experiment_Orchestrator SHALL exclude the artifact from every phase.
5. WHEN generated GLB_Asset admission to the Warehouse is requested, THE Experiment_Orchestrator SHALL attach the approved upstream model and data provenance record.
6. IF an artifact provenance chain contains an unresolved license conflict, THEN THE Experiment_Orchestrator SHALL quarantine the artifact outside the Warehouse.
7. THE Experiment_Orchestrator SHALL use only self-owned Test_Pairs during Phase_1 and Phase_2.

### Requirement 11: Gate the GIFT-Inspired Adapter Experiment

**User Story:** As a research engineer, I want adapter work attempted only after a strong baseline, so that additional model work is justified by held-out evidence.

#### Acceptance Criteria

1. WHEN the Phase_1 Phase_Gate passes, THE Experiment_Orchestrator SHALL permit creation of a tiny self-owned GIFT_Adapter experiment plan.
2. WHILE the Phase_1 Phase_Gate has not passed, THE Experiment_Orchestrator SHALL prohibit GIFT_Adapter training and evaluation.
3. THE GIFT_Adapter SHALL operate as offline model improvement or data augmentation rather than as a World_Pipeline runtime image-to-mesh component.
4. THE GIFT_Adapter SHALL train only on self-owned Test_Pairs outside the Held_Out_Partition.
5. WHEN Phase_2 evaluation runs, THE Experiment_Orchestrator SHALL compare the GIFT_Adapter and CAD_Coder_Baseline on the same Held_Out_Partition, seeds, modes, and metric definitions.
6. WHEN the GIFT_Adapter achieves at least a 10 percent relative reduction in median IoU_Error or at least a 10 percent relative reduction in Compile_Failure rate without regressing Phase_1 security and conversion gates, THE Phase_Gate SHALL mark Phase_2 as passed.
7. IF the GIFT_Adapter fails to achieve the required held-out improvement, THEN THE Phase_Gate SHALL stop adapter progression.
8. WHEN Phase_2 completes, THE Experiment_Orchestrator SHALL record adapter size, training inputs, training settings, checkpoints, held-out results, and license provenance in the Evidence_Bundle.

### Requirement 12: Gate a Disposable World Integration Spike

**User Story:** As a World engineer, I want any integration trial manual, allowlisted, and disposable, so that research output cannot become an accidental production dependency.

#### Acceptance Criteria

1. WHEN both Phase_1 and Phase_2 Phase_Gates pass, THE Experiment_Orchestrator SHALL permit a manual Phase_3 integration spike for explicitly allowlisted Eligible_Objects.
2. WHILE either prior Phase_Gate has not passed, THE Experiment_Orchestrator SHALL prohibit Phase_3 execution.
3. WHILE Phase_3 is active, THE Experiment_Orchestrator SHALL require a human operator to select each allowlisted SceneObject.
4. WHILE Phase_3 is active, THE Experiment_Orchestrator SHALL write GLB_Assets only to a disposable World-stage output.
5. WHEN a Phase_3 GLB_Asset passes validation, THE Experiment_Orchestrator SHALL hand the GLB_Asset to the existing World_Assembler without changing the Scene_Graph.
6. IF a Phase_3 CAD attempt fails, THEN THE Experiment_Orchestrator SHALL use the Deterministic_Trimesh_Backend for the affected SceneObject.
7. THE Experiment_Orchestrator SHALL exclude Phase_3 controls from production and user interfaces.
8. THE Experiment_Orchestrator SHALL exclude Phase_3 artifacts from shipping packages and production Warehouse namespaces.
9. WHEN Phase_3 authorization is requested, THE Phase_Gate SHALL require approved numerical limits for Latency, Peak_VRAM, Triangle_Count, and Scaled_Dimension_Error.
10. WHEN Phase_3 completes, THE Experiment_Orchestrator SHALL record assembler compatibility, fallback behavior, resource metrics, visual review, and metadata-preservation results.

### Requirement 13: Apply Stop Conditions

**User Story:** As an experiment owner, I want unsafe, unlicensed, low-quality, or non-reproducible work stopped early, so that failed research cannot drift toward production.

#### Acceptance Criteria

1. WHEN any Sandbox_Violation occurs, THE Experiment_Orchestrator SHALL halt the active phase and revoke progression approval.
2. WHEN any required license or provenance decision is rejected or unresolved, THE Experiment_Orchestrator SHALL halt affected model and artifact use.
3. WHEN a repeated deterministic trial produces a Determinism mismatch, THE Experiment_Orchestrator SHALL halt metric aggregation for the affected configuration.
4. WHEN Phase_1 misses any required gate, THE Experiment_Orchestrator SHALL stop before Phase_2.
5. WHEN Phase_2 misses the held-out improvement gate, THE Experiment_Orchestrator SHALL stop before Phase_3.
6. WHEN Phase_3 changes any preserved SceneObject contract field, THE Experiment_Orchestrator SHALL halt the integration spike and discard the affected output.
7. IF configured CPU, RAM, time, Latency, Peak_VRAM, or Triangle_Count limits are exceeded, THEN THE Experiment_Orchestrator SHALL terminate the affected trial and record the limit breach.
8. IF production or UI integration is requested before the Production_Gate passes, THEN THE Experiment_Orchestrator SHALL reject the request and preserve offline-only status.

### Requirement 14: Verify Correctness Properties

**User Story:** As a test engineer, I want generative correctness checks across broad input ranges, so that routing, isolation, scaling, selection, and contract preservation hold beyond example fixtures.

#### Acceptance Criteria

1. WHEN the Validation_Harness generates a SceneObject without explicit CAD selection, THE Experiment_Orchestrator SHALL select the Deterministic_Trimesh_Backend.
2. WHEN the Validation_Harness generates an Excluded_Object or Prohibited_Target, THE Experiment_Orchestrator SHALL avoid CAD_Sidecar invocation and return the required rejection or fallback reason.
3. WHEN the Validation_Harness generates positive finite target dimensions and a Valid_Solid, THE Tessellator SHALL scale each GLB_Asset axis to the corresponding target dimension within 0.1 percent relative error.
4. WHEN the Validation_Harness substitutes CAD geometry for arbitrary valid SceneObjects, THE Experiment_Orchestrator SHALL preserve every non-geometry SceneObject field within Numeric_Tolerance.
5. WHEN the Validation_Harness repeats a trial with identical immutable inputs, configuration, software versions, and seed, THE Experiment_Orchestrator SHALL produce equal statuses, selections, metrics within Numeric_Tolerance, and Artifact_Hashes.
6. WHEN the first Best_Of_4 candidate is valid, THE Experiment_Orchestrator SHALL select a candidate whose documented selector score is greater than or equal to the first candidate score.
7. WHEN the Validation_Harness exports and reloads an arbitrary finite tessellated Valid_Solid, THE Tessellator SHALL preserve mesh bounds within Numeric_Tolerance and triangle topology exactly.
8. WHEN the Validation_Harness generates malformed source, disallowed imports, path traversal, network operations, subprocess requests, or resource exhaustion, THE Sandbox SHALL return the documented failure class without creating output outside the disposable location.
9. WHEN the Validation_Harness disables CAD after any generated trial history, THE Deterministic_Trimesh_Backend SHALL produce the same Artifact_Hash as a clean run with identical Scene_Graph input.
10. WHEN the Validation_Harness varies SceneObject position, rotation, material, physics, or lighting relationships while holding geometry inputs constant, THE generated local-space GLB_Asset SHALL remain unchanged.

### Requirement 15: Prevent Production and UI Integration

**User Story:** As a release owner, I want a hard separation between experiment evidence and shipped behavior, so that no feature reaches users without independent readiness approval.

#### Acceptance Criteria

1. WHILE the Production_Gate is incomplete, THE Experiment_Orchestrator SHALL prohibit production configuration, production API, production UI, automatic World routing, and shipping-package changes.
2. WHEN Production_Gate evaluation starts, THE Experiment_Orchestrator SHALL require Phase_1, Phase_2, and Phase_3 Evidence_Bundles with passed gates.
3. WHEN Production_Gate evaluation starts, THE Experiment_Orchestrator SHALL require approved numerical quality, security, Latency, Peak_VRAM, Triangle_Count, and licensing thresholds.
4. WHEN Production_Gate evaluation starts, THE Experiment_Orchestrator SHALL require measured results within every approved threshold on a separately approved release corpus.
5. IF any quality, security, Latency, Peak_VRAM, Triangle_Count, determinism, or licensing criterion fails, THEN THE Production_Gate SHALL remain failed.
6. THE Experiment_Orchestrator SHALL prevent experimental model weights, generated source, and unapproved GLB_Assets from entering shipping artifacts.
7. THE Experiment_Orchestrator SHALL require a separate reviewed implementation specification before any application-code or UI change.
