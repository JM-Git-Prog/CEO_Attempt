# Requirements Document

## Introduction

This specification defines an LLM-directed world-building architecture that uses UPBGE as a hidden scene compiler and optional real-time runtime while preserving an engine-neutral source of truth. The LLM expresses intent through typed semantic commands; deterministic application code owns geometry, validation, physics, execution, persistence, and export. The same approved world contract can produce an UPBGE `.blend` and playable package, Godot output, and GLB assets for Three.js without exposing engine complexity in the product interface.

The feature replaces neither the approved Plan nor the immutable Camera_Contract. It integrates the existing Blender prototype only after correcting its opening, physics, provenance, portability, and pipeline gaps. Existing released interfaces and workflow profiles remain behaviorally stable. Any user-visible release requires a new query version and a clean zero-state qualification pass.

## Glossary

- **World_Contract**: Engine-neutral, versioned description of room geometry, instances, transforms, materials, lights, cameras, physics intent, interactions, and export policy.
- **Semantic_Command**: Allowlisted typed operation proposed by the LLM against a World_Contract; never arbitrary executable code.
- **Command_Validator**: Deterministic component that validates authorization, schema, references, units, limits, and invariants before applying a Semantic_Command.
- **Scene_Compiler**: Deterministic sidecar that translates an approved World_Contract into engine artifacts through UPBGE's Blender-compatible Python API.
- **UPBGE_Sidecar**: Isolated subprocess running a pinned UPBGE executable with bounded inputs, outputs, resources, and environment.
- **Runtime_Adapter**: Deterministic generator for engine-specific runtime behavior such as movement, collision, doors, grabbing, and interactions.
- **Export_Adapter**: Generator that converts one World_Contract into a target-specific package without changing world semantics.
- **Engine_Artifact**: `.blend`, GLB, runtime package, render, manifest, or target project created by an Export_Adapter.
- **Compiler_Manifest**: Immutable record binding inputs, versions, profile, camera, command log, outputs, hashes, diagnostics, and validation results.
- **Structural_Parity_Report**: Machine-checkable comparison of identities, counts, dimensions, transforms, openings, camera, and relationships across artifacts.
- **Runtime_Smoke_Report**: Result of loading a package, spawning the player, moving, colliding, and exercising required interactions.
- **LLM_Director**: Model that interprets user intent and proposes semantic changes without controlling simulation frames or executing code.
- **Deterministic_Authority**: Application component that owns exact transforms, collisions, simulation, export, and artifact acceptance.
- **Retained_Interface**: Previously released query-versioned UI whose behavior remains stable.
- **Workflow_Profile**: Immutable version-specific generation and compilation contract persisted with a session.
- **Graceful_Fallback**: Explicit continuation through the existing Godot assembler or another approved adapter when UPBGE is unavailable or compilation fails.

## Requirements

### Requirement 1: Preserve an Engine-Neutral Source of Truth

**User Story:** As a product owner, I want one engine-neutral world definition, so that UPBGE accelerates creation without locking the product to one runtime.

#### Acceptance Criteria

1. THE World_Contract SHALL represent stable object identities, room geometry, openings, transforms, dimensions, materials, lights, cameras, physics intent, interactions, and export targets without UPBGE-specific types.
2. WHEN a Plan, Scene_Graph, or Camera_Contract is approved, THE World_Contract SHALL preserve its authoritative metric values and identifiers.
3. THE Scene_Compiler SHALL treat the World_Contract as read-only input.
4. IF an Export_Adapter cannot represent a World_Contract feature, THEN it SHALL return a structured unsupported-feature result rather than silently changing semantics.
5. WHEN identical canonical World_Contract bytes and compiler configuration are supplied, THE compilation plan SHALL be identical.

### Requirement 2: Constrain LLM Direction to Typed Commands

**User Story:** As a system operator, I want the LLM to direct creation safely, so that natural-language flexibility cannot execute arbitrary code or corrupt geometry.

#### Acceptance Criteria

1. THE LLM_Director SHALL output only versioned Semantic_Commands defined by an allowlisted schema.
2. THE LLM_Director SHALL express spatial intent through explicit relationships such as `centered`, `against_wall`, `adjacent_to`, `south_of`, `around`, `above`, `facing`, and `near_corner`.
3. THE LLM_Director SHALL NOT emit Python, shell commands, filesystem paths, engine operators, or per-frame control instructions.
4. WHEN a Semantic_Command references an object, THE Command_Validator SHALL require an existing stable identifier or an explicit create operation.
5. IF a Semantic_Command is invalid, unauthorized, ambiguous, cyclic, or outside configured limits, THEN THE Command_Validator SHALL reject it without mutating the World_Contract.
6. WHEN accepted commands are applied, THE system SHALL record their canonical form, model identity, source prompt hash, and resulting World_Contract hash.

