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
- Demo proving ground: the hash-bound photoreal Golden Room reference defined in Requirement 38; later release qualification remains the exact fresh Danny's kitchenette prompt in Requirement 30.2.

## Glossary

- **Dream_Preview**: A provisional, non-authoritative mood image shown during conversation to enable visual steering. Never controls geometry.
- **Brief**: The structured interpretation of user intent — purpose, atmosphere, era, palette, objects, GAME concept, REAL capabilities.
- **Art_Bible**: Style reference derived from conversation — materials, palette, era exclusions, lighting direction.
- **Metric_Plan**: The validated, solver-approved spatial layout — rooms, walls, openings, placements, circulation, clearances.
- **Blockout**: A 3D render of the validated Plan from the immutable CameraContract, showing geometry before expensive art.
- **Scene_Canon**: The final approved photorealistic image conditioned on approved Blockout. Owns appearance, not geometry.
- **Golden_Room_Appearance_Reference**: The immutable Demo Profile appearance/composition evidence binding the authoritative photoreal source image hash to the original Comfy workflow hash. It guides visual convergence but cannot authorize dimensions, transforms, openings, collision, navigation, or camera.
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


### Requirement 37: Non-Authoritative Canon-to-Geometry Diagnostic Spike

**User Story:** As a pipeline owner, I want one bounded local diagnostic of a Canon-to-video-to-object-geometry path, so that I can decide whether it improves visual quality without weakening authority, release, or qualification gates.

#### Acceptance Criteria

1. THE Diagnostic_Harness SHALL use session `11bdb38d-9064-4633-ab3b-09673f70c36d` Canon and Brief only as immutable diagnostic inputs, SHALL NOT resume that session's pipeline, and SHALL permanently classify every derived artifact as non-authoritative and release-ineligible.
2. BEFORE implementation or GPU execution, THE Capability_Preflight SHALL inventory Comfy Desktop node classes, locally installed models, Depth Anything adapter availability, Hunyuan availability, GPU/process ownership, and exact source hashes without downloading models or using cloud services; any required missing or incompatible capability SHALL stop the chain with exact evidence.
3. IF locally executable, THE MiniMax_H3 stage SHALL preserve the 1024x768 Canon aspect ratio and produce one continuous approximately five-second camera move with no cuts, object movement, count/identity drift, architecture/opening drift, material/lighting instability, implausible camera jumps, or morphing, while preserving the exact fixed inventory. The optional 8-step turbo model MAY produce draft evidence only; accepted diagnostic video SHALL use the locally available 20-step path.
4. THE Temporal_Gate SHALL sample 8-12 frames, persist each frame hash and explicit accepted/rejected checks, and SHALL expose 8-16 stable frames only when every sampled-frame count, identity, architecture/opening, material/lighting, camera-continuity, and morphing check passes.
5. FOR stable frames only, THE Diagnostic_Harness SHALL invoke the existing Depth Anything adapter where locally available and persist depth maps, camera estimates, confidence, masks, and tracking bound to the five Brief UUID assets: round table, chair-1, chair-2, counter, and coffee maker.
6. FOR each required UUID, THE Diagnostic_Harness SHALL produce or explicitly reject an RGB-D/colored point cloud and record observed coverage, a single uniform scale anchor, silhouette reprojection, depth reprojection, color reprojection, and accepted/rejected status; per-axis scaling and min-max normalization are forbidden.
7. WHERE observed coverage and remaining time permit, THE Diagnostic_Harness MAY run local coverage-aware Hunyuan candidate generation/completion sequentially; every candidate counted as successful SHALL load independently and pass a standalone neutral-view/turntable validation. Placeholder geometry and temporary-material assets SHALL NOT count as successful candidates.
8. THE approved normalized Metric_Plan SHALL remain the sole authority for dimensions, transforms, placement, architecture, openings, collision, navigation, and CameraContract derivation. Generated video motion, estimated camera/depth, masks, bounding boxes, point clouds, and candidate meshes SHALL remain evidence only and SHALL NOT authorize any spatial value.
9. THE Resource_Arbiter SHALL permit only one substantial GPU owner at a time, unload Ollama before MiniMax or Hunyuan GPU work, use the Comfy Desktop owner already serving port 8188, and SHALL NOT launch or retain ComfyUI or the Windows-owned Ratchet watch in an agent-managed terminal.
10. THE Diagnostic_Harness SHALL persist seeds, model/workflow identities and hashes, input/output hashes, source fingerprint, frame/mask/depth/camera/point-cloud/candidate evidence, per-stage verdicts, and explicit outcomes for all five UUIDs in one deterministic non-authoritative evidence bundle.
11. THE diagnostic verdict SHALL be `SUCCESS` only when the complete chain and evidence bundle exist, all five UUIDs have clear outcomes, and at least one independently validated high-quality non-placeholder object candidate passes neutral-view/turntable validation; otherwise it SHALL report `PARTIAL` or `FAILURE` with the exact furthest completed stage, measured metrics, artifacts, blocker, and an integrate/revise/reject recommendation.
12. THIS diagnostic SHALL remain non-blocking unless later evidence proves production viability; it SHALL NOT complete or qualify Task 11.7, create release evidence, activate Tasks 11.9-11.10, weaken existing gates, alter any released interface, or authorize a commit.
13. THE final decision record SHALL state whether the observed setup and execution cost still supports the governing 6-8 active-coding-hour end-to-end MVP target; non-blocking polish and tooling SHALL be deferred when they threaten that target.


