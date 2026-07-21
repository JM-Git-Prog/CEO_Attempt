# Requirements Document

## Introduction

This specification defines a low-risk experiment to determine whether an image-to-CAD model improved by GIFT or inspired by GIFT can serve as an optional, per-object geometry backend during World asset generation. The experiment consumes an isolated image of one object from the approved Canon and the corresponding SceneObject, generates sandboxed CadQuery candidate programs and solid geometry, validates and tessellates accepted geometry to GLB, normalizes the GLB to authoritative SceneObject dimensions, and passes the GLB to the existing World assembler.

The experiment preserves the established authority chain: Text establishes intent; Plan and Blockout establish architecture and placement; the approved Canon establishes visual and art-direction intent; and SceneObject establishes the runtime contract. The experiment is limited to replaceable geometry for eligible individual objects. Existing deterministic trimesh generation remains the default and automatic fallback.

Repository verification found that `src/pipeline.py:215-229` builds the SceneGraph from the approved planning context, `src/pipeline.py:266-274` invokes asset generation during World construction, `src/asset_factory/mesh_generator.py:15-37` emits one GLB path per SceneObject or door through deterministic trimesh generation, and `src/models.py` defines SceneObject identifiers, meter dimensions, transforms, materials, physics, mesh type, primitive shape, and visual description. These existing contracts bound the spike; this specification does not authorize implementation changes during the requirements phase.

## Glossary