### Requirement 3: Resolve Geometry Deterministically

**User Story:** As a world designer, I want exact geometry resolved by deterministic code, so that LLM variability cannot create overlaps or cross-stage drift.

#### Acceptance Criteria

1. THE Deterministic_Authority SHALL resolve Semantic_Command relationships into finite metric transforms before any engine invocation.
2. WHEN constraints are resolved, THE Deterministic_Authority SHALL enforce rotation-aware room bounds, opening keep-clear volumes, object clearance, mount height, and camera occupancy.
3. IF all hard constraints cannot be satisfied, THEN compilation SHALL stop with identified unsatisfied constraints and SHALL NOT place objects at an overlapping fallback origin.
4. WHEN repeated objects share a parent relationship, THE Deterministic_Authority SHALL preserve exact count and distribute them according to the declared relation.
5. WHEN a floor, wall, or ceiling object is compiled, THE resulting transform SHALL preserve the World_Contract coordinate and mount semantics within configured numeric tolerance.

### Requirement 4: Discover and Isolate UPBGE

**User Story:** As an operator, I want UPBGE detected and executed predictably, so that the application can compile scenes without exposing engine setup to users.

#### Acceptance Criteria

1. THE UPBGE_Sidecar SHALL discover the executable from explicit configuration, approved installation locations, or PATH in that order.
2. WHEN an executable is discovered, THE UPBGE_Sidecar SHALL verify product identity, version, Blender API version, runtime capability, and required exporters before compilation.
3. THE UPBGE_Sidecar SHALL run outside the web and pipeline processes with read-only input, a unique writable output directory, bounded runtime, and no inherited secrets.
4. IF UPBGE is absent, incompatible, times out, or exits unsuccessfully, THEN the system SHALL return a structured failure and apply the configured Graceful_Fallback.
5. THE system SHALL NOT download, upgrade, or execute an unapproved UPBGE build automatically.

### Requirement 5: Compile Structurally Faithful Scenes

**User Story:** As a pipeline reviewer, I want the compiled scene to match the approved world exactly, so that the Blockout, Canon, and playable World retain one identity.

#### Acceptance Criteria

1. WHEN the Scene_Compiler creates a room shell, it SHALL create physical wall, floor, and ceiling geometry with actual door and window openings rather than opaque opening panels.
2. WHEN the Scene_Compiler creates an instance, it SHALL preserve stable ID, count, dimensions, transform, mount, category, and declared relationships.
3. WHEN the Scene_Compiler creates the Canon camera, it SHALL preserve Camera_Contract position, target, up direction, vertical field of view, aspect, near plane, far plane, and raster dimensions.
4. WHEN the Scene_Compiler creates physics, it SHALL derive collision shape and body mode from validated physics intent rather than object-name inference.
5. WHEN the Scene_Compiler creates a light, it SHALL create exactly one declared fixture representation and one associated light source unless the World_Contract explicitly specifies otherwise.
6. WHEN compilation completes, THE Structural_Parity_Report SHALL compare expected and compiled IDs, counts, transforms, dimensions, openings, camera, and relationships.
7. IF a required parity check exceeds tolerance, THEN the Engine_Artifact SHALL be rejected.

### Requirement 6: Provide a Playable UPBGE Runtime

**User Story:** As a user, I want the generated world to be immediately explorable, so that world creation results in an interactive experience rather than only a rendered model.

#### Acceptance Criteria

1. WHEN UPBGE runtime output is selected, THE Runtime_Adapter SHALL configure a player spawn, camera, movement, collision, gravity, and pause/exit behavior from versioned templates.
2. WHEN an approved interaction intent exists, THE Runtime_Adapter SHALL instantiate only an allowlisted interaction component with validated parameters.
3. THE LLM_Director SHALL NOT execute or schedule per-frame runtime logic.
4. WHEN the runtime starts, it SHALL load the compiled world without network access unless a separately approved feature explicitly requires it.
5. WHEN runtime smoke validation runs, THE Runtime_Smoke_Report SHALL record load success, player spawn, movement, collision, opening traversal, and required interaction results.
6. IF a mandatory runtime smoke check fails, THEN the playable Engine_Artifact SHALL be rejected while portable non-runtime artifacts MAY remain available if their own gates pass.

### Requirement 7: Preserve Multi-Engine Export

**User Story:** As a product owner, I want future runtime choice, so that using UPBGE now does not make Godot or Three.js export impossible later.

#### Acceptance Criteria