## Corrective Requirements Tranche — Hash-Bound Golden Room Demo and Qualification Order

### Normative Precedence

This additive document-only correction supersedes conflicting kitchenette-as-demo, fixed-chair, and five-kitchenette-asset clauses in the Core Principles and Requirements 10, 26, 30, and 35–42. It does not alter the exact kitchenette Release Profile prompt, weaken MetricPlan spatial authority, canonical hashing, structural/parity gates, exact-fingerprint validation, fresh release qualification, append-only failed-session evidence, or V3–V16 preservation. It authorizes no live session, UI/version change, implementation completion claim, asset generation, model download, or commit.

### Corrective Tranche Glossary

- **Golden_Room_Appearance_Reference**: The immutable Demo Profile tuple binding authoritative image `C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png` at SHA-256 `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6` to original Comfy workflow `C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json` at SHA-256 `0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196`. The mirrored image `C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png` is accepted only while its SHA-256 is the same `dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6`; any mismatch fails closed and must be documented before Demo work proceeds.
- **Golden_Room_Hero_Manifest**: Exactly five independently approved UUID-bound hero assets: recliner, refrigerator, CRT television, wooden TV stand, and bookshelf.
- **Golden_Room_Fidelity_Inventory**: The five hero assets plus ceiling fan, wall mirror, area rug, telephone side table, table lamp, foreground sofa, trophy shelf/trophies, and paintings; and the recognizable long warm room, wood-plank floor, cream walls, rear and right wooden doors, right-side street-facing window, warm lamp/daylight balance, and approved camera composition.
- **StandaloneAssetGate**: A fail-closed visual gate proving that one hero asset loads independently, has non-placeholder geometry and durable non-temporary materials, passes a neutral turntable review, and receives explicit human approval.
- **SceneVisualGate**: A fail-closed whole-room visual gate proving that the Golden_Browser_Room is immediately recognizable as the Golden_Room_Appearance_Reference from the approved Plan-derived camera and remains visually coherent from at least one navigable first-person viewpoint, without claiming pixel identity from navigable views.
- **Golden_Browser_Room**: The photo-bound Demo Profile Browser assembly built from the approved MetricPlan, immutable CameraContract, geometry-conditioned final Scene_Canon, five StandaloneAssetGate-approved hero assets, and complete Golden_Room_Fidelity_Inventory.
- **Demo_Ready**: A non-release milestone proving the photo-bound Golden_Browser_Room is visually green, playable, and demonstrates one functional GAME interaction plus one working REAL read-only binding, all bound to one exact candidate fingerprint and the Golden_Room_Appearance_Reference hashes.
- **Release_Ready**: A distinct later milestone proving fresh prompt-driven generalization with the exact kitchenette Release Profile prompt, a clean replacement Task 11.7.1 run, and all fresh repeated qualification required by Tasks 11.9–11.11.
- **Platform_Complete**: Broader completion of deferred production, GAME, REAL, engine, and polish capabilities; it is not implied by Demo_Ready or Release_Ready.
- **Diagnostic_Profile**: Non-authoritative investigation that may inspect or reuse existing evidence and approved assets but can never create Demo_Ready or release evidence.
- **Demo_Profile**: The bounded photo-bound visual-integration profile that may reuse explicitly approved warehouse assets to reproduce and evaluate the Golden_Room_Appearance_Reference.
- **Fresh_Benchmark_Profile**: A fresh-generation benchmark profile that does not consult or reuse prior-session warehouse assets before generation.
- **Release_Profile**: The strict fresh zero-state prompt-driven qualification profile; every qualifying asset is newly generated for its qualifying session and no prior-session asset may substitute for fresh evidence.