- **Experiment**: The research-only program governed by this specification.
- **Experiment_Coordinator**: The component that enforces phase eligibility, gates, stop conditions, and evidence recording.
- **World_Pipeline**: The existing Text-to-Plan-to-Blockout-to-Canon-to-World workflow.
- **World_Assembler**: The existing component that consumes the SceneGraph and object GLB paths to create the World project.
- **Existing_Generator**: The current deterministic trimesh asset generator used as the default geometry backend and automatic fallback.
- **Optional_Geometry_Backend**: The experimental per-object backend that may provide geometry for an Eligible_Object without changing upstream or non-geometry authority.
- **Text**: The user-provided interior description and resulting scene concept.
- **Plan**: The approved metric floor plan and architectural specification.
- **Blockout**: The rendered preview of approved Plan geometry.
- **Canon**: The approved reference image that establishes visual and art-direction intent.
- **SceneGraph**: The existing spatial description containing the room, SceneObject records, lights, doors, and windows.
- **SceneObject**: The runtime contract for one object, including identifier, name, category, dimensions in meters, position, rotation, scale, material, physics, mesh type, primitive shape, and visual description.
- **Authoritative_Dimensions**: The SceneObject `dimensions` values in meters.
- **Authority_Preservation**: Retention of Text, Plan, Blockout, Canon, floor plan, room shell, scene layout, transforms, physics, materials, lighting intent, game behavior, real-mode wiring, and scoring without experimental modification.
- **GIFT**: An offline model-improvement and data-augmentation method that samples and executes multiple CadQuery programs, verifies generated geometry against owned ground-truth CAD using normalized and aligned IoU, and uses high-fidelity alternatives plus rendered near-misses for supervised fine-tuning.
- **GIFT_Inspired_Adaptation**: A small self-owned adaptation that applies selected GIFT concepts without claiming reproduction of the published method.
- **Runtime_Model_Artifact**: The image-to-CAD model artifact deployed for inference after any offline preparation; GIFT itself is not a runtime image-to-mesh converter.
- **CAD-Coder**: The baseline image-to-CAD source project whose inspected source listing uses Apache-2.0 while associated model weights and GenCAD-derived dataset artifacts have unconfirmed licensing.
- **CadQuery**: The Apache-2.0 Python CAD library targeted by generated candidate programs.
- **OCCT**: The Open CASCADE Technology geometry kernel used by CadQuery and subject to a required obligations review.
- **Candidate_Program**: One sampled Python program intended to create one CadQuery solid.
- **Candidate_Set**: The ordered Candidate_Program samples generated for one Benchmark_Pair and inference strategy.
- **Sandbox**: An isolated, disposable execution environment with denied network access, read-only inputs, disposable outputs, allowlisted imports, and enforced resource limits.
- **Run_Limit_Profile**: The recorded finite CPU, RAM, wall-clock time, child-process, output-size, and file-count limits applied to every Sandbox execution.
- **Valid_Solid**: A nonempty CadQuery result that passes execution, topology, finite-coordinate, bounded-complexity, and deterministic artifact validation.
- **STEP**: The intermediate ISO 10303 CAD exchange representation used to verify solid export before GLB conversion.
- **GLB**: The binary glTF mesh artifact consumed by the World_Assembler.
- **Normalized_GLB**: An accepted GLB scaled to the Authoritative_Dimensions without embedding SceneObject placement transforms, materials, or physics changes.
- **Normalized_Aligned_IoU**: Volumetric intersection-over-union after generated and owned ground-truth solids are normalized and aligned by the documented benchmark procedure.
- **Post_Scale_Dimension_Error**: The maximum absolute per-axis difference between Normalized_GLB bounds and Authoritative_Dimensions, divided by the corresponding Authoritative_Dimensions, expressed as a percentage.
- **Executable_Code_Rate**: Candidate_Program executions that complete and produce a CadQuery result divided by attempted Candidate_Program executions.
- **Valid_Solid_Rate**: executable Candidate_Program executions producing a Valid_Solid divided by attempted Candidate_Program executions.
- **Executable_Valid_Solid_Rate**: Benchmark_Pairs producing at least one executable Valid_Solid divided by evaluated Benchmark_Pairs.
- **GLB_Conversion_Rate**: Benchmark_Pairs with an accepted STEP artifact converted to a valid GLB divided by Benchmark_Pairs with an accepted STEP artifact.
- **Clean_Image**: A self-owned 448×448 render matching the model's training-like object presentation.
- **Canon_Like_Image**: A self-owned 448×448 render that approximates isolation, viewpoint, lighting, and occlusion conditions expected from an approved Canon.
- **Benchmark_Pair**: A self-owned hand-authored CadQuery object, owned ground-truth solid, SceneObject description, Clean_Image, and Canon_Like_Image sharing one object identity.
- **Benchmark_Set**: The 20–30 Benchmark_Pairs used in Phase_1.
- **Held_Out_Set**: Benchmark_Pairs excluded from adaptation and candidate selection during Phase_2.
- **Single_Shot**: Runtime inference that samples one Candidate_Program.
- **Best_Of_4**: Runtime inference that samples four Candidate_Programs and selects the highest-ranked valid candidate using a fixed recorded selection procedure.
- **Category_Allowlist**: The explicit set of hard-surface, mostly one-piece object categories permitted to use the Optional_Geometry_Backend.
- **Eligible_Object**: An isolated, sufficiently visible, hard-surface, mostly one-piece SceneObject in the Category_Allowlist.
- **Excluded_Object**: An object or scene element outside the Optional_Geometry_Backend scope.
- **Evaluation_Record**: The immutable inputs, configuration, model identity, seeds, candidates, artifacts, metrics, violations, decisions, and provenance for one evaluated Benchmark_Pair.
- **Phase_1**: The inference-only external-sidecar benchmark using an unchanged Runtime_Model_Artifact and no production application dependencies.
- **Phase_1_Gate**: The mandatory clean-image quality, conversion, dimensional, security, and determinism thresholds for entry to Phase_2.
- **Phase_2**: The conditional tiny self-owned GIFT_Inspired_Adaptation evaluated against an unchanged baseline.
- **Phase_2_Gate**: The mandatory held-out relative improvement threshold for entry to Phase_3.
- **Phase_3**: The conditional reversible manual or sidecar World-stage integration spike.
- **Warehouse**: Reusable inventory whose approved assets may compound across future worlds.
- **Quarantine**: Experiment-only storage that prevents an artifact from entering the Warehouse or future World generation.
- **Fallback_Result**: The Existing_Generator GLB returned when the Optional_Geometry_Backend is disabled, ineligible, rejected, unavailable, or unsuccessful.
- **Sandbox_Violation**: Any denied import, network attempt, unauthorized read or write, limit exceedance, child-process violation, persistence attempt, or contamination outside disposable outputs.
- **Deterministic_Build**: Rebuilding fixed accepted CadQuery code with the same approved toolchain and configuration produces identical canonical solid and GLB hashes.
- **Canon_Like_Degradation**: The difference between Clean_Image and Canon_Like_Image results for the same metric and inference strategy.
- **Progression_Decision**: A recorded `pass`, `hold`, or `stop` outcome for a phase gate.
- **Validation_Harness**: The research test system that calculates metrics, evaluates correctness properties, and produces phase evidence.
- **Canon_Like_Collapse**: A Canon_Like_Image result with Executable_Valid_Solid_Rate below 70%, median Normalized_Aligned_IoU more than 0.20 below the corresponding Clean_Image median, or median Post_Scale_Dimension_Error above 10%.
- **Approved_Component**: A source dependency, model artifact, weight set, or dataset artifact whose intended experimental use has documented internal approval and verified license terms.

## Explicit Non-Goals

- Replacing or changing Text, Plan, Blockout, Canon generation, floor plans, room shells, full-room reconstruction, scene layout, object placement, or SceneObject authority.
- Generating or changing transforms, materials, textures, physics, collisions, lighting intent, game behavior, real-mode wiring, scoring, doors, joints, or articulated behavior.
- Treating GIFT as a runtime image-to-mesh converter or claiming reproduction of the published GIFT study.
- Shipping or redistributing unconfirmed model weights, training artifacts, or GenCAD-derived artifacts.
- Adding a public toggle, page, route, interface control, or other user-visible interface change.
- Replacing normal current asset generation or adding Phase_1 dependencies to the production application.