1. THE system SHALL retain the existing Godot Export_Adapter while introducing the UPBGE Export_Adapter.
2. WHEN GLB export is requested, THE Export_Adapter SHALL export meshes, materials, cameras, punctual lights, stable identifiers as extras, units, and axis metadata supported by the target contract.
3. THE system SHALL store gameplay and physics semantics in sidecar metadata when GLB cannot represent them portably.
4. WHEN Godot or Three.js output is requested, THE corresponding adapter SHALL consume the same World_Contract rather than reverse-engineering `.blend` output.
5. WHEN multiple target artifacts are generated, THE Structural_Parity_Report SHALL compare each artifact against the same World_Contract.
6. IF target-specific behavior has no equivalent, THEN the adapter SHALL mark it unsupported or use an explicitly documented target-specific implementation.

### Requirement 8: Enforce Execution and Content Safety

**User Story:** As a security owner, I want generated intent separated from executable code, so that an LLM-directed pipeline cannot compromise the host.

#### Acceptance Criteria

1. THE system SHALL prohibit direct execution of model-generated Python, shell, shader source, driver expressions, and file paths.
2. THE UPBGE_Sidecar SHALL accept only canonical World_Contract input and versioned first-party compiler scripts.
3. THE UPBGE_Sidecar SHALL restrict writes to its assigned output directory and SHALL reject traversal outside that directory.
4. THE compiler SHALL apply configurable limits for object count, polygon count, texture size, output bytes, CPU time, memory, and wall time.
5. IF input or output violates a security or resource limit, THEN compilation SHALL terminate and record the violated limit.
6. THE product SHALL disclose the use of bundled third-party runtime components and satisfy approved licensing and attribution obligations.

### Requirement 9: Record Reproducible Provenance

**User Story:** As a release owner, I want every compiled world reproducible and auditable, so that generated artifacts can be traced to exact inputs and tools.

#### Acceptance Criteria

1. BEFORE compilation, THE system SHALL write an immutable prepared Compiler_Manifest.
2. WHEN compilation terminates, THE system SHALL write an immutable completed, failed, timed-out, or rejected Compiler_Manifest.
3. THE Compiler_Manifest SHALL record session ID, interface version, Workflow_Profile, World_Contract version and hash, Plan revision, Camera_Contract ID, compiler script hash, UPBGE identity and versions, configuration, command-log hash, timings, diagnostics, and artifact metadata.
4. WHEN an Engine_Artifact is produced, THE Compiler_Manifest SHALL record its path, bytes, SHA-256 hash, media type, and target role.
5. WHEN a persisted session is restored, THE system SHALL reject profile or contract content that differs from the immutable registry identity.
6. Recompiling a historical session SHALL NOT overwrite its prior manifests or artifacts.

### Requirement 10: Gate Artifacts with Automated and Human QA

**User Story:** As a quality owner, I want structural, runtime, visual, and human checks, so that attractive but incorrect worlds cannot pass as successful.

#### Acceptance Criteria

1. BEFORE Canon generation advances, THE system SHALL verify Plan and Blockout structural validity under the selected Workflow_Profile.
2. AFTER Floor Plan, Blockout, and Canon are available, THE QA process SHALL evaluate Spatial Accuracy, Aesthetic Quality, Prompt Adherence, Artifacts and Glitches, Information Representation, Camera Perspective versus Blueprint, and Asset Fidelity.
3. WHEN local vision screening is used, THE system SHALL require `pass=true` and confidence of at least `0.8` for automatic acceptance.
4. IF local vision screening fails, is unavailable, or has confidence below `0.8`, THEN the artifact SHALL require explicit adjudication rather than automatic approval.
5. BEFORE a world artifact is accepted, THE system SHALL require a passing Structural_Parity_Report and applicable Runtime_Smoke_Report.
6. Human QA SHALL bind verdicts to artifact hashes, interface version, Workflow_Profile, plan revision, and Canon attempt, and SHALL support superseding earlier verdicts without deleting history.

### Requirement 11: Preserve Versioned Behavior and Fallbacks

**User Story:** As a maintainer, I want the integration introduced without rewriting history, so that existing sessions and released interfaces remain trustworthy.

#### Acceptance Criteria

1. THE implementation SHALL introduce UPBGE behavior through a new immutable Workflow_Profile and SHALL NOT mutate existing V9 or V10 profile documents.
2. IF user-visible controls or stage behavior change, THEN the implementation SHALL increment the query interface version, retain the preceding version, make the newest released version the default, and show version-switch links.
3. WHEN an older session is restored, THE pipeline SHALL use its persisted or historical Workflow_Profile and SHALL NOT route it through UPBGE unless that profile requires UPBGE.
4. WHEN UPBGE compilation fails and the profile permits fallback, THE pipeline SHALL use the declared adapter and record that fallback in provenance and the user-visible status.
5. THE system SHALL distinguish successful native UPBGE output, successful fallback output, partial export, and failure.
6. THE system SHALL reject unsupported future interface versions rather than silently normalizing them to an older version.