### Requirement 38: Golden Room Critical Path, Immutable Reference, and Product Stage Order

**User Story:** As a product owner, I want visual quality proven against one immutable photoreal room before repeated release qualification, without letting the reference image replace spatial authority.

#### Acceptance Criteria

1. THE Pipeline_Team SHALL execute the active visual-first critical path in this exact order: focused counter/cabinet regression repair and exact-fingerprint revalidation → general exploratory-geometry freeze → bounded local WorldMirror 2.0 documentation/preflight/feasibility gate → fixed-recliner bake-off → common-gate lane selection → five Golden_Room_Hero_Manifest approvals → Golden_Browser_Room → SceneVisualGate plus playability plus one functional GAME interaction plus one REAL binding → Demo_Ready record → replacement clean Task 11.7.1 → Tasks 11.9–11.11.
2. THE product pipeline SHALL preserve Prompt → Dream_Preview → MetricPlan solve/validation and Blockout approval → geometry-conditioned final Scene_Canon → object production.
3. BEFORE Demo Profile object production, THE Source_Reference_Controller SHALL bind the exact authoritative image and workflow paths and hashes in Golden_Room_Appearance_Reference and SHALL confirm that the ComfyUI-Shared image mirror hashes identically; missing or mismatched evidence SHALL fail closed with a documented blocker.
4. THE Golden_Room_Appearance_Reference SHALL control appearance, identity, set-dressing inventory, lighting balance, and composition evidence only; it SHALL NOT authorize dimensions, transforms, placement, architecture, openings, collision, navigation, or camera.
5. THE approved normalized MetricPlan SHALL remain the sole spatial authority, and the immutable CameraContract SHALL remain derived only from that approved MetricPlan.
6. THE geometry-conditioned final Scene_Canon SHALL derive framing and spatial conditioning from the approved MetricPlan, approved Blockout, and immutable CameraContract, then converge visually on Golden_Room_Appearance_Reference without importing it as a Canon or granting it spatial authority.
7. BEFORE the fixed-recliner bake-off, THE Task_11_8_Repair SHALL correct the counter/cabinet semantic observation defect and revalidate the repaired candidate against its exact fingerprint; this regression prerequisite SHALL NOT make counter/cabinet a Golden_Room_Hero_Manifest asset.
8. AFTER the repair is validated, THE Pipeline_Team SHALL freeze general exploratory geometry and SHALL NOT begin new MiniMax, Depth Anything 3, MoGe, Anima, HY-Pano, WorldNav, WorldStereo, MoVerse, One2Scene, or other open-ended model downloads or integrations on this critical path; the only bounded exception SHALL be the user-selected WorldMirror 2.0 gate in Requirement 43, whose preflight authorizes no installation or download.
9. THE fixed-recliner bake-off SHALL compare only a raw object crop, the existing Qwen amodal completion, and a video-depth input only when that video-depth evidence is already locally available at bake-off start.
10. THE fixed-recliner bake-off SHALL have a fixed 60–90 minute active execution budget; when the budget expires, THE Pipeline_Team SHALL evaluate completed lanes and proceed without extending model exploration.
11. THE Pipeline_Team SHALL apply one identical StandaloneAssetGate rubric to every completed recliner lane and select the visually best passing lane.
12. THE Pipeline_Team SHALL NOT start a replacement fresh Task 11.7.1 session before Demo_Ready is recorded for the exact candidate fingerprint; photo-bound Demo_Ready SHALL remain distinct from prompt-driven Release_Ready.