## Requirements

### Requirement 1: Preserve Pipeline Authorities

**User Story:** As a product owner, I want experimental geometry generation constrained to one object mesh at the World stage, so that the approved design and runtime contracts remain authoritative.

#### Acceptance Criteria

1. THE Experiment SHALL limit each Optional_Geometry_Backend replacement operation to exactly one SceneObject.
2. THE World_Pipeline SHALL retain Text, Plan, and Blockout as architectural and placement authority.
3. THE World_Pipeline SHALL retain the approved Canon as visual and art-direction authority.
4. THE World_Pipeline SHALL retain SceneObject as the runtime contract for dimensions, transforms, materials, physics, and behavior.
5. WHEN the Optional_Geometry_Backend evaluates a SceneObject, THE Experiment SHALL preserve the input SceneObject without mutation.
6. WHEN the World_Assembler receives a Normalized_GLB, THE World_Assembler SHALL apply the original SceneObject transform, material, physics, lighting relationships, game behavior, real-mode wiring, and scoring relationships.
7. THE Experiment SHALL retain existing floor-plan, room-shell, door, window, light, and scene-layout generation paths.

### Requirement 2: Restrict Per-Object Eligibility

**User Story:** As a research lead, I want the experiment restricted to object classes compatible with one-piece CAD reconstruction, so that results measure the proposed backend rather than unsupported reconstruction problems.

#### Acceptance Criteria

1. THE Category_Allowlist SHALL contain only isolated, hard-surface, mostly one-piece categories.
2. WHEN the Experiment defines the initial Category_Allowlist, THE Experiment SHALL consider shades, vessels, pedestals, brackets, and simple fixtures as candidate categories.
3. WHEN a SceneObject is outside the Category_Allowlist, THE Experiment_Coordinator SHALL classify the SceneObject as an Excluded_Object.
4. WHEN a SceneObject represents upholstered furniture, organic furniture, an articulated object, an assembly, a door, a joint, a material, or a texture, THE Experiment_Coordinator SHALL classify the SceneObject as an Excluded_Object.
5. WHEN an isolated object image is heavily occluded or lacks sufficient visible silhouette for the documented eligibility rubric, THE Experiment_Coordinator SHALL classify the SceneObject as an Excluded_Object.
6. WHEN an Excluded_Object reaches asset generation, THE Experiment_Coordinator SHALL select the Existing_Generator.
7. THE Experiment SHALL classify floor plans, room shells, full-room reconstruction, and scene layout as outside the Optional_Geometry_Backend scope.
8. WHEN object eligibility is evaluated, THE Evaluation_Record SHALL contain the category, rubric results, evidence image, and eligibility decision.

### Requirement 3: Separate Offline Improvement from Runtime Inference

**User Story:** As a model engineer, I want offline preparation separated from runtime inference, so that the experiment evaluates a deployable image-to-CAD artifact accurately.

#### Acceptance Criteria

1. THE Experiment SHALL represent GIFT as an offline model-improvement and data-augmentation method.
2. THE Experiment SHALL represent Runtime_Model_Artifact inference as the runtime operation.
3. WHEN GIFT_Inspired_Adaptation samples training candidates, THE offline preparation workflow SHALL sample and execute between four and eight Candidate_Programs per training example.
4. WHEN offline candidate geometry is verified, THE offline preparation workflow SHALL compare generated geometry with self-owned ground-truth CAD by Normalized_Aligned_IoU.
5. WHEN Normalized_Aligned_IoU is calculated, THE Validation_Harness SHALL require a value from 0 through 1 inclusive.
6. IF an alignment or normalization calculation produces a value outside the inclusive 0-through-1 range, THEN THE Validation_Harness SHALL reject the value as an invalid IoU calculation.
7. WHERE offline augmentation is enabled, THE offline preparation workflow SHALL limit augmentation inputs to approved high-fidelity alternatives and rendered near-misses derived from self-owned Benchmark_Pairs.
8. THE runtime inference workflow SHALL operate without access to training labels or owned ground-truth CAD.
9. THE Experiment SHALL record that the referenced method studied individual mechanical CAD solids with CadQuery and OCCT, required substantial compute, and reported lower real-world or out-of-distribution performance than in-distribution performance.
10. WHILE GIFT_Inspired_Adaptation is inactive, THE runtime inference workflow SHALL permit Single_Shot and Best_Of_4 candidate sampling for evaluation.

### Requirement 4: Enforce Component and Data Licensing

**User Story:** As a compliance owner, I want every model, dataset, and CAD dependency approved before use or distribution, so that research results do not create unlicensed product assets.

