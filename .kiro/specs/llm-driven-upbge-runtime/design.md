# Design Document

## Overview

The feature introduces a typed world contract between generative reasoning and engine execution. The LLM acts as a director: it proposes objects, relationships, appearance, and interaction intent. Deterministic services validate and resolve that intent, then a pinned UPBGE subprocess compiles the result into a `.blend`, a neutral GLB, a reference render, and optionally a playable UPBGE package. Existing Godot generation remains available through a sibling adapter.

The design intentionally avoids direct LLM-authored Python and avoids making `.blend` the source of truth. UPBGE consolidates scene construction, Eevee rendering, physics setup, and interactive execution, but all product semantics remain serializable outside UPBGE.

## Goals

- Drive world creation from natural language through typed, reviewable commands.
- Use UPBGE as the preferred hidden scene compiler and optional runtime.
- Preserve exact Plan, Camera_Contract, object identity, count, and transform fidelity.
- Retain Godot and Three.js portability through shared contracts and GLB.
- Produce immutable, reproducible compiler evidence.
- Fail closed on invalid geometry and fail over explicitly when UPBGE is unavailable.

## Non-Goals

- Letting an LLM execute arbitrary Python or shell code.
- Letting an LLM drive physics or rendering frame by frame.
- Replacing the Plan, deterministic solver, Canon approval, or Camera_Contract.
- Translating arbitrary engine-specific gameplay behavior perfectly between engines.
- Mutating V9, V10, or any released workflow profile in place.
- Shipping or redistributing UPBGE before version, license, and packaging review.

## Architecture

```text
User description / revision
          |
          v
     LLM Director
  Semantic_Command[]
          |
          v
 Command Validator ----> rejection diagnostics
          |
          v
 Relation Solver + World Contract Builder
          |
          v
 Canonical World_Contract + hash
      /           |             \
     v            v              v
UPBGE Adapter  Godot Adapter   Web/GLB Adapter
     |            |              |
.blend/GLB/    Godot project   GLB + metadata
render/runtime
     \____________|______________/
                  v
      Structural Parity + Runtime QA
```

## Authority Model

1. User-approved Plan owns room dimensions, openings, item identities, metric placement, and counts.
2. Camera_Contract owns projection and initial viewpoint.
3. Canon owns approved appearance intent, not geometry.
4. World_Contract combines those authorities with physics and interaction intent.
5. Export adapters may translate representation but may not reinterpret authority.
6. Runtime simulation may change transient state but may not rewrite the persisted approved contract without a validated revision command.

## Data Models

### WorldContract

A new versioned aggregate should be generated from existing domain models rather than replacing them immediately:

```python
class WorldContract(BaseModel):
    schema_version: Literal["world-contract/v1"]
    source: SourceBinding
    room: RoomShell
    openings: list[WorldOpening]
    instances: list[WorldInstance]
    materials: list[MaterialIntent]
    lights: list[WorldLight]
    camera: CameraBinding
    physics: PhysicsPolicy
    interactions: list[InteractionIntent]
    exports: ExportPolicy
```

`SourceBinding` contains session ID, interface version, profile ID, plan revision/hash, Scene_Graph hash, Camera_Contract ID, and Canon hash. Canonical serialization sorts maps and identity-keyed arrays, rejects non-finite numbers, and hashes UTF-8 JSON bytes. One meter is the unit of length.

### Coordinate Contract

The domain coordinate system remains right-handed X-right, Y-up, Z-depth. Blender/UPBGE uses X-right, Y-depth, Z-up. The UPBGE adapter performs exactly one explicit mapping:

```text
domain (x, y, z) -> UPBGE (x, z, y)
```

Dimensions, rotations, normals, camera vectors, and exported metadata use the same documented conversion. Adapters cannot infer axes from object names.

### Semantic Commands

Commands are discriminated models, for example:

```json
{
  "version": "semantic-command/v1",
  "op": "relate",
  "subject_id": "stool_1",
  "relation": "south_of",
  "target_id": "island_1",
  "parameters": {"gap_m": 0.3}
}
```