### Requirement 39: Fail-Closed Standalone and Golden Room Scene Visual Gates

**User Story:** As a user, I want the hero assets and assembled room to reproduce the source room convincingly before the photo-bound demo is called ready.

#### Acceptance Criteria

1. THE StandaloneAssetGate SHALL require a hero asset to load independently without scene-only dependencies, missing buffers, or unresolved external materials.
2. THE StandaloneAssetGate SHALL reject placeholder geometry, fused room or ground-sheet geometry, temporary materials, and Pass-1-only materials that have not been approved as durable final demo materials.
3. THE StandaloneAssetGate SHALL require neutral multi-angle turntable evidence that exposes silhouette, topology, object identity, material continuity, and obvious reconstruction artifacts.
4. THE StandaloneAssetGate SHALL require explicit human approval bound to the asset hash, source lane, candidate fingerprint, Golden_Room_Appearance_Reference hashes, and gate evidence.
5. THE common recliner bake-off rubric SHALL score every lane on the same independent-load, silhouette/identity, artifact, and durable-material criteria; lane-specific exceptions SHALL NOT convert a failure into a pass.
6. THE Demo_Profile SHALL produce or permissibly reuse and pass StandaloneAssetGate for exactly five UUID-bound Golden_Room_Hero_Manifest assets: recliner, refrigerator, CRT television, wooden TV stand, and bookshelf.
7. THE SceneVisualGate SHALL require every Golden_Room_Fidelity_Inventory element: ceiling fan, wall mirror, area rug, telephone side table, table lamp, foreground sofa, trophy shelf/trophies, paintings, and all five hero assets.
8. THE SceneVisualGate SHALL require the recognizable shell and composition: a long warm room, wood-plank floor, cream walls, rear and right wooden doors, right-side street-facing window, warm lamp/daylight balance, and the approved Plan-derived camera composition.
9. SET dressing MAY use approved, procedural, or non-hero assets, but no mandatory element MAY be missing, represented by a gross placeholder, fused into a scene remnant, or rendered in a way that breaks its visual identity.
10. WHEN all five hero assets are approved and the full fidelity inventory is available, THE Browser_Assembler SHALL build one Golden_Browser_Room from the approved MetricPlan, immutable CameraContract, approved geometry-conditioned Scene_Canon, hash-bound hero assets, and set dressing.
11. THE SceneVisualGate SHALL verify Plan-consistent shell/openings/transforms/dimensions, recognizable hero silhouettes, complete fidelity inventory, durable material completeness, Golden_Room_Appearance_Reference-consistent appearance/composition/lighting intent, and absence of placeholders, fused remnants, and temporary Pass-1-only materials.
12. THE final room SHALL be immediately recognizable as the source room from the approved camera and SHALL still hold up from at least one navigable first-person viewpoint; first-person review SHALL assess identity and coherence, not pixel identity.
13. IF StandaloneAssetGate or SceneVisualGate fails, THEN THE Demo_Readiness_Controller SHALL block Demo_Ready even when structural, hash, compilation, parity, or automated semantic gates pass.
14. STRUCTURAL gate success SHALL NOT compensate for a visual gate failure, and visual gate success SHALL NOT compensate for a structural gate failure.

### Requirement 40: Photo-Bound Demo Ready, Minimal GAME/REAL Proof, and Readiness Separation