#### Acceptance Criteria

1. THE Experiment SHALL record the absence of a verified official GIFT implementation or checkpoint at requirements approval time.
2. THE Experiment SHALL record Apache-2.0 as the inspected CAD-Coder source license without extending that conclusion to associated weights or datasets.
3. THE Experiment SHALL classify CAD-Coder weights and GenCAD-derived dataset artifacts as unconfirmed until explicit applicable license terms are verified.
4. THE Experiment SHALL limit internal research data to self-owned Benchmark_Pairs.
5. THE Experiment SHALL limit internal research components to Approved_Components.
6. IF a model weight, training artifact, or dataset artifact has unconfirmed license terms, THEN THE Experiment_Coordinator SHALL block shipping and redistribution of that artifact and derivatives whose distribution rights depend on that artifact.
7. THE Experiment SHALL record CadQuery's Apache-2.0 license and a completed OCCT obligations review before Phase_3 begins.
8. IF any required license or OCCT obligation remains unresolved, THEN THE Experiment_Coordinator SHALL assign a `stop` Progression_Decision.
9. WHEN a component or artifact enters the Experiment, THE Evaluation_Record SHALL identify source, version, cryptographic hash, owner, license evidence, approval status, and permitted use.

### Requirement 5: Establish the Phase 1 Benchmark

**User Story:** As a research lead, I want a small owned benchmark with training-like and Canon-like views, so that inference feasibility and domain degradation are measured without training-data risk.

#### Acceptance Criteria

1. THE Phase_1 Benchmark_Set SHALL contain between 20 and 30 self-owned hand-authored Benchmark_Pairs.
2. THE Benchmark_Set SHALL contain exactly one Clean_Image and one Canon_Like_Image at 448×448 pixels for each Benchmark_Pair.
3. THE Benchmark_Set SHALL pair each image pair with the same owned ground-truth CadQuery solid and corresponding SceneObject description.
4. WHEN a Benchmark_Pair is authored, THE Evaluation_Record SHALL identify object category, CadQuery source hash, ground-truth solid hash, image-render settings, and SceneObject hash.
5. THE Phase_1 execution environment SHALL run as an external inference-only sidecar.
6. THE Phase_1 execution environment SHALL add zero dependencies to the production application.
7. THE Phase_1 evaluation SHALL execute Single_Shot and Best_Of_4 for every Clean_Image and Canon_Like_Image.
8. WHEN benchmark composition is finalized, THE Experiment_Coordinator SHALL freeze Benchmark_Pair identities before Phase_1 results are calculated.

### Requirement 6: Generate Per-Object CAD Candidates

**User Story:** As a World asset researcher, I want image-conditioned CAD candidates tied to the SceneObject contract, so that generated geometry can be assessed as an optional object backend.

#### Acceptance Criteria

1. WHEN an Eligible_Object is evaluated, THE Optional_Geometry_Backend SHALL consume one isolated object image and the corresponding SceneObject description.
2. WHEN Single_Shot is selected, THE Optional_Geometry_Backend SHALL sample exactly one Candidate_Program.
3. WHEN Best_Of_4 is selected, THE Optional_Geometry_Backend SHALL sample exactly four Candidate_Programs.
4. THE Optional_Geometry_Backend SHALL permit a Candidate_Program to produce an isolated-solid variant, a fused one-piece variant, or both variants.
5. WHEN one Candidate_Program produces both variants, THE Optional_Geometry_Backend SHALL validate both variants and select at most one variant for acceptance.
6. WHEN a Candidate_Program is sampled, THE Evaluation_Record SHALL store model identity, model hash, inference configuration, sampling seed, candidate order, source hash, and source text.
7. WHEN Best_Of_4 selects a candidate, THE Optional_Geometry_Backend SHALL use a fixed versioned ranking procedure that considers only Sandbox and geometry-validation evidence available at runtime.
8. IF every Candidate_Program in a Candidate_Set is rejected, THEN THE Experiment_Coordinator SHALL produce a Fallback_Result.

### Requirement 7: Sandbox Generated Python

**User Story:** As a security owner, I want generated Python executed with deny-by-default isolation, so that model output cannot affect the application, host, network, or persistent data.

#### Acceptance Criteria

