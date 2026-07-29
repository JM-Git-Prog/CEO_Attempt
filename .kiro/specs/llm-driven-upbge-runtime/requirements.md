# Requirements Document

## Introduction

This specification defines an LLM-directed world-building architecture that uses UPBGE as an optional high-quality scene compiler and runtime while preserving an engine-neutral WorldContract as the source of truth. The WorldContract is produced by EITHER the text-to-world path (LLM semantic commands → relationship solver) OR the photo-to-world path (V14 pipeline → depth/layout → WorldContract assembly). Both paths converge at the same WorldContract, which can then be compiled to UPBGE, exported to Godot, or rendered via Three.js.

The feature preserves existing released interfaces. Any user-visible release requires a new query version and a clean zero-state qualification pass.

### Relationship to V14 (Photo-to-Real-3D-World)

V14 produces a WorldContract from a photograph. This spec governs what happens AFTER the WorldContract exists:
- Optional UPBGE compilation for high-quality `.blend` + playable runtime
- Godot export adapter
- GLB export with metadata sidecar
- Structural parity validation between WorldContract and compiled output
- Runtime smoke testing for playable packages

The text-to-world path (LLM semantic commands) remains available for prompt-based world generation but is secondary to the photo path for now.

## Glossary

- **World_Contract**: Engine-neutral, versioned description of room geometry, instances, transforms, materials, lights, cameras, physics intent, interactions, and export policy. Produced by EITHER the text-to-world LLM path OR the V14 photo pipeline.
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
- **Graceful_Fallback**: Explicit continuation through the existing Godot assembler or another approved adapter when UPBGE is unavailable or compilation fails.

## Requirements

### Requirement 1: Preserve an Engine-Neutral Source of Truth

**User Story:** As a product owner, I want one engine-neutral world definition, so that UPBGE accelerates creation without locking the product to one runtime.

#### Acceptance Criteria

1. THE World_Contract SHALL represent stable object identities, room geometry, openings, transforms, dimensions, materials, lights, cameras, physics intent, interactions, and export targets without UPBGE-specific types.
2. WHEN a WorldContract is produced (by either V14 photo pipeline or LLM text path), THE World_Contract SHALL preserve its authoritative metric values and identifiers.
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

**User Story:** As a pipeline reviewer, I want the compiled scene to match the approved world exactly, so that exported artifacts retain structural identity with the source WorldContract.

#### Acceptance Criteria

1. WHEN the Scene_Compiler creates a room shell, it SHALL create physical wall, floor, and ceiling geometry with actual door and window openings rather than opaque opening panels.
2. WHEN the Scene_Compiler creates an instance, it SHALL preserve stable ID, count, dimensions, transform, mount, category, and declared relationships.
3. WHEN the Scene_Compiler creates the Canon camera, it SHALL preserve Camera_Contract position, target, up direction, vertical field of view, aspect, near plane, far plane, and raster dimensions.
4. WHEN the Scene_Compiler creates physics, it SHALL derive collision shape and body mode from validated physics intent rather than object-name inference.
5. WHEN the Scene_Compiler creates a light, it SHALL create exactly one declared fixture representation and one associated light source unless the World_Contract explicitly specifies otherwise.
6. WHEN compilation completes, THE Structural_Parity_Report SHALL compare expected and compiled IDs, counts, transforms, dimensions, openings, camera, and relationships.
7. IF a required parity check exceeds tolerance, THEN the Engine_Artifact SHALL be rejected.

### Requirement 6: Provide a Playable UPBGE Runtime

**User Story:** As a user, I want the generated world to be immediately explorable via UPBGE, so that world creation results in an interactive experience beyond the Three.js browser view.

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

1. THE system SHALL retain the existing Godot Export_Adapter while supporting the UPBGE Export_Adapter.
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
3. THE Compiler_Manifest SHALL record session ID, interface version, World_Contract version and hash, compiler script hash, UPBGE identity and versions, configuration, timings, diagnostics, and artifact metadata.
4. WHEN an Engine_Artifact is produced, THE Compiler_Manifest SHALL record its path, bytes, SHA-256 hash, media type, and target role.
5. WHEN a persisted session is restored, THE system SHALL reject profile or contract content that differs from the immutable registry identity.
6. Recompiling a historical session SHALL NOT overwrite its prior manifests or artifacts.

### Requirement 10: Gate Artifacts with Structural and Runtime QA

**User Story:** As a quality owner, I want structural and runtime checks before artifact acceptance, so that incorrect compiled output cannot pass as successful.

#### Acceptance Criteria

1. BEFORE an Engine_Artifact is accepted, THE system SHALL require a passing Structural_Parity_Report comparing compiled output against the source World_Contract.
2. WHEN UPBGE runtime output is produced, THE system SHALL require a passing Runtime_Smoke_Report (load, spawn, movement, collision, opening traversal).
3. THE system SHALL distinguish successful native UPBGE output, successful fallback output, partial export, and failure.
4. A fallback result can never be represented as native UPBGE success.

### Requirement 11: Preserve Versioned Behavior and Fallbacks

**User Story:** As a maintainer, I want the UPBGE integration introduced without breaking existing interfaces, so that prior sessions and released versions remain trustworthy.

#### Acceptance Criteria

1. IF user-visible controls or stage behavior change, THEN the implementation SHALL increment the query interface version, retain the preceding version, make the newest released version the default, and show version-switch links.
2. WHEN an older session is restored, THE pipeline SHALL use its persisted Workflow_Profile and SHALL NOT route it through UPBGE unless that profile requires UPBGE.
3. WHEN UPBGE compilation fails and the profile permits fallback, THE pipeline SHALL use the declared adapter and record that fallback in provenance and the user-visible status.
4. THE system SHALL reject unsupported future interface versions rather than silently normalizing them to an older version.