**User Story:** As a product owner, I want an honest photo-bound demo milestone distinct from fresh prompt-driven release qualification and platform completion.

#### Acceptance Criteria

1. THE Demo_Readiness_Controller SHALL record Demo_Ready only when the five Golden_Room_Hero_Manifest StandaloneAssetGate records and one GREEN SceneVisualGate record reference the same Golden_Browser_Room, candidate fingerprint, Golden_Room_Appearance_Reference hashes, Plan revision, and Canonical_Hash where available.
2. THE Golden_Browser_Room SHALL be playable with first-person entry, movement, collision, and a safe spawn sufficient to inspect every hero asset and mandatory set-dressing region.
3. THE Demo_Profile SHALL include at least one functional GAME interaction in which a user action on a stable UUID-bound object changes persistent room GAME state, produces visible success or progress feedback, and can be observed during the same demo.
4. THE Demo_Profile SHALL retain at least one working REAL read-only binding that displays bound data on a stable UUID-bound surface without changing geometry or materials.
5. THE GAME interaction and REAL binding SHALL coexist with the same approved visuals; switching behavior overlays SHALL NOT replace, hide, or restyle the hero assets or mandatory set dressing.
6. THE Demo_Ready record SHALL include the exact candidate fingerprint, profile, authoritative source image path/hash, mirrored-image verification, workflow path/hash, five hero asset hashes and approvals, full fidelity-inventory verdict, SceneVisualGate evidence, playability verdict, GAME interaction evidence, REAL binding evidence, Plan revision, Canonical_Hash where available, and timestamp.
7. Demo_Ready SHALL NOT be represented as Release_Ready, fresh qualification evidence, or Platform_Complete; it proves faithful reproduction of one immutable photo-bound Golden Room.
8. Release_Ready SHALL prove separate fresh prompt-driven generalization and SHALL require Demo_Ready plus the exact-prompt replacement clean Task 11.7.1 run and every fresh round and release checkpoint in Tasks 11.9–11.11.
9. Platform_Complete SHALL remain a separate post-MVP state requiring completion of explicitly deferred platform capabilities.

### Requirement 41: Explicit Execution Profiles and Controlled Warehouse Reuse

**User Story:** As a release owner, I want each run's reference, freshness, and reuse policy declared, so that a photo-bound demo can reuse approved work without contaminating fresh release evidence.

#### Acceptance Criteria

1. BEFORE object production, THE Pipeline_Orchestrator SHALL record exactly one immutable profile: diagnostic, demo, fresh-benchmark, or release.
2. THE Diagnostic_Profile MAY inspect or reuse prior evidence and approved assets but SHALL mark every output non-authoritative and ineligible for Demo_Ready and release qualification.
3. THE Demo_Profile SHALL bind Golden_Room_Appearance_Reference and MAY reuse only warehouse assets with verified hashes, durable material bindings, explicit human approval, and a passing StandaloneAssetGate; every reused binding SHALL be recorded.
4. THE Fresh_Benchmark_Profile SHALL generate fresh candidate assets without pre-generation warehouse lookup or substitution and SHALL report benchmark results separately from Demo_Ready and release evidence.
5. THE Release_Profile SHALL preserve the always-fresh rule: no pre-generation similarity lookup, warehouse substitution, restored asset, or prior-session asset may count as qualifying evidence.
6. PROFILE selection SHALL NOT weaken MetricPlan authority, exact-fingerprint validation, structural gates, parity, SceneVisualGate, append-only provenance, stable UUID binding, or source-hash verification.
7. IF a run changes profile or immutable appearance reference, THEN THE Pipeline_Orchestrator SHALL create a new run identity; it SHALL NOT relabel existing evidence.

### Requirement 42: Regression Prerequisite, Failed-Session Retention, and Release Dependencies

**User Story:** As a release owner, I want the preserved semantic regression fixed and failed smoke evidence retained while prompt-driven qualification waits for a real photo-bound Demo Ready milestone.

#### Acceptance Criteria