1. WHEN a Candidate_Program is executed, THE Sandbox SHALL execute the Candidate_Program outside the application process.
2. THE Sandbox SHALL deny all network access.
3. WHERE an Approved_Component requires network retrieval, THE offline preparation environment SHALL permit approved network access before Candidate_Program execution begins.
4. THE Sandbox SHALL mount input artifacts as read-only data.
5. THE Sandbox SHALL restrict writes to a disposable output location.
6. THE Sandbox SHALL discard the disposable execution environment after each Candidate_Program attempt.
7. THE Sandbox SHALL permit only version-pinned allowlisted imports required for CadQuery generation and artifact export.
8. THE Sandbox SHALL enforce the Run_Limit_Profile for CPU, RAM, wall-clock time, child processes, output bytes, and output file count.
9. THE Run_Limit_Profile SHALL contain a finite numeric limit for every controlled resource before Candidate_Program execution begins.
10. IF a Candidate_Program requests a denied capability or exceeds a Run_Limit_Profile value, THEN THE Sandbox SHALL terminate the Candidate_Program and record a Sandbox_Violation.
11. IF a Sandbox_Violation occurs, THEN THE Experiment_Coordinator SHALL reject every artifact from the violating execution and produce a Fallback_Result when World-stage output is required.
12. WHEN a Sandbox execution ends, THE Validation_Harness SHALL verify that no unexpected file, process, network activity, or persistent state exists outside the disposable output location.
13. THE production application process SHALL execute zero generated Python instructions.

### Requirement 8: Validate Solid and Mesh Artifacts

**User Story:** As a geometry engineer, I want deterministic validation before conversion or assembly, so that malformed or hostile geometry cannot enter a World.

#### Acceptance Criteria

1. WHEN a Candidate_Program finishes, THE Validation_Harness SHALL verify successful execution before inspecting geometry.
2. WHEN a CadQuery result is produced, THE Validation_Harness SHALL verify that the result is nonempty, finite, and convertible to one accepted solid.
3. WHEN a solid is evaluated, THE Validation_Harness SHALL verify topology validity, finite bounds, positive volume, and compliance with recorded complexity limits.
4. WHEN a solid passes solid validation, THE Validation_Harness SHALL export the solid to STEP.
5. WHEN a STEP artifact is exported, THE Validation_Harness SHALL reopen and validate the STEP artifact before GLB conversion.
6. WHEN a STEP artifact passes validation, THE Validation_Harness SHALL tessellate the STEP artifact to GLB.
7. WHEN a GLB is produced, THE Validation_Harness SHALL verify parseability, finite vertices, nonempty faces, bounds, manifoldness status, triangle count, and absence of external resource references.
8. IF any required artifact validation fails, THEN THE Experiment_Coordinator SHALL reject the candidate and retain the candidate's failure reason.
9. IF the candidate-rejection mechanism fails, THEN THE Experiment_Coordinator SHALL halt candidate processing until rejection capability is restored.
10. THE Experiment_Coordinator SHALL prevent candidate acceptance when any required execution, solid, STEP, GLB, normalization, security, or deterministic validation has failed.
11. WHEN a candidate is accepted, THE Evaluation_Record SHALL contain hashes for Candidate_Program source, canonical solid, STEP, raw GLB, and Normalized_GLB.
12. THE Validation_Harness SHALL apply the same versioned validation procedure to Single_Shot and Best_Of_4 candidates.

### Requirement 9: Normalize and Hand Off Accepted Geometry

**User Story:** As a World assembler owner, I want accepted geometry normalized to the existing runtime contract, so that experimental shape detail cannot override layout or behavior.

#### Acceptance Criteria

1. WHEN a GLB passes artifact validation, THE Optional_Geometry_Backend SHALL scale the GLB bounds to the Authoritative_Dimensions on each axis.
2. WHEN geometry normalization is applied, THE Optional_Geometry_Backend SHALL retain the object-local origin and axis convention defined by the versioned normalization procedure.
3. THE Normalized_GLB SHALL contain no baked SceneObject position, rotation, material, physics, lighting, game behavior, real-mode wiring, or scoring change.
4. WHEN Post_Scale_Dimension_Error exceeds the active phase threshold, THE Experiment_Coordinator SHALL reject the Normalized_GLB.
5. WHEN a Normalized_GLB is accepted, THE Experiment_Coordinator SHALL associate the GLB path with the original SceneObject identifier.
6. WHEN a Normalized_GLB is handed to the World_Assembler, THE Experiment_Coordinator SHALL hand off the original SceneGraph and the substituted path for only the accepted SceneObject.
7. IF normalization or handoff fails, THEN THE Experiment_Coordinator SHALL provide the Existing_Generator path for the affected SceneObject.

### Requirement 10: Measure Phase 1 Outcomes

**User Story:** As a research decision-maker, I want complete metrics separated by image condition and inference strategy, so that progression is based on reproducible evidence rather than selected examples.

#### Acceptance Criteria

