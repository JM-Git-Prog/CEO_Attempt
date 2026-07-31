# Requirements Document

## Introduction

This specification defines the complete end-to-end system for transforming a natural-language conversation into a walkable, interactive 3D world with persistent GAME and REAL mode behaviors, compounding asset warehouse, and engine-neutral output. It supersedes and unifies the fragmented V14/V15 photo pipeline specs, the integration blueprint, and the product vision into one executable marathon spec.

**The governing sentence:** Does this turn conversation into a validated place, preserve one truth per concern, let the user steer what matters, reach a walkable world, enable GAME and REAL behaviors, and compound approved work?

### Core Principles

1. **Always fresh generation** — every session generates new meshes; the warehouse catalogs results but is never consulted before generation.
2. **One truth per concern** — Dream Preview owns mood; Plan owns space; Canon owns appearance; WorldContract binds everything.
3. **Human gates where perception matters** — Plan/Blockout approval, Canon approval, mesh shape approval, final world QA.
4. **Automated gates where correctness is measurable** — containment, overlap, circulation, parity, hash binding.
5. **Engine-neutral WorldContract** — browser, Godot, and UPBGE consume the same hash-bound contract.
6. **Per-room REAL/GAME toggle** — identical visuals, different behavior overlays.
7. **Warehouse compounds but never blocks** — append-only, session-independent, never consulted pre-generation.

### Environment Assumptions

- NVIDIA RTX 4090 (24GB VRAM), 96GB system RAM, Windows 11.
- ComfyUI on localhost:8188 with Hunyuan3D 2.1, Trellis2, SAM ViT-H, FLUX.2, Depth Anything 3.
- Ollama with flash attention for semantic labeling and conversation.
- Local LLM (Ollama) for Brief interpretation, Plan generation, GAME design.
- UPBGE 0.50 and Godot 4.x installed for optional compilation.
- Single-user, single-session-at-a-time execution.
- No cloud API calls without explicit user permission.
- Qualification scene: Danny's kitchenette (or any user-described interior).

## Glossary

- **Dream_Preview**: A provisional, non-authoritative mood image shown during conversation to enable visual steering. Never controls geometry.
- **Brief**: The structured interpretation of user intent — purpose, atmosphere, era, palette, objects, GAME concept, REAL capabilities.
- **Art_Bible**: Style reference derived from conversation — materials, palette, era exclusions, lighting direction.
- **Metric_Plan**: The validated, solver-approved spatial layout — rooms, walls, openings, placements, circulation, clearances.
- **Blockout**: A 3D render of the validated Plan from the immutable CameraContract, showing geometry before expensive art.
- **Scene_Canon**: The final approved photorealistic image conditioned on approved Blockout. Owns appearance, not geometry.
- **Object_Canon**: The approved appearance reference for one object — original extraction or completed version.
- **WorldContract**: The single hash-bound, engine-neutral document binding Plan, assets, physics, lighting, and camera.
- **CameraContract**: Immutable perspective projection shared by Blockout, Canon, and initial World presentation.
- **Approved_Asset**: A concrete mesh with verified hash, triangle count, materials, and provenance bound to the WorldContract.
- **Asset_Warehouse**: The persistent append-only library cataloging every approved asset with full metadata.
- **GAME_Overlay**: Per-room behavior bindings that assign gameplay roles to stable object identities.
- **REAL_Overlay**: Per-room behavior bindings that connect external tool data to surfaces.
- **Mode_Toggle**: The per-room switch between REAL and GAME that changes only behavior, never visuals.

## Requirements

### Requirement 1: Conversational Front Door

**User Story:** As a user, I want to describe my desired space through natural conversation with an AI that leads and proposes, so that I never face a blank form or technical interface.

#### Acceptance Criteria

1. WHEN the user opens the interface, THE system SHALL present a conversational prompt that asks about the desired space in natural language, never a form or blank text box.
2. THE AI SHALL interpret the user's description and propose art direction, era, mood, palette, key objects, and spatial character within the first exchange.
3. THE AI SHALL propose a GAME concept (mechanics, scoring, theme) tailored to the described space within the first three exchanges.
4. THE AI SHALL propose potential REAL capabilities (which tools could wire to which surfaces) within the first three exchanges.
5. WITHIN the first exchange, THE system SHALL generate and display a Dream_Preview image showing the proposed mood and style.
6. THE Dream_Preview SHALL be explicitly labeled as provisional and non-authoritative for spatial decisions.
7. THE user SHALL be able to point out mistakes, redirect style, add or remove objects, and adjust the concept through continued conversation.
8. WHEN the user's steering stabilizes, THE system SHALL produce a structured Brief capturing: purpose, atmosphere, era, palette, required objects, GAME concept, REAL capability hooks, and success criteria.

### Requirement 2: Brief Interpretation and Structured Intent

**User Story:** As a developer, I want the conversation to produce a machine-readable structured Brief, so that downstream stages have unambiguous input.

#### Acceptance Criteria