Initial operations are `create_instance`, `remove_instance`, `set_relation`, `set_style`, `set_light_intent`, `set_physics_intent`, and `set_interaction_intent`. Camera changes remain requests until a new approved Camera_Contract is created. A command batch applies transactionally: all commands validate before any mutation.

## Components and Interfaces

### 1. LLM Director

The existing interpretation/planning provider produces typed commands and relations. It receives compact allowed schemas and IDs, not filesystem or engine details. Output is untrusted data. The director may explain intent, but only the typed command payload reaches the validator.

### 2. Command Validator

Responsibilities:
- Pydantic schema validation and version dispatch.
- Stable-ID and reference checks.
- Operation and value allowlists.
- Object, texture, polygon, and batch limits.
- Authority checks that prevent Plan and Camera mutation.
- Relation-cycle and contradictory-constraint detection.
- Transactional apply and before/after hashes.

### 3. Relation Solver

The current keyword solver is replaced for the new profile by explicit weighted constraints. Hard constraints include bounds, openings, physical collision, mount surfaces, and camera occupancy. Semantic constraints are hard unless marked relaxable. The solver returns transforms plus a report for every constraint; it never falls back to `(0, 0)` when occupied.

### 4. World Contract Builder

This component combines approved Plan geometry, Scene_Graph appearance/physics, Camera_Contract projection, Canon appearance binding, and accepted commands. It checks cross-authority conflicts before producing canonical bytes.

### 5. UPBGE Capability Probe

`blender_runner.py` evolves into an engine runner with an explicit executable setting such as `UPBGE_PATH`. The probe runs a bounded version script and returns:

```json
{
  "product": "UPBGE",
  "product_version": "...",
  "blender_version": "...",
  "python_version": "...",
  "supports_game_runtime": true,
  "supports_eevee": true,
  "supports_gltf": true
}
```

Regular Blender can remain a compile-only development fallback only when a profile explicitly permits it; it must never be reported as UPBGE.

### 6. UPBGE Sidecar and Scene Compiler

The sidecar receives only canonical contract and compiler options. It uses first-party versioned scripts to:
- Clear the factory scene.
- Build wall solids with actual door/window apertures.
- Instantiate deterministic primitive or approved asset geometry.
- Bind materials without changing object identities.
- Create exact cameras and lights.
- Configure collision bodies and runtime properties.
- Attach versioned first-party runtime components.
- Render a geometry reference.
- Save `.blend`, export GLB with extras, and optionally package runtime output.

The current prototype's solid opening panels, ineffective blockout override, invalid physics placeholder, and ignored runner flags are removed rather than carried forward.

### 7. Runtime Adapter

Runtime behavior is composed from reviewed templates: first-person movement, collision, pause/exit, door interaction, and grabbing. Interaction intents choose templates and parameters; they do not inject source. Dynamic state is saved separately from the approved World_Contract.

### 8. Export Adapters

- **UPBGE**: `.blend`, neutral GLB, render, and optional playable package.
- **Godot**: existing project output migrated to consume World_Contract while preserving current behavior for retained profiles.
- **Three.js**: GLB plus metadata manifest; a full web runtime is deferred.

GLB includes `export_extras` for stable IDs and semantics. Physics and gameplay remain in a JSON sidecar because glTF does not guarantee portable runtime behavior.

### 9. QA and Provenance

Compilation writes prepared and terminal manifests using exclusive creation. Structural parity is computed from the contract and an exported scene inventory, not inferred from pixels. Visual QA remains complementary and evaluates Plan, Blockout, Canon, and UPBGE render. Human verdicts bind to hashes and may supersede, but never overwrite, prior reviews.

## Compilation Flow

1. Load the session and verify its immutable Workflow_Profile.
2. Require an approved Plan and valid Camera_Contract.
3. Build or revise typed Semantic_Commands from user intent.
4. Validate the complete command batch without mutation.
5. Apply the batch and solve explicit relationships deterministically.
6. Build and canonicalize World_Contract; write the prepared manifest.
7. Probe the configured UPBGE executable.
8. Launch the isolated sidecar with canonical input and requested outputs.
9. Inventory the generated scene and compute structural parity.
10. Run applicable GLB and runtime smoke checks.
11. Write a terminal manifest and expose native, fallback, partial, or failed status.
12. Route artifacts into QA and immutable session snapshots.