1. THE Validation_Harness SHALL calculate Executable_Code_Rate for each image condition and inference strategy.
2. THE Validation_Harness SHALL calculate Valid_Solid_Rate and Executable_Valid_Solid_Rate for each image condition and inference strategy.
3. THE Validation_Harness SHALL calculate GLB_Conversion_Rate for each image condition and inference strategy.
4. THE Validation_Harness SHALL calculate Normalized_Aligned_IoU against owned ground-truth CAD for each accepted candidate.
5. THE Validation_Harness SHALL calculate Post_Scale_Dimension_Error for each converted GLB.
6. THE Validation_Harness SHALL record manifoldness status and triangle count for each converted GLB.
7. THE Validation_Harness SHALL record candidate-generation latency, Sandbox execution latency, conversion latency, end-to-end latency, and peak VRAM for each attempt.
8. THE Validation_Harness SHALL record Sandbox_Violation type and count for each attempt.
9. WHEN deterministic repeatability is evaluated, THE Validation_Harness SHALL run each fixed accepted Candidate_Program three times with the same approved toolchain and configuration.
10. WHEN inference repeatability is evaluated, THE Validation_Harness SHALL run three repetitions with identical model identity, configuration, input, and fixed seed.
11. THE Validation_Harness SHALL report Canon_Like_Degradation independently for Single_Shot and Best_Of_4.
12. THE Validation_Harness SHALL report aggregate count, denominator, median, and percentile statistics without omitting failed attempts.

### Requirement 11: Enforce the Phase 1 Gate

**User Story:** As a research sponsor, I want explicit progression thresholds, so that adaptation work begins only after inference demonstrates basic feasibility and safety.

#### Acceptance Criteria

1. THE Phase_1_Gate SHALL use aggregate Best_Of_4 Clean_Image results as the progression result and retain Single_Shot results as separately reported evidence.
2. THE Phase_1_Gate SHALL require an Executable_Valid_Solid_Rate of at least 95%.
3. THE Phase_1_Gate SHALL require a GLB_Conversion_Rate of at least 90%.
4. THE Phase_1_Gate SHALL require a median Normalized_Aligned_IoU of at least 0.75.
5. THE Phase_1_Gate SHALL require a median Post_Scale_Dimension_Error of at most 5%.
6. THE Phase_1_Gate SHALL require zero Sandbox_Violations and zero detected host contamination events.
7. THE Phase_1_Gate SHALL require Deterministic_Build success for every accepted candidate used in aggregate metrics.
8. WHEN unrounded metric values definitively satisfy every inclusive Phase_1_Gate threshold, THE Experiment_Coordinator SHALL record a `pass` Progression_Decision for Phase_1.
9. IF measurement precision leaves any Phase_1_Gate threshold outcome ambiguous, THEN THE Experiment_Coordinator SHALL withhold a `pass` Progression_Decision.
10. IF any Phase_1_Gate threshold fails, THEN THE Experiment_Coordinator SHALL override any previously computed `pass`, block Phase_2, and record a `hold` or `stop` Progression_Decision with failed thresholds.
11. IF Canon_Like_Collapse occurs, THEN THE Experiment_Coordinator SHALL record a `stop` Progression_Decision regardless of Clean_Image results.

### Requirement 12: Conduct Conditional Phase 2 Adaptation

**User Story:** As a model engineer, I want a controlled tiny adaptation compared with an unchanged baseline, so that any improvement is attributable and does not overstate research reproduction.

#### Acceptance Criteria

1. WHILE Phase_1 lacks a `pass` Progression_Decision, THE Experiment_Coordinator SHALL keep Phase_2 disabled.
2. WHEN Phase_1 passes, THE Experiment_Coordinator SHALL permit one tiny self-owned GIFT_Inspired_Adaptation.
3. THE Phase_2 adaptation SHALL use only self-owned training examples and Approved_Components.
4. WHERE parameter-efficient adaptation is selected, THE Phase_2 adaptation SHALL use an approved LoRA configuration recorded in the Evaluation_Record.
5. THE Phase_2 evaluation SHALL reserve a Held_Out_Set excluded from all adaptation examples and candidate-selection tuning.
6. WHEN adapted and baseline artifacts are compared, THE Validation_Harness SHALL use identical Held_Out_Set inputs, candidate counts, seeds, Sandbox limits, validation procedures, and metric formulas.
7. THE Phase_2 baseline SHALL remain byte-identical to the Runtime_Model_Artifact evaluated before adaptation.
8. THE Phase_2_Gate SHALL require at least a 10% relative reduction in median IoU error, defined as `1 - median Normalized_Aligned_IoU`, when median IoU error is eligible for relative comparison.
9. THE Phase_2_Gate SHALL require at least a 10% relative reduction in Candidate_Program compile-failure rate when compile-failure rate is eligible for relative comparison.
10. IF a baseline error value equals zero, THEN THE Validation_Harness SHALL classify that error metric as ineligible for relative-reduction qualification.
11. WHERE exactly one Phase_2 error metric is eligible for relative comparison, THE Phase_2_Gate SHALL require the eligible metric to achieve at least a 10% relative reduction.
12. WHEN every eligible Phase_2 error metric passes without regression of Phase_1 security and conversion gates, THE Experiment_Coordinator SHALL record a `pass` Progression_Decision for Phase_2.
13. IF any eligible Phase_2 error metric fails or any Phase_1 security or conversion gate regresses, THEN THE Experiment_Coordinator SHALL block Phase_3.
14. THE Experiment SHALL describe Phase_2 results as GIFT-inspired adaptation results rather than reproduction of the published study.