1. THE Brief SHALL contain: room_purpose, atmosphere (mood + lighting_direction + time_of_day), era (period + style_exclusions), palette (primary + accent + material_finishes), object_manifest (list of {id, name, role, count, material_hint, is_architectural}), game_concept (theme + mechanics + scoring + win_condition), real_capabilities (list of {tool_type, surface_binding, read_only_v1}), and success_criteria (user's stated done-check).
2. EACH object in the manifest SHALL receive a stable UUID that persists through all downstream stages.
3. THE Brief SHALL record provenance: which user utterance generated each field, and which AI proposal was accepted or modified.
4. IF any required Brief field cannot be determined from conversation, THE system SHALL use a documented safe default and flag the field as defaulted.
5. THE system SHALL validate Brief completeness before advancing to Plan generation.

### Requirement 3: Dream Preview Generation

**User Story:** As a user, I want to see an immediate visual representation of the AI's interpretation, so that I can steer by pointing rather than only by describing.

#### Acceptance Criteria

1. THE Dream_Preview SHALL be generated within 15 seconds of the first user description using FLUX via ComfyUI.
2. THE Dream_Preview SHALL reflect the proposed era, mood, palette, and key objects from the current conversation state.
3. THE Dream_Preview SHALL NOT be used as spatial authority for Plan, Blockout, or WorldContract geometry.
4. THE Dream_Preview SHALL be regenerated when the user provides significant steering feedback.
5. MULTIPLE Dream_Preview variants MAY be shown for the user to indicate preference direction.
6. THE system SHALL record which Dream_Preview the user responded positively to, for Art_Bible conditioning.

### Requirement 4: Art Bible Derivation

**User Story:** As a developer, I want a structured style reference derived from the approved conversation direction, so that all downstream visual generation is consistent.

#### Acceptance Criteria

1. FROM the approved Brief and preferred Dream_Preview, THE system SHALL produce an Art_Bible containing: era_rules (what belongs, what to exclude), material_palette (specific materials with PBR hints), lighting_direction (key/fill/accent with color temperatures), color_palette (hex values + usage rules), and prop_style (silhouette language, detail level, wear/patina).
2. THE Art_Bible SHALL explicitly list era exclusions (e.g., "no smart thermostats in a 1950s diner").
3. THE Art_Bible SHALL be used to condition Canon generation, material estimation, and architectural finishing.
4. THE Art_Bible SHALL be immutable once Canon generation begins — changes require returning to conversation.

### Requirement 5: Metric Plan Generation and Validation

**User Story:** As a user, I want the AI to produce a spatially valid floor plan from my description, so that the resulting world has correct dimensions, walkable paths, and properly placed openings.

#### Acceptance Criteria

1. THE system SHALL convert the Brief's spatial requirements into a Metric_Plan using constrained template selection and parameterization (not free-form LLM emission of coordinates).
2. THE Metric_Plan SHALL define: room dimensions (meters), wall positions, door openings (position along wall as parameter 0..1, width, height), window openings (same parameterization), object placements (position, rotation, dimensions), and required circulation paths.
3. THE system SHALL validate the Metric_Plan against: room closure (all walls connect), opening validity (not too close to corners, not on wall stubs), object non-overlap, circulation clearance (minimum 0.6m walkable paths), door swing clearance, and dimensional plausibility (no room narrower than 1.5m or taller than 6m for residential).
4. IF validation fails, THE system SHALL correct the Plan automatically and create a new revision number.
5. EVERY Plan revision SHALL be traceable — revision number, what changed, why.
6. THE Metric_Plan SHALL use relative parameterization (fixtures reference parent wall by ID and parameter, not absolute world coordinates) so that wall moves propagate to attached fixtures.

### Requirement 6: Immutable Camera Contract

**User Story:** As a developer, I want one locked camera projection shared across Blockout, Canon, and initial World, so that spatial registration is guaranteed.

#### Acceptance Criteria

1. WHEN the Metric_Plan is validated, THE system SHALL create one immutable CameraContract defining: position, target, up vector, vertical FOV, aspect ratio, near/far planes, and raster dimensions (1024×768).
2. THE CameraContract SHALL be right-handed, X-right, Y-up, Z-depth perspective.
3. ONCE created, THE CameraContract SHALL NOT be mutated by any downstream stage.
4. THE CameraContract SHALL be used identically for Blockout rendering, Canon conditioning, and initial World presentation.
5. THE CameraContract SHALL include a stable hash for binding verification.

### Requirement 7: Blockout Rendering and Spatial Approval

**User Story:** As a user, I want to see and approve the spatial layout before expensive visual generation begins, so that I can catch dimensional or placement errors cheaply.

#### Acceptance Criteria

1. THE system SHALL render the validated Metric_Plan as a 3D Blockout from the CameraContract viewpoint.
2. THE Blockout SHALL show: walls with actual openings (doors, windows), object placeholders at correct scale and position, and major architectural features.
3. THE user SHALL approve or revise the Blockout before Canon generation proceeds.
4. IF the user requests revisions, THE system SHALL return to Plan generation with the feedback, produce a new Plan revision, and re-render the Blockout.
5. NO expensive mesh generation, texturing, or Canon rendering SHALL begin before Blockout approval.

### Requirement 8: Scene Canon Generation and Approval

**User Story:** As a user, I want a photorealistic final reference image that respects my approved spatial layout, so that the visual target for the world is both beautiful and geometrically honest.

#### Acceptance Criteria

1. THE Scene_Canon SHALL be generated by FLUX via ComfyUI, conditioned on the approved Blockout geometry and the Art_Bible style direction.
2. THE Scene_Canon SHALL use the identical CameraContract framing as the Blockout.
3. THE system SHALL validate that the Scene_Canon contains all objects from the Brief's manifest — each receives a present/missing/uncertain verdict.
4. THE user SHALL approve, reject (with feedback), or request regeneration of the Scene_Canon.
5. WHEN approved, THE Scene_Canon's hash SHALL be bound to the Plan revision and CameraContract hash.
6. THE Scene_Canon owns appearance (materials, lighting mood, object identity). It does NOT own geometry, dimensions, placement, or collision.
7. NO mesh generation or world assembly SHALL begin before Scene_Canon approval.

### Requirement 9: Object Segmentation and Isolation

**User Story:** As a developer, I want each object cleanly isolated from the approved Canon, so that individual mesh generation has clean input.

#### Acceptance Criteria

1. THE system SHALL segment the approved Scene_Canon using SAM to produce one RGBA Object_PNG per object on transparent background.
2. EACH Object_PNG SHALL correspond to exactly one object from the Brief's manifest via the stable UUID.
3. BLANK or broken segmentations (empty mask, <1% coverage) SHALL be detected automatically and flagged.
4. THE Object_PNG SHALL be used directly as input to mesh generation (Object_Canon = raw segmentation for MVP).
5. (POST-MVP) IF an object is partially occluded, THE system SHALL complete the hidden portions via controlled inpainting (FLUX) to produce a full Object_Canon.
6. (POST-MVP) BLANK, fused, or broken completions SHALL be detected automatically (corner purity check, subject coverage 20-80% of frame, no ground shadow band) and rejected.
7. (POST-MVP) THE user SHALL choose between the original extraction and the completed version as the authoritative Object_Canon.
8. (POST-MVP) THE approved Object_Canon SHALL be recorded with provenance (original pixels vs. inpainted regions, prompt used, approval timestamp).

### Requirement 10: Always-Fresh Mesh Generation

**User Story:** As a user, I want every session to produce freshly generated meshes unique to my submission, so that each world is original.

#### Acceptance Criteria

1. WHEN an Object_Canon is approved, THE system SHALL generate a fresh 3D mesh without consulting the Asset_Warehouse for existing similar assets.
2. THE system SHALL NOT implement similarity matching, hash-based lookup, or semantic deduplication against the warehouse before generating.
3. THE primary generator SHALL be Hunyuan3D 2.1 via ComfyUI (ImageOnlyCheckpointLoader → ModelSamplingAuraFlow → CLIPVisionEncode → Hunyuan3Dv2Conditioning → KSampler steps=50, cfg=7.0 → VAEDecodeHunyuan3D octree_resolution=384 → VoxelToMesh → SaveGLB).
4. IF Hunyuan3D fails or stalls beyond 180 seconds, THE system SHALL fall back to Trellis2 (18 steps, 12000 triangles, GLB with embedded textures).
5. IF both fail, THE system SHALL produce placeholder geometry (box/cylinder/sphere by aspect ratio) colored with Object_Canon average color.
6. THE system SHALL validate each mesh: ≥100 faces, ≥50 vertices, embedded texture data, no fused ground sheet (M8 rule).
7. GENERATED meshes SHALL be scaled to real-world dimensions using the Plan's object placement dimensions.

### Requirement 11: Mesh Shape Approval

**User Story:** As a user, I want to inspect important newly generated meshes before expensive painting begins, so that bad geometry doesn't waste time.

#### Acceptance Criteria

1. FOR each newly generated mesh, THE system SHALL present a turntable preview to the user.
2. THE user SHALL approve or reject the mesh shape.
3. REJECTED meshes SHALL return to generation with the rejection reason recorded.
4. APPROVED meshes SHALL proceed to material/texture application.
5. PLACEHOLDER geometry SHALL be clearly labeled and does not require shape approval (it is inherently approximate).

### Requirement 12: Two-Pass Material Application

**User Story:** As a user, I want objects to have immediate textures that improve to full PBR quality over time.

#### Acceptance Criteria

1. PASS 1: For Hunyuan3D/Trellis2 meshes, accept native generator textures (already conditioned on Object_Canon). For placeholders only, photo-project the Object_Canon onto the mesh surface. Pass 1 SHALL complete within 2 seconds of mesh availability.
2. PASS 2: When GPU is free, estimate metallic (0-1), roughness (0-1), and normal map from the Object_Canon. Process largest objects first.
3. THE V14 interface SHALL hot-swap Pass 2 materials via WebSocket without page reload.
4. IF Pass 2 fails, Pass 1 textures SHALL be retained — the object remains visually acceptable.
5. ALL textures SHALL be embedded in the GLB as buffer views (no external file references).
6. TEXTURE dimensions SHALL be: 256×256 (<2% image area), 512×512 (2-10%), 1024×1024 (>10%).

### Requirement 13: Semantic Labeling

**User Story:** As a developer, I want each object semantically labeled for warehouse cataloging and physics estimation.

#### Acceptance Criteria

1. THE system SHALL send each Object_PNG to Ollama requesting: semantic_label, primary_material, category (props/architecture/foliage/hard-surface/set-dressing), estimated_era, condition (new/worn/broken), is_architectural.
2. THE labeling call SHALL use a vision-capable model and complete within 10 seconds.
3. IF Ollama fails, THE system SHALL fall back to heuristic labeling based on dimensions and mask shape.
4. THE semantic label SHALL determine: warehouse category, material density for physics, and asset filename.
5. THE response SHALL be validated: all required fields present, category matches one of five taxonomy values.

### Requirement 14: Depth Estimation

**User Story:** As a developer, I want metric depth for room shell reconstruction and object placement reference.

#### Acceptance Criteria

1. THE system SHALL invoke Depth Anything 3 via ComfyUI producing a metric depth map (meters) at source resolution.
2. DA3 SHALL load only after FLUX is fully unloaded from VRAM.
3. THE depth map SHALL be validated: ≥50% valid pixels (positive, finite, <20m for indoor).
4. THE depth map SHALL be saved as float32 NumPy .npy.
5. IF DA3 fails, fall back to MoGe-2, then flat-floor heuristic (4m depth, aspect-ratio width, 2.7m ceiling).

### Requirement 15: VRAM Management

**User Story:** As a developer, I want strict sequential model loading to prevent OOM crashes on the RTX 4090.

#### Acceptance Criteria

1. FLUX and Hunyuan3D SHALL never be loaded simultaneously.
2. BETWEEN model transitions, call ComfyUI `/free` and wait for VRAM < 4GB before loading next.
3. FIXED stage order: SAM → FLUX inpaint → unload → DA3 → unload → Hunyuan3D per object (sequential) → unload.
4. Flash attention enabled for all inference to stay below 22GB peak.
5. OOM recovery: call /free, wait 5s, retry once, then fall to next method in chain.
6. System RAM pause at >80GB, resume at <72GB.

### Requirement 16: Room Shell Reconstruction

**User Story:** As a user, I want the room environment to be a real textured mesh matching the photographed/rendered space.

#### Acceptance Criteria

1. THE room shell SHALL be reconstructed using a displaced-grid method from the depth map (max 500 vertices per dimension).
2. THE shell SHALL be textured with the inpainted Room_Plate (Canon with objects removed) using direct UV mapping.
3. FACES with depth gradient >0.5m between adjacent vertices SHALL be removed (no bridge triangles).
4. NORMALS SHALL face inward (toward camera origin) for correct interior rendering.
5. THE shell SHALL be oriented Y-up, meters, right-handed.
6. FALLBACK: flat box room (4m × aspect × 2.7m) textured with Room_Plate via planar projection.
7. VERTEX count SHALL be between 10,000 and 250,000.

### Requirement 17: Architectural Completion (Finish Pass)

**User Story:** As a user, I want architecturally complete spaces with correct trim, molding, fixtures, and era-appropriate details.

#### Acceptance Criteria

1. THE system SHALL place pre-baked architectural primitives (baseboards, door frames, window frames, casing) from a small built-in library, positioned procedurally along parent walls. No CSG or boolean geometry operations are required.
2. ALL architectural details SHALL be parameterized along their parent wall (M3 rule — geometry is derived, never hand-placed).
3. BASEBOARDS and CASING SHALL be placed by extruding a 2D profile along the wall path (simple sweep, not boolean).
4. OUTLETS and SWITCHES SHALL be placed at era-appropriate heights as flat quad decals or simple box primitives.
5. THE finish pass SHALL respect era exclusions from the Art_Bible (no smart thermostats in 1950s).
6. IF the finish pass cannot determine appropriate detail for an element, it SHALL omit rather than hallucinate.
7. CROWN MOLDING, WAINSCOTING, and VENT COVERS are post-MVP polish — stub the interface but defer implementation.

### Requirement 18: Physics Classification and World Assembly

**User Story:** As a user, I want realistic physics — light things move, heavy things stay put, doors swing.

#### Acceptance Criteria

1. EACH object SHALL be classified dynamic (≤25kg, grabbable/pushable) or static (>25kg or architectural, immovable).
2. MASS SHALL be estimated: volume_m3 × material_density (wood=600, metal=7800, glass=2500, fabric=200, ceramic=2300, plastic=950 kg/m³).
3. DYNAMIC objects: body_mode=DYNAMIC, estimated mass, friction=0.5, restitution=0.2, can_topple=True.
4. STATIC objects: body_mode=STATIC, mass=0, friction=0.6, restitution=0.1, can_topple=False.
5. ARCHITECTURAL elements (walls, doors, built-ins, countertops, large appliances) SHALL be STATIC regardless of mass.
6. DOORS SHALL receive hinge joints with configured limits and mass.
7. A physics settle pass (max 500 iterations or 5s) SHALL resolve floating objects and interpenetration.
8. ALL objects SHALL be clamped within room bounds with 0.05m margin.

### Requirement 19: Canonical WorldContract Assembly

**User Story:** As a developer, I want one deterministic, hash-bound contract that every consumer reads identically.

#### Acceptance Criteria

1. THE WorldContract SHALL bind: Plan revision, CameraContract hash, room shell reference, all object instances (position, rotation, scale, asset binding, physics intent, material intent), lighting configuration, and relationship graph.
2. THE WorldContract SHALL be serialized deterministically and hashed (SHA-256).
3. THE hash SHALL bind plan revision, camera, room authority, instances, transforms, relationships, materials, physics, and approved asset bindings.
4. NO browser payload, compiler plan, or published artifact SHALL claim final status without a valid WorldContract hash.
5. EVERY object event marked "final" SHALL contain transforms from the solved WorldContract and the exact hash.
6. PROVISIONAL events (before contract creation) SHALL be explicitly marked provisional.

### Requirement 20: Pre-Publication Validation Gates

**User Story:** As a release owner, I want objective gates before anything is called final.

#### Acceptance Criteria

1. GEOMETRY gate: room closure verified, all walls connect, every object extent within room bounds, camera origin in navigable interior space.
2. PHYSICS gate: every final mesh has verified path and positive triangle count, collision shapes match visible geometry, no floating objects after settle.
3. SEMANTIC gate: every object has a valid semantic label, category matches taxonomy, WorldContract hash is stable across serialization.
4. FAILURE of any MVP gate SHALL prevent final publication and compiled release.
5. EACH gate result SHALL be recorded with contract hash, plan revision, and focused failure details.
6. (POST-MVP) PROVENANCE gate: nonzero evidence provenance and plan revision with unbroken chain.
7. (POST-MVP) CIRCULATION gate: required walkable paths meet minimum clearance (≥0.6m).
8. (POST-MVP) MATERIAL gate: every mesh has verifiable material or is honestly labeled degraded.
9. (POST-MVP) ASSET gate: every final mesh has verified SHA-256 digest matching registry.
10. (POST-MVP) PARITY gate: browser and compiled engine payloads carry same WorldContract hash and equivalent derived values.

### Requirement 21: Engine Compilation

**User Story:** As a user, I want my validated world compilable to browser preview, Godot, or UPBGE from the same contract.

#### Acceptance Criteria

1. THE browser compiler SHALL derive a Three.js scene from the WorldContract with GLTFLoader, PBR rendering, orbit + first-person controls, and progressive SSE loading.
2. THE Godot compiler SHALL emit a complete Godot 4 project with .tscn scene, physics bodies, first-person controller, grabbing, door behavior, and correct lighting.
3. THE UPBGE compiler SHALL emit a .blend with player controller, character physics, logic bricks, and correct scene structure.
4. ALL compilers SHALL consume the identical WorldContract — no independent re-estimation of dimensions, transforms, or camera.
5. THE user SHALL choose which output format(s) to compile.
6. A first-person player controller SHALL receive a safe spawn position within navigable space.

### Requirement 22: Walkable World and Interaction

**User Story:** As a user, I want to walk into my completed world, interact with objects, and experience physics.

#### Acceptance Criteria

1. THE player SHALL move with WASD + mouse look in first person.
2. DOORS SHALL swing on configured hinges when interacted with.
3. DYNAMIC objects SHALL be grabbable, pushable, and toppable.
4. PHYSICS SHALL respond realistically — objects fall, collide, settle.
5. LIGHTING SHALL reproduce the Scene_Canon's atmosphere.
6. THE world SHALL remain visually faithful to the approved Canon.
7. THE user's perception SHALL be the final quality gate — green or it isn't done.

### Requirement 23: GAME Mode

**User Story:** As a user, I want a persistent AI-designed game that uses my room's objects as gameplay elements.

#### Acceptance Criteria

1. THE system SHALL define the GameOverlay data model: rules, scoring, win_condition, object_role_bindings (by UUID).
2. GAME bindings SHALL reference objects by their stable UUID from the Brief.
3. THE GAME overlay SHALL NOT alter geometry, materials, or lighting — only behavior and interaction affordances.
4. THE marathon implementation SHALL return a stubbed game concept (theme + suggested mechanics) without functional gameplay logic.
5. (POST-MVP) THE AI SHALL design a game concept tailored to the room (noir tower → investigation, diner → service/rhythm, kitchenette → cooking challenge).
6. (POST-MVP) THE game SHALL define functional: rules, scoring, win condition with runtime execution.
7. (POST-MVP) GAME progress (score, unlocks, state) SHALL persist across sessions.
8. (POST-MVP) IF the user remodels a room the game depends on, THE AI SHALL patch affected bindings and explain what changed.
9. (POST-MVP) GAME points SHALL unlock game content only — never land/budget (that requires REAL work).

### Requirement 24: REAL Mode

**User Story:** As a user, I want my room to display real data from my connected tools on appropriate surfaces.

#### Acceptance Criteria

1. REAL mode v1 SHALL be read-only: live data displayed on surfaces, no sending/paying/deleting.
2. BINDINGS: desk → inbox, filing cabinet → documents, terminal → shell output, whiteboard → calendar, computer → inference.
3. REAL bindings SHALL reference objects by their stable UUID.
4. REAL data SHALL appear on the bound surface without altering geometry or materials.
5. TOOL connections SHALL be MCP-server-compatible for extensibility.
6. REAL work (verified by connected tool activity) SHALL earn budget that buys land/new rooms.
7. CONSEQUENTIAL actions (reply, send, delete, pay) SHALL require explicit user approval and are deferred to v2.

### Requirement 25: Per-Room Mode Toggle

**User Story:** As a user, I want to switch between REAL and GAME in the same room instantly with no visual change.

#### Acceptance Criteria

1. THE toggle SHALL be per-room — each room remembers its own mode.
2. SWITCHING modes SHALL NOT change geometry, materials, lighting, or any visual property.
3. ENTERING a room SHALL loudly announce its current mode (visual indicator, audio cue, or HUD state).
4. EITHER mode counts as "alive" — a GAME-finished room and a REAL-finished room are equally valid.
5. MODE state SHALL persist across sessions.
6. THE scoring bridge is asymmetric: real work → budget → land; game points → game content only.

### Requirement 26: Asset Warehouse (Append-Only Cataloging)

**User Story:** As a user, I want every approved asset permanently cataloged so my collection grows with each build.

#### Acceptance Criteria

1. WHEN a mesh is approved (Hunyuan3D or Trellis2, not placeholder), THE warehouse SHALL save the GLB into the appropriate category: assets/props/, assets/architecture/, assets/foliage/, assets/hard-surface/, assets/set-dressing/.
2. ALONGSIDE the GLB, THE warehouse SHALL write a JSON registry: name, semantic_label, category, era, condition, material_type, dimensions_m, weight_estimate_kg, generation_method, source_session_id, face_count, vertex_count, has_pbr_textures, game_properties (if assigned), real_bindings (if assigned), created_at.
3. THE warehouse SHALL be append-only and session-independent — never overwrite, never delete.
4. FILENAMES SHALL use: {semantic_label_slug}_{session_short}_{mask_id}.glb.
5. THE warehouse SHALL NOT be consulted before generation (always-fresh rule).
6. EACH asset SHALL retain an asset card with: source prompt, Object_Canon reference, generation seed, workflow parameters, approval timestamp, tri count — sufficient to replay generation.

### Requirement 27: Pipeline Orchestration

**User Story:** As a developer, I want reliable end-to-end orchestration that prioritizes quality over speed.

#### Acceptance Criteria

1. THE pipeline SHALL support up to 15 objects per scene with no hard time cap.
2. STAGES SHALL execute in VRAM-safe order with SSE progress events at each transition.
3. PROGRESS SHALL report: current stage, objects X/N complete, elapsed time, ETA.
4. A 180-second stall detection (not quality timeout) SHALL trigger fallback for the stalled object only.
5. THE pipeline SHALL record: session_id, source hashes, quality classification, generation metadata per object.
6. PASS 2 materials SHALL begin only after all Pass 1 meshes are loaded in the viewer.

### Requirement 28: Interface Versioning and Coexistence

**User Story:** As a developer, I want the unified pipeline to coexist with all existing versions.

#### Acceptance Criteria

1. THE unified pipeline SHALL be accessible as a new interface version (V16 or as configured).
2. ALL previous versions (V3–V15) SHALL remain accessible via ?v=N with identical behavior.
3. THE new version SHALL be the default when no ?v= parameter is supplied.
4. SESSION metadata SHALL include interface_version, same FIFO queue, lifecycle, and TTL cleanup.
5. BEFORE committing, THE system SHALL create a fresh empty session, run the canonical qualification prompt, inspect all stages, and pass cleanly.

### Requirement 29: Serialization Round-Trip Integrity

**User Story:** As a developer, I want all pipeline artifacts to serialize and deserialize losslessly.

#### Acceptance Criteria

1. GLB files loaded by Three.js GLTFLoader and re-exported by GLTFExporter SHALL produce vertex positions differing by <1e-5.
2. WorldContract JSON serialized and deserialized SHALL produce identical canonical hash.
3. Asset Registry JSON SHALL round-trip losslessly.
4. Pipeline Manifest JSON SHALL round-trip losslessly.
5. Depth maps (.npy float32) SHALL round-trip losslessly.

### Requirement 30: Qualification and Release

**User Story:** As a release owner, I want qualification from a clean zero-state session with Danny's kitchenette.

#### Acceptance Criteria

1. QUALIFICATION SHALL begin with a brand-new empty session.
2. THE canonical prompt SHALL be: "Danny's kitchenette — a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain."
3. QUALIFICATION SHALL traverse: Conversation → Brief → Dream → Plan → Blockout → Canon → Objects → Meshes → Materials → Physics → WorldContract → Compilation → Validation → Walk → GAME concept → REAL concept → Toggle demonstration.
4. EVERY affected stage SHALL be inspected for correctness.
5. A failed session SHALL be retained as diagnostic evidence only, never release evidence.
6. RELEASE SHALL occur only after one complete clean zero-state pass.
7. THE commit SHALL use: `feat(web): release vN unified-world-pipeline`.

## Corrective Requirements Tranche — Pre-Task 5.1 Authority, Finality, and Qualification Correction

### Normative Precedence

This additive tranche supersedes only conflicting clauses in Requirements 14–20 and 27–30. All non-conflicting clauses in Requirements 1–30 remain in force verbatim.

### Corrective Tranche Glossary

- **Approved_Normalized_Metric_Plan**: The nonzero-revision Metric_Plan that has completed solve, normalization, validation, and human approval.
- **Evidence_Input**: Scene_Canon, Room_Plate, mask, depth, or other observation used to evaluate appearance or alignment without spatial authority.
- **Neural_Mesh**: Generated geometry that remains a candidate asset until approval, provenance verification, and exactly-once normalization.
- **Constrained_SceneGraph**: A scene graph whose authoritative spatial values are derived from the Approved_Normalized_Metric_Plan and immutable CameraContract.
- **Relationship_Solve**: Deterministic resolution of containment, attachment, support, opening-host, and collision relationships before canonical hashing.
- **Canonical_Hash**: The SHA-256 digest of the deterministic, relationship-solved WorldContract serialization.
- **Structural_Gate_Set**: The provenance, containment, overlap/opening/circulation, camera, asset, material, geometry, physics, and semantic gates required before compilation.
- **Parity_Gate**: The post-compilation comparison of browser and selected-engine outputs against the same WorldContract.
- **Asset_Normalization**: The single conversion of approved asset coordinates, units, orientation, scale, and origin into contract space.
- **Durable_Checkpoint**: An atomic stage record containing input hashes, output hashes, Plan revision, approval revision, external-job identity, attempt, and completion state.
- **External_Job**: Work submitted to a process or service outside the durable orchestrator transaction.
- **Stale_Response**: An External_Job response bound to a superseded Plan, Canon, Object_Canon, mesh, material, or approval revision.
- **Worker_Lease**: The durable exclusive right for one worker to advance one session.
- **Approval_Writer**: The durable exclusive owner permitted to record approval state for one session.
- **Three_View_Identity_Report**: A hash-bound comparison of Plan-derived Blockout or blueprint, Scene_Canon, and first-person World render.
- **Fresh_Zero_State_Run**: A qualification run created from a brand-new empty session without restored state or prior-version artifacts.
- **V15_Behavior**: Observed V15 behavior retained for comparison and diagnosis without authority over the current pipeline or release qualification.

### Requirement 31: Corrected Spatial Authority Boundary

**User Story:** As a release owner, I want one spatial authority, so that evidence and generated assets cannot silently redefine the approved world.

#### Acceptance Criteria

1. THE Authority_Controller SHALL recognize the Approved_Normalized_Metric_Plan as the sole authority for architecture, openings, navigation, collision, object transforms, and CameraContract derivation.
2. THE Authority_Controller SHALL classify Scene_Canon and Room_Plate as appearance evidence, masks and depth as Evidence_Inputs, and Neural_Mesh instances as candidate assets.
3. THE Authority_Controller SHALL derive every authoritative room dimension, opening, navigable bound, collision shape, object transform, and camera parameter from the Approved_Normalized_Metric_Plan.
4. IF an Evidence_Input conflicts with the Approved_Normalized_Metric_Plan, THEN THE Authority_Controller SHALL retain the Approved_Normalized_Metric_Plan value and record the discrepancy.
5. IF depth-derived geometry claims architecture, opening, navigation, collision, transform, or camera authority, THEN THE Authority_Controller SHALL reject the authority claim.
6. WHERE depth evidence is aligned for appearance comparison, THE Evidence_Aligner SHALL apply one camera-anchored uniform similarity transform plus translation-to-fit.
7. IF evidence alignment applies independent-axis scaling or min-max normalization, THEN THE Evidence_Aligner SHALL reject the aligned result.

### Requirement 32: Mandatory Canonical Construction Chain

**User Story:** As a developer, I want one mandatory construction chain, so that every final artifact has deterministic lineage and ordering.

#### Acceptance Criteria

1. WHEN an approved Plan enters world construction, THE Pipeline_Orchestrator SHALL execute solve → normalize → validate → immutable CameraContract → Constrained_SceneGraph → WorldContract → Relationship_Solve → canonical serialization → Canonical_Hash in the stated order.
2. THE Revision_Controller SHALL assign a nonzero revision to every Approved_Normalized_Metric_Plan.
3. THE CameraContract_Factory SHALL derive the immutable CameraContract after Plan validation and before Constrained_SceneGraph creation.
4. THE SceneGraph_Builder SHALL constrain authoritative spatial values to the Approved_Normalized_Metric_Plan, immutable CameraContract, and approved asset bindings.
5. WHEN the Relationship_Solve completes, THE WorldContract_Builder SHALL serialize the relationship-solved WorldContract deterministically before computing the Canonical_Hash.
6. IF a required construction stage is omitted or reordered, THEN THE Pipeline_Orchestrator SHALL block compilation and classify downstream artifacts as provisional.
7. IF an authoritative value changes after Canonical_Hash creation, THEN THE Revision_Controller SHALL create a new revision and restart the mandatory construction chain.

### Requirement 33: MVP Gates, Compilation Parity, and Finality

**User Story:** As a release owner, I want every correctness gate enforced at the correct stage, so that compilation and publication cannot legitimize an invalid world.

#### Acceptance Criteria

1. THE Publication_Controller SHALL include provenance, containment, overlap/opening/circulation, camera, asset, material, geometry, physics, and semantic validation in the Structural_Gate_Set.
2. THE Publication_Controller SHALL treat every member of the Structural_Gate_Set as an MVP prerequisite for compilation.
3. WHEN the Canonical_Hash is created, THE Publication_Controller SHALL execute the Structural_Gate_Set before compilation.
4. IF any Structural_Gate_Set member fails, THEN THE Publication_Controller SHALL block compilation, final events, and publication with focused diagnostics.
5. WHEN every Structural_Gate_Set member passes, THE Publication_Controller SHALL authorize compilation from the hash-bound WorldContract.
6. WHEN browser and selected-engine compilation complete, THE Publication_Controller SHALL execute the Parity_Gate before final events or publication.
7. THE Parity_Gate SHALL compare Canonical_Hash, Plan revision, CameraContract, room dimensions, solved transforms, asset bindings, material bindings, collision intent, and semantic UUID bindings.
8. IF the Parity_Gate fails, THEN THE Publication_Controller SHALL retain compiled outputs as provisional diagnostic artifacts.
9. WHEN the Structural_Gate_Set and Parity_Gate pass for the same Canonical_Hash and Plan revision, THE Publication_Controller SHALL authorize final events and publication.

### Requirement 34: Durable Identity, Normalization, and Ownership

**User Story:** As an operator, I want resumable single-owner orchestration, so that retries, reloads, and revisions cannot duplicate or corrupt pipeline work.

#### Acceptance Criteria

1. THE Identity_Registry SHALL preserve each stable UUID across evidence, segmentation, approval, regeneration, WorldContract assembly, compilation, replay, and warehouse cataloging.
2. WHEN a Neural_Mesh becomes an Approved_Asset, THE Asset_Normalizer SHALL perform Asset_Normalization exactly once before WorldContract binding.
3. WHEN a resumed stage encounters a normalized Approved_Asset, THE Asset_Normalizer SHALL reuse the recorded normalized binding.
4. WHEN a pipeline stage changes durable state, THE Pipeline_Orchestrator SHALL write a Durable_Checkpoint atomically.
5. WHEN a session resumes with a pending External_Job, THE External_Job_Controller SHALL reconcile the recorded External_Job identity and current service state idempotently.
6. WHEN a newer authoritative revision supersedes pending External_Job work, THE External_Job_Controller SHALL request cancellation of the superseded work.
7. WHEN a Stale_Response arrives, THE External_Job_Controller SHALL quarantine the Stale_Response as diagnostic evidence and preserve the newer revision state.
8. WHEN an upstream Plan, Canon, Object_Canon, mesh, material, or approval revision changes, THE Invalidation_Controller SHALL invalidate and archive every dependent artifact and approval.
9. WHILE a session is active, THE Lease_Manager SHALL permit exactly one valid Worker_Lease to advance the session.
10. WHILE approval state is writable, THE Approval_Manager SHALL permit exactly one Approval_Writer to record decisions for the session.
11. IF an approval references a superseded revision, THEN THE Approval_Manager SHALL classify the approval as stale and block downstream use.

### Requirement 35: Strict Three-View Identity and Fresh Qualification

**User Story:** As a release owner, I want spatially strict cross-view qualification from fresh state, so that prior behavior and superficial similarity cannot qualify a release.

#### Acceptance Criteria

1. WHEN the first-person World render is available, THE Identity_Validator SHALL create a Three_View_Identity_Report from the Plan-derived Blockout or blueprint, Scene_Canon, and first-person World render.
2. THE Three_View_Identity_Report SHALL verify shared Plan revision, CameraContract, shell and opening geometry, stable UUID membership, rotation-aware extents, placement, dimensions, heights, forbidden-overlap status, palette and material intent, and prompt fidelity.
3. THE Identity_Validator SHALL require the Three_View_Identity_Report checks beyond object presence and ordering to produce a GREEN verdict.
4. IF any required Three_View_Identity_Report check fails, THEN THE Identity_Validator SHALL produce a non-GREEN verdict with the mismatched UUID or region and measured discrepancy.
5. IF the Three_View_Identity_Report is non-GREEN, THEN THE Publication_Controller SHALL block final quality approval and publication.
6. WHEN release qualification begins, THE Qualification_Harness SHALL run one Fresh_Zero_State_Run smoke round followed by five fresh headless rounds and five fresh human-like rounds.
7. THE Qualification_Harness SHALL create a brand-new empty session for every qualifying round.
8. THE Qualification_Harness SHALL record source fingerprints, exact artifact hashes, Plan and approval revisions, Canonical_Hash, Parity_Gate result, browser owner, and mocked-or-live status for every qualifying round.
9. IF a qualifying round fails, THEN THE Qualification_Harness SHALL retain the failed round as diagnostic evidence and restart qualification with a new Fresh_Zero_State_Run.
10. WHEN V15_Behavior is observed, THE Qualification_Harness SHALL record V15_Behavior as source-fingerprinted comparative evidence with evidence-only status.
11. THE Release_Decision SHALL accept release evidence only from current-pipeline Fresh_Zero_State_Run rounds that satisfy the Structural_Gate_Set, Parity_Gate, and Three_View_Identity_Report requirements.

### Requirement 36: Append-Only Qualification Evidence and UI V16 Preservation

**User Story:** As a release owner, I want exact immutable qualification evidence and preserved interface versions, so that a V16 release is reproducible without overwriting prior user-visible behavior.

#### Acceptance Criteria

1. FOR every qualification stage and round, THE Qualification_Harness SHALL append an immutable exact evidence record containing the source fingerprints, exact artifact hashes, Plan revision, approval revision, Canonical_Hash, Structural_Gate_Set result, Parity_Gate result, Three_View_Identity_Report result, browser owner, mocked-or-live status, session identity, and timestamp.
2. THE Qualification_Harness SHALL NOT overwrite, edit, delete, merge, or substitute qualification evidence records after they are appended.
3. IF any qualification stage or round fails, THEN THE Qualification_Harness SHALL retain that session's evidence as diagnostic-only, discard the session as release evidence, and restart the entire qualification sequence from a new Fresh_Zero_State_Run.
4. THE Interface_Router SHALL expose the unified pipeline as UI version V16 and SHALL make V16 the default when no version query is supplied.
5. THE Interface_Router SHALL preserve every previously released V3–V15 interface at its existing query selector or route with behavior unchanged; V16 SHALL NOT silently overwrite a prior interface.
6. THE V16 interface SHALL provide clear links for switching to each retained prior interface, and retained interfaces SHALL provide a clear link to V16 where the shared version navigation is available.
7. WHEN a later user-visible interface change is introduced, THE Release_Process SHALL allocate a new interface query version, preserve V16 behavior, and make the new version the default only after its own clean qualification succeeds.
8. BEFORE a V16 release commit, THE Release_Process SHALL create a brand-new empty V16 session, run the exact canonical prompt from Requirement 30.2, and inspect Brief, Plan, Blockout, Canon, World, and Compare stages where applicable.
9. IF any defect appears during the pre-commit V16 run, THEN THE Release_Process SHALL append the defect evidence, fix the cause, discard that session as release evidence, and restart with another brand-new empty V16 session.
10. THE Release_Process SHALL NOT use a restored session, a previous-version session, or a failed session as V16 release evidence.
11. WHEN the clean V16 zero-state sequence and all required fresh rounds pass, THE release commit title SHALL be `feat(web): release v16 interface`, superseding conflicting commit-title language in Requirement 30.7.
12. AFTER the V16 release commit, THE Release_Process SHALL report the clean-version URL, fresh qualifying session URL, exact canonical prompt, and commit hash.