1. THE Qualification_Harness SHALL retain every failed Task 11.7 session and its artifacts append-only as permanently ineligible diagnostic evidence.
2. THE Pipeline_Team SHALL NOT resume, restore, clone, repair in place, or otherwise use a failed Task 11.7 session as Demo_Ready or release evidence.
3. Task 11.8.1 SHALL repair the counter/cabinet semantic defect, add or update focused regression coverage, and revalidate the affected candidate fingerprint, but counter/cabinet SHALL NOT appear in the Golden_Room_Hero_Manifest and the repair SHALL NOT start a replacement qualification session.
4. ONLY AFTER photo-bound Demo_Ready is recorded SHALL the Qualification_Harness create the replacement Task 11.7.1 session as a brand-new empty V16 Release_Profile session.
5. THE replacement Task 11.7.1 session and every qualifying round in Tasks 11.9–11.11 SHALL submit exactly: `Danny's kitchenette — a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain.`
6. THE exact canonical prompt SHALL remain 142 UTF-8 bytes with SHA-256 `af6759e5d516561fad3fb49b129f02ad27743e273d1345173d59430f462f32ec`; any byte change SHALL fail release qualification.
7. Tasks 11.9 and 11.10 SHALL remain inactive until photo-bound Demo_Ready and one clean prompt-driven replacement Task 11.7.1 pass both exist for the same exact candidate fingerprint.
8. Task 11.11 SHALL remain inactive until Tasks 11.9 and 11.10 complete with eligible fresh evidence.
9. THE correction SHALL preserve V3–V16 behavior, existing selectors/routes, shared version navigation, unrelated working-tree changes, Windows ownership of the Ratchet watch, Comfy Desktop ownership of port 8188, and the prohibition on agent-owned long-running service processes.
10. NO document-only correction SHALL start a live session, generate an asset, download or integrate a model, change production or test code, change a user-visible interface or version, mark implementation tasks complete, authorize a commit, or claim Demo_Ready or Release_Ready.


## Corrective Requirements Tranche — Bounded HY-World 2.0 WorldMirror Feasibility Gate

### Normative Precedence

This additive document-only correction supersedes only conflicting critical-path and exploratory-freeze clauses in Requirements 38 and 42. It inserts one bounded local WorldMirror 2.0 feasibility gate before the fixed-recliner bake-off. It does not authorize installation, download, cloud use, service or session startup, asset generation, implementation completion, UI/version change, or commit.

### Requirement 43: WorldMirror-First Local Feasibility Without Authority Transfer

**User Story:** As a product owner, I want to test the smallest official HY-World 2.0 reconstruction component against the hash-bound Golden Room before continuing per-object reconstruction, so that a useful persistent-world backend can be adopted without mistaking it for the product architecture or weakening MetricPlan authority.

#### Acceptance Criteria