### Requirement 13: Conduct Conditional Phase 3 World Integration

**User Story:** As a World pipeline owner, I want a reversible sidecar integration behind a strict allowlist, so that realistic assembly behavior can be tested without changing production defaults.

#### Acceptance Criteria

1. WHILE Phase_1 or Phase_2 lacks a `pass` Progression_Decision, THE Experiment_Coordinator SHALL keep Phase_3 disabled.
2. WHILE any required component or artifact license remains unresolved, THE Experiment_Coordinator SHALL keep Phase_3 disabled.
3. WHEN prior gates and license reviews pass, THE Experiment_Coordinator SHALL permit a reversible manual or external-sidecar World-stage spike.
4. THE Phase_3 Optional_Geometry_Backend SHALL remain disabled by default.
5. THE Phase_3 Optional_Geometry_Backend SHALL evaluate only SceneObject records accepted by the strict Category_Allowlist.
6. WHEN the Optional_Geometry_Backend is disabled, unavailable, ineligible, rejected, timed out, or invalid, THE Experiment_Coordinator SHALL select the Existing_Generator automatically.
7. WHEN the Optional_Geometry_Backend returns an accepted Normalized_GLB, THE World_Assembler SHALL preserve every original SceneObject transform, material, physics, lighting intent, game behavior, real-mode wiring, and scoring authority.
8. IF any original SceneObject transform is lost or changed, THEN THE Experiment_Coordinator SHALL reject the experimental GLB and select the Existing_Generator.
9. WHEN a Phase_3 World is assembled, THE Validation_Harness SHALL inspect the generated object in a disposable Godot scene.
10. WHEN disposable Godot inspection runs, THE Validation_Harness SHALL verify geometry loading, bounds, transforms, collision and physics compatibility, material and lighting compatibility, and applicable game-mode behavior.
11. IF disposable Godot inspection fails, THEN THE Experiment_Coordinator SHALL reject the experimental GLB and rebuild the affected object with the Existing_Generator.
12. THE Phase_3 spike SHALL retain the existing `SceneObject.id` to GLB-path handoff contract.
13. THE Experiment SHALL retain current user-visible pages and interfaces without a new toggle or interface version.

### Requirement 14: Protect Warehouse Compounding

**User Story:** As a warehouse owner, I want experimental assets quarantined until every reuse gate passes, so that rejected or uncertain geometry cannot degrade future worlds.

#### Acceptance Criteria

1. WHEN an asset is generated by the Optional_Geometry_Backend, THE Experiment_Coordinator SHALL place the asset in Quarantine.
2. WHILE an asset remains in Quarantine, THE Warehouse SHALL exclude the asset from reusable inventory and future World generation.
3. THE Warehouse admission record SHALL require verified source provenance and component licenses.
4. THE Warehouse admission record SHALL require passing geometric quality and Deterministic_Build evidence.
5. THE Warehouse admission record SHALL require passing physics and collision evidence.
6. THE Warehouse admission record SHALL require passing lighting and material compatibility evidence.
7. THE Warehouse admission record SHALL require passing applicable real-mode and game-mode behavior evidence.
8. THE Warehouse admission record SHALL require explicit human approval for the specific asset and version.
9. WHEN every Warehouse admission gate passes, THE Warehouse SHALL admit only the approved hashed asset version to reusable inventory.
10. IF an artifact is rejected, uncertain, superseded, or missing gate evidence, THEN THE Warehouse SHALL retain the artifact outside reusable inventory.

### Requirement 15: Apply Stop Conditions and Resource Budgets

**User Story:** As a research sponsor, I want explicit stop conditions, so that the spike ends before unsafe, impractical, or low-value work reaches production.

#### Acceptance Criteria