## Error Handling

Errors use stable stages and reason codes: `contract`, `command_validation`, `constraint_solving`, `capability_probe`, `compile`, `export`, `parity`, `runtime_smoke`, `qa`, and `fallback`. Each failure records retryability and whether portable artifacts remain valid.

- Contract, security, and parity failures are non-retryable without input or code changes.
- Process timeout and transient engine startup failures may be retried within profile limits.
- Missing UPBGE may invoke the declared Godot fallback.
- A fallback never changes the status to native success.
- Partial artifacts are not presented as playable output.
- Existing accepted artifacts remain immutable when later compilation fails.

## V14 Integration Path

The UPBGE compilation path consumes a WorldContract produced by either the text-to-world LLM path or the V14 photo pipeline. V14's WorldContract includes real textured GLB meshes (from Hunyuan3D/Trellis2), PBR materials, dynamic/static physics classification, and a depth-reconstructed room shell. The UPBGE compiler imports these assets rather than generating primitive geometry.

Key integration points:
- V14 `geometry_strategy: "asset"` with `asset_registry_id` → UPBGE imports the real GLB mesh
- V14 `PhysicsIntent` (body_mode, mass_kg, friction, restitution, can_topple) → UPBGE rigid body config
- V14 Room_Shell_Mesh GLB → UPBGE room geometry (replaces procedural wall generation)
- V14 PBR materials (metallic, roughness, normal) → UPBGE Eevee material nodes

Structural parity and runtime smoke gates apply identically to V14-sourced WorldContracts.

## Security Model

The model never receives tool credentials or executable locations and never writes compiler source. Compiler scripts are first-party files bound by hash in the Workflow_Profile. The sidecar receives a minimal environment, canonical read-only input, and one writable output root. Inputs reject path-like fields where paths are not part of the schema. External asset references must resolve through an approved asset registry rather than arbitrary URLs or local paths.

For Windows, process isolation begins with a separate process, sanitized environment, timeout, output-root enforcement, and Job Object resource controls where available. Stronger OS/container isolation remains an implementation option, but lack of it must be visible in capability evidence rather than overstated.

## Determinism and Performance

Compilation caches may key on World_Contract hash, profile ID, compiler hash, UPBGE version, and options. Cache hits must verify every artifact hash before reuse. Runtime timestamps and random identifiers are excluded from canonical input. Any procedural geometry receives an explicit seed.

The initial limits are configuration values, not hard-coded product claims. Metrics include probe time, compile time, render time, export time, peak memory when measurable, object count, triangle count, output bytes, and runtime startup time. Compilation remains asynchronous relative to web request handling.

## Compatibility and Versioning

The integration requires a new Workflow_Profile because compiler target, blockout source, World output, and QA behavior are observable. Existing V9/V10 profile documents remain byte-stable. Future interface versions must be explicitly registered; values greater than the latest supported version return an error instead of being coerced.

The existing Godot path remains available as a profile-selected adapter and fallback. Historical sessions continue to use their persisted/historical profile. No prior session is upgraded merely because UPBGE becomes installed.

## Migration Strategy

### Phase 1: COMPLETE — Offline compiler + parity + runtime

UPBGE compilation infrastructure is operational: scene compiler, runtime templates, export adapters, structural parity gates, and interface version (V11). All completed in tasks 1-12.

### Phase 2: CURRENT — V14 WorldContract integration

After V14 stabilizes, verify that V14's real-mesh WorldContract feeds correctly into the UPBGE compiler. Import real GLB assets, map PBR materials to Eevee, apply physics classification. Run structural parity and runtime smoke.

### Phase 3: FUTURE — Photo-to-2D-CAD SLM training

Use V14 pipeline outputs as a data factory for training a small vision model that converts room photos directly to 2D CAD floor plans. See `self-learning-flywheel-design.md`.