1. THE Architecture_Record SHALL state that HY-World 2.0 and the Unified World Pipeline address the same broad persistent and navigable 3D-asset category, while the Unified World Pipeline additionally owns conversation, Brief and ArtBible derivation, Plan-owned metric authority, deterministic WorldContract construction, per-object warehouse provenance, human approval gates, engine-neutral compilation, and persistent GAME and REAL overlays; HY-World SHALL remain a reconstruction or generation backend candidate rather than the product architecture or an authority source.
2. THE Capability_Record SHALL state that official HY-World 2.0 supports text, single-image, multi-view, and video inputs and can produce persistent 3DGS or mesh outputs; full worldgen is HY-Pano 2.0 → WorldNav → WorldStereo 2.0 → WorldMirror 2.0 plus 3DGS, while WorldMirror 2.0 is the bounded approximately 1.2B-parameter feed-forward multi-view or video reconstruction target.
3. BEFORE any WorldMirror installation, download, native build, or GPU execution, THE WorldMirror_Preflight SHALL inspect the official license and redistribution terms; inventory disk, VRAM, RAM, CUDA, Python, compiler, and native-build requirements; estimate and record exact anticipated repository, model, dependency, environment, cache, and output storage; confirm that no Golden Room evidence, project data, telemetry, or inference leaves the local machine; and define reversible environment isolation plus fixed setup, storage, and 60-minute maximum active feasibility budgets.
4. THE WorldMirror_Preflight SHALL NOT authorize installation or download. A later implementation step MAY install or download WorldMirror dependencies or weights only after the user explicitly confirms the measured size, storage budget, license finding, local-only data path, reversible isolated-environment plan, and cleanup procedure.
5. WHEN explicitly authorized later, THE WorldMirror_Gate SHALL receive only local Golden_Room_Appearance_Reference evidence and SHALL treat candidate depth, normals, cameras, point clouds, 3DGS, TSDF, and meshes as non-authoritative visual or geometry evidence with recorded provenance.
6. THE approved normalized MetricPlan SHALL remain the sole authority for dimensions, transforms, placement, architecture, openings, collision, navigation, and CameraContract derivation; no WorldMirror camera, depth, normal, point cloud, 3DGS, TSDF, or mesh value SHALL silently replace or rescale Plan-owned values.
7. A WorldMirror TSDF or mesh MAY become a visual or collision candidate only after explicit alignment, validation, contract binding, applicable structural and visual gates, and human approval; absent those approvals it SHALL remain non-colliding evidence and SHALL NOT replace Plan architecture.
8. AFTER explicit installation approval, THE WorldMirror_Gate SHALL enforce one RTX 4090, one substantial GPU owner, safe process ownership, and a maximum of 60 active minutes for the feasibility attempt; it SHALL stop rather than expanding resources, stages, or models when the budget expires.
9. THE WorldMirror_Gate SHALL pass only if: the environment is reversibly isolated; WorldMirror loads locally or an official reduced-memory or offload mode is documented and viable on the 24GB GPU; one bounded Golden Room reconstruction completes without OOM or unsafe process ownership; an output loads locally; approved-camera resemblance and at least one novel-view coherence are materially better than the current source-only or depth evidence; no placeholder or cloud demo substitutes for execution; and source/input/output hashes, provenance, commands/configuration, timing, peak VRAM, peak RAM, and disk use are recorded.
10. THE WorldMirror_Gate SHALL fail or defer if official execution requires multi-GPU-only stages; WorldMirror exceeds 24GB VRAM without an official viable reduced-memory or offload mode; setup, active-time, or storage budgets are exceeded; CUDA, Python, compiler, or native-build compatibility fails; license or redistribution terms block intended use; local-only execution cannot be guaranteed; the output cannot load locally; or the result is not materially useful against the stated visual criteria.
11. IF the WorldMirror_Gate fails or defers, THEN THE Pipeline_Team SHALL freeze WorldMirror immediately, preserve its evidence and exact blocker, and return directly to the existing fixed-recliner bake-off without expanding into HY-Pano, WorldNav, WorldStereo, MoVerse, One2Scene, or unrelated model exploration.
12. Full HY-World 2.0 worldgen SHALL remain deferred and off the active critical path because official guidance recommends at least four GPUs, reports testing on eight H20 GPUs, and uses an external vLLM service; it MAY later be evaluated as an optional remote or high-end backend, but no cloud or external data transmission is permitted without explicit user permission.
13. PASS, FAIL, or DEFER evidence SHALL bind the exact Golden Room source image and workflow hashes, candidate fingerprint, environment identity, license finding, measured storage, model and dependency identities, execution mode, local-only verification, metrics, output hashes, visual comparison, and recommendation; it SHALL remain diagnostic until separately approved and SHALL NOT by itself establish StandaloneAssetGate, SceneVisualGate, Demo_Ready, Release_Ready, or Platform_Complete.
14. THIS document-only correction SHALL preserve the exact Golden Room image, mirror, and workflow hashes; five hero assets and complete fidelity inventory; counter/cabinet regression prerequisite; Demo and Release distinction; exact kitchenette prompt bytes and hash; V3–V16 behavior; failed-session retention; process ownership; no-session rule; and no-commit rule.