1. WHEN a phase begins, THE Experiment_Coordinator SHALL record finite latency and peak-VRAM budgets before collecting phase results.
2. IF median end-to-end latency or peak VRAM exceeds a recorded phase budget, THEN THE Experiment_Coordinator SHALL record a `stop` Progression_Decision for impractical resource use.
3. IF Canon_Like_Collapse occurs, THEN THE Experiment_Coordinator SHALL stop progression.
4. IF more than 20% of technically valid held-out outputs fail the versioned human review rubric because one-piece approximation is unsuitable, THEN THE Experiment_Coordinator SHALL stop progression.
5. IF the Sandbox cannot enforce every Run_Limit_Profile control or detect contamination, THEN THE Experiment_Coordinator SHALL stop progression.
6. IF a required license remains unresolved, THEN THE Experiment_Coordinator SHALL stop progression before Phase_3 or distribution.
7. IF any accepted candidate fails Deterministic_Build verification, THEN THE Experiment_Coordinator SHALL stop progression until the nondeterminism is resolved and the phase is rerun.
8. IF generated geometry fails required solid, mesh, physics, collision, or applicable game-mode checks, THEN THE Experiment_Coordinator SHALL reject the affected output.
9. IF the Experiment cannot preserve automatic Existing_Generator fallback for every SceneObject, THEN THE Experiment_Coordinator SHALL stop Phase_3.
10. IF experimental integration changes any earlier World_Pipeline stage or authority contract, THEN THE Experiment_Coordinator SHALL stop Phase_3 and restore the pre-spike path.

### Requirement 16: Verify Correctness Properties

**User Story:** As a test engineer, I want high-value properties checked across generated inputs and failure modes, so that the experiment validates invariants rather than only curated examples.

#### Acceptance Criteria

1. THE Validation_Harness SHALL verify the Authority_Preservation invariant by comparing every non-mesh SceneObject and SceneGraph field before and after optional-backend evaluation.
2. THE Validation_Harness SHALL verify that every accepted Normalized_GLB has Post_Scale_Dimension_Error at or below the active phase threshold on every axis.
3. THE Validation_Harness SHALL verify normalization idempotence by confirming that normalizing an already Normalized_GLB changes no axis bound beyond 0.1%.
4. THE Validation_Harness SHALL verify fallback totality by confirming that every evaluated SceneObject produces either one accepted experimental GLB path or one Existing_Generator GLB path.
5. THE Validation_Harness SHALL verify rejection isolation by confirming that rejected candidate hashes appear in neither assembled World asset paths nor Warehouse inventory.
6. THE Validation_Harness SHALL verify Best_Of_4 selection dominance by confirming that the selected valid candidate's versioned ranking score is at least the score of Candidate_Program one when Candidate_Program one is valid.
7. THE Validation_Harness SHALL verify Deterministic_Build by comparing canonical solid and GLB hashes across three rebuilds of fixed accepted CadQuery code.
8. THE Validation_Harness SHALL verify Sandbox error handling with generated denied imports, network attempts, unauthorized writes, child-process attempts, time-limit exceedances, memory-limit exceedances, and malformed outputs.
9. THE Validation_Harness SHALL verify category exclusion with representative upholstered, organic, articulated, assembly, door, joint, material, texture, occluded, room-shell, full-room, and scene-layout inputs.
10. THE Validation_Harness SHALL verify phase-gate monotonicity by confirming that Phase_2 and Phase_3 remain disabled until every prerequisite Progression_Decision and license gate passes.
11. THE Validation_Harness SHALL verify warehouse quarantine by confirming that repeated processing of a rejected or uncertain artifact cannot make the artifact eligible for reuse without new complete gate evidence and human approval.
12. WHEN a correctness property fails, THE Experiment_Coordinator SHALL record the minimal reproducible input, expected result, actual result, affected phase, and Progression_Decision.

### Requirement 17: Produce Auditable Experiment Evidence

**User Story:** As a decision-maker, I want complete auditable results and limitations, so that the team can decide whether to stop, adapt, integrate, or revisit the experiment.

#### Acceptance Criteria

1. THE Experiment SHALL produce an Evaluation_Record for every Benchmark_Pair, image condition, inference strategy, and phase.
2. THE Evaluation_Record SHALL retain failed candidates and rejected outputs as quarantined evidence without admitting the outputs to the Warehouse.
3. WHEN a phase completes, THE Experiment_Coordinator SHALL produce a phase report containing metric definitions, raw denominators, aggregate results, resource use, violations, exclusions, gate outcomes, and stop-condition outcomes.
4. WHEN Phase_1 completes, THE phase report SHALL compare Single_Shot with Best_Of_4 and Clean_Image with Canon_Like_Image.
5. WHEN Phase_2 completes, THE phase report SHALL compare the unchanged baseline with the adapted artifact on the Held_Out_Set.
6. WHEN Phase_3 completes, THE phase report SHALL list every experimental substitution, fallback, Godot inspection result, preserved SceneObject field hash, and warehouse disposition.
7. THE Experiment SHALL identify limitations arising from the small Benchmark_Set, individual-solid focus, compute requirements, and expected real-world or out-of-distribution degradation.
8. THE Experiment SHALL make no production-readiness claim from a phase report that lacks all required gate evidence.
9. WHEN the Experiment ends, THE Experiment_Coordinator SHALL record one final recommendation of `stop`, `continue research`, or `propose separate production specification`.