## Correctness Properties

### Property 1: Canonicalization Idempotence

Canonicalizing an already canonical World_Contract produces identical bytes and hash.

**Validates: Requirements 1.5**

### Property 2: Command Atomicity

Any invalid command causes the complete batch to leave the input World_Contract unchanged.

**Validates: Requirements 2.5**

### Property 3: Coordinate Round Trip

Mapping a finite transform from domain to UPBGE coordinates and back preserves values within numeric tolerance.

**Validates: Requirements 5.2, 5.3**

### Property 4: Authority Preservation

Compilation cannot change approved Plan geometry, opening identities, counts, or Camera_Contract projection.

**Validates: Requirements 1.2, 5.2, 5.3**

### Property 5: Instance Conservation

Every accepted World_Contract instance appears exactly once in each structurally accepted target inventory unless explicitly marked unsupported.

**Validates: Requirements 5.2, 7.5**

### Property 6: Constraint Safety

A successful solve contains no out-of-bounds footprint, physical overlap, blocked opening, invalid mount, or occupied camera footprint.

**Validates: Requirements 3.2, 3.3**

### Property 7: Artifact Binding

Every accepted artifact hash occurs in exactly one terminal manifest bound to its prepared manifest inputs.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4**

### Property 8: Fallback Transparency

A fallback result can never be represented as native UPBGE success.

**Validates: Requirements 11.4, 11.5**

### Property 9: Historical Stability

Selecting a retained profile produces the same compiler-routing policy regardless of currently installed engines.

**Validates: Requirements 11.1, 11.3**

### Property 10: Runtime Template Isolation

Varying semantic data cannot alter first-party runtime template source or escape allowlisted parameters.

**Validates: Requirements 2.3, 6.2, 8.1**

## Testing Strategy

### Unit and property validation

- Canonical World_Contract serialization and hashing.
- Semantic command allowlists, rejection, and transactional application.
- Coordinate and rotation conversion round trips.
- Relationship solver invariants over varied room and object dimensions.
- Opening, collision, mount, camera, count, and ID preservation.
- Manifest exclusivity and artifact hash binding.

### Integration validation

- Capability probing against the pinned UPBGE build.
- Headless compilation of representative 8–12 object rooms.
- `.blend` load, GLB reload, extras, bounds, materials, camera, and light checks.
- UPBGE runtime startup, movement, collisions, doors, and grabbing.
- Godot adapter parity and explicit UPBGE-unavailable fallback.

### Visual and release validation

- Seven-category qwen2.5vl screening with confidence gate.
- Artifact-bound human review.
- Plan/Blockout/Canon/UPBGE-render comparison.
- Retained-interface checks.
- One complete clean zero-state release pass on the exact target commit.

## Principal Risks and Mitigations

| Risk | Mitigation |
|---|---|
| UPBGE/Blender API drift | Pin and probe exact builds; bind versions and compiler hash in manifests. |
| LLM emits unsafe or contradictory output | Typed allowlisted commands, transactional validation, no generated code execution. |
| Scene differs across targets | One World_Contract plus structural inventories and parity reports. |
| GLB loses gameplay or physics | Export explicit sidecar metadata and target Runtime_Adapters. |
| Counts or openings drift | Exact ID/count checks and real constructive openings before artifact acceptance. |
| Camera differs from Canon | Bind and numerically validate one Camera_Contract across all renderers. |
| Headless runtime failures remain invisible | Load tests, reference render, runtime smoke harness, and structured diagnostics. |
| Engine installation becomes product lock-in | Keep neutral contracts and sibling Godot/Three.js adapters. |
| Historical behavior changes accidentally | New interface/profile; byte-stable retained profiles and characterization checks. |
| Third-party distribution obligations are missed | Gate packaging on exact-version license and attribution review. |

## Design Decision

UPBGE is selected as the preferred hidden scene compiler and optional integrated runtime, not as the canonical product data model. The LLM directs typed intent, deterministic code compiles it, and artifact acceptance depends on structural evidence rather than visual plausibility alone.