### Requirement 12: Qualify Release from a Fresh Zero-State Session

**User Story:** As a release owner, I want a complete clean run before release, so that the new architecture is proven from user intent to playable output.

#### Acceptance Criteria

1. BEFORE release, THE release process SHALL create a brand-new empty session and run the canonical prompt without restoring prior state.
2. THE release process SHALL inspect Brief, Plan, Blockout, Canon, World, Compare, Compiler_Manifest, Structural_Parity_Report, and Runtime_Smoke_Report as applicable.
3. IF any defect appears, THEN the release process SHALL record the defect, fix it, discard that session as release evidence, and restart with another empty session.
4. THE release process SHALL validate retained interfaces, relevant APIs, static JavaScript, Python diagnostics, compiler capability detection, GLB loading, UPBGE runtime startup, and Godot fallback.
5. THE release process SHALL prohibit release classification until one complete zero-state pass succeeds on the exact target commit.
6. THE release process SHALL record the clean-version URL, fresh session URL, exact canonical prompt, workflow profile, UPBGE version, artifact hashes, and commit hash.

### Requirement 13: Qualify Composition and Realism Deterministically

**User Story:** As a creative owner, I want every approved Canon to be completely framed and intentionally rendered as hyperrealistic or stylized-realistic, so that attractive output cannot hide missing geometry or drift from the requested visual mode.

#### Acceptance Criteria

1. BEFORE Camera_Contract approval, THE Composition_Sidecar SHALL evaluate all eight rotation-aware 3D bounds corners of every required Plan instance at the fixed raster, aspect, and vertical field of view.
2. THE Composition_Sidecar SHALL preserve the typed camera corner and field of view and MAY search only profile-bounded corner inset and target aim offsets without moving Plan geometry.
3. WHEN a candidate is accepted, every required instance SHALL be fully inside the configured safe-frame margin, and the sidecar SHALL emit immutable canonical candidate evidence with deterministic ordering, scores, per-instance projected bounds, and a stable hash.
4. IF no candidate satisfies full required-instance coverage, THEN Plan approval SHALL fail with structured clipped-instance evidence; the system SHALL NOT silently widen field of view, move geometry, or approve center-point-only coverage.
5. THE Plan and relationship solvers SHALL use one documented clearance contract: each instance contributes one half of its declared clearance to pairwise separation, matching strict Plan validation.
6. THE workflow SHALL represent appearance mode as typed `hyperrealistic` or `stylized_realistic` intent and SHALL build immutable mode-specific conditioning from approved appearance, material, lighting, and weather intent without changing geometry.
7. Visual QA SHALL judge realism quality against the selected appearance mode while deterministic structural and composition evidence remains authoritative.
8. THE Composition_Sidecar and realism conditioning path SHALL be isolated to the new workflow profile and SHALL NOT change retained V3–V10 behavior.

### Requirement 14: Continuously Qualify the Working Tree

**User Story:** As a release owner, I want one repeatable local qualification loop after every relevant code update, so regressions are detected with durable evidence before a candidate can be released.

#### Acceptance Criteria

1. THE Qualification_Loop SHALL run once on startup and in watch mode after debounced relevant source, test, spec, or static-file changes.
2. THE Qualification_Loop SHALL serialize iterations, never overlap runs, and coalesce any number of edits during an active iteration into exactly one pending rerun.
3. EACH iteration SHALL bind a source fingerprint to fast static checks, focused tests, full tests, and—unless tests-only—a brand-new zero-state V11 E2E session that is never restored or reused.
4. THE deterministic E2E adapter SHALL inspect Brief, Plan, Blockout, Canon, World, Compare when applicable, compiler manifests, UPBGE capability, declared Godot fallback, parity, runtime applicability, QA evidence, and recorded downloads.
5. THE Qualification_Loop SHALL write append-only JSONL events plus atomic canonical JSON and Markdown summaries containing commands, timings, exits, stage verdicts, source hashes, session identity, artifact hashes, and regression deltas.
6. IF source changes during an iteration, THEN that iteration SHALL be labeled stale and SHALL NOT qualify the newer source fingerprint.
7. THE tool SHALL use a recoverable single-process lock, sanitized subprocess environment, argv without `shell=True`, bounded timeouts, graceful cancellation, and Windows-safe filenames.
8. Optional local model analysis MAY summarize deterministic evidence but SHALL NOT override a failed gate or create release evidence.
9. THE tool SHALL support `--once`, `--watch`, `--tests-only`, `--e2e-only`, changed-file scoping, output-root selection, debounce, timeout, and bounded iteration count.
10. THE Qualification_Loop SHALL never stage, commit, delete diagnostic sessions, modify retained interfaces, or claim native UPBGE success without exact evidence.
