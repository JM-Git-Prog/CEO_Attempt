# The Level Design Book — Internalization Notes

Source: [https://book.leveldesignbook.com](https://book.leveldesignbook.com)
License: CC BY-NC-SA 4.0 (free to read, non-commercial attribution-sharealike)
Author: Robert Yang et al.
Content rephrased for compliance with licensing restrictions.

## Relevance to Our Workflow

The Level Design Book's process maps almost 1:1 to our six-stage pipeline:

| LDB Phase | Our Stage | Notes |
|---|---|---|
| Pre-production (experience goals, pacing) | BRIEF | User describes intent, LLM interprets mood/era/palette/architecture |
| Layout (parti, bubble diagrams, floor plan) | PLAN | We generate a metric floor plan with items, openings, camera |
| Blockout (massing, metrics, construction) | BLOCKOUT | We render a camera-locked 3D blockout with exact dimensions |
| Art Pass / Lighting / Environment Art | CANON | FLUX.2 resynthesizes materials, textures, lighting onto blockout geometry |
| Scripting / Assembly | WORLD | Scene graph, physics, meshes, Godot project |
| Playtesting / Iteration | COMPARE | User can revise, Compare captures render feedback |

---

## Key Principles Extracted

### 1. Blockout Purpose (directly applicable)
- A blockout is a playable rough draft built with simple 3D shapes, no final art.
- Purpose: prototype, test, and adjust foundational shapes.
- It's cheap to delete/rebuild blockout geometry, expensive to throw away art-passed work.
- Keep it "cheap" until ready to become "expensive."
- You can't playtest a document, but you can playtest a blockout.

**Application:** Our Blockout stage IS the testable 3D draft. The user approves geometry before the expensive Canon art pass. This validates our stage ordering.

### 2. Massing (shape and volume)
- Massing = overall feeling and logic of shape and space.
- Three methods: dimensional (scale/rotate), additive (combine shapes), subtractive (carve).
- Hierarchy: more important masses should be bigger or unusually shaped.
- Readability: clear distinct shapes aid navigation; fragmented massing = camouflage.
- Articulation vs. continuity: separate parts vs unified monolith.

**Application:** Our floor plan items have explicit dimensions, rotation, and category. The blockout renderer draws them as distinct colored boxes with hierarchy (counter is largest, stools are small). We could improve by varying material intensity to communicate hierarchy better.

### 3. Metrics (scale and proportion)
- Player metrics = factual physics (size, speed, jump height).
- Building metrics = suggested dimensions (hallway width, door height, ceiling height).
- Video game scale is weird — it should merely FEEL realistic, not match exact real-world measurements.
- Common modern architecture: doors ~0.9m, hallways ≥2x player width, stairs 30-35°, ceilings 2.4-3m residential.
- Camera height affects perceived scale. Lower camera = things feel bigger.
- FOV affects perceived speed and spatial compression. Our 55° vertical FOV is on the narrow/natural end — good for intimate architectural photography feel.
- Grid textures help estimate distances during blockout.

**Application:** Our metric floor plan uses exact meters. The canonical diner is 6×4×2.8m with a 0.9m door, 4.2m counter, 1024×768 raster at 55° vertical FOV. These all align with LDB's recommended building metrics for a compact interior.

### 4. Wayfinding (navigation aids)
- Wayfinding = how players find where they are (orientation) and route to destination (navigation).
- Hierarchy of aids from subtle (lighting gradient, material change) to direct (walls, locked doors).
- Players form mental maps using: paths, edges, districts, nodes, landmarks.
- "Everything in the game is a wayfinding aid." Walls, stairs, light all convey information.
- Avoid trying to "trick" players — co-create the experience instead.

**Application:** Our scene includes openings (door, window), lighting (three pendants create a warm focal path along counter), and the camera position itself establishes the viewer's orientation in the southeast looking northwest. The Canon should preserve these wayfinding cues.

### 5. Lighting (functional, not just decorative)
- Lighting gives visual depth and helps players gauge distances.
- Four passes: global → wayfinding/critical path → gameplay → detail/mood.
- Motivated light = visible fixture that justifies the light source.
- D6 lighting theory: focal point, focal frame, path, area, combined strategies.
- Three-point (key/fill/rim) has limits in interactive 3D; D6 is better for spatial design.
- Static lighting is better for perf; dynamic enables interactivity.
- Don't use flat solid colors — lose depth/scale cues.

**Application:** Our canonical prompt explicitly specifies two light temperatures (warm amber pendants, cool blue-gray rain light) creating a motivated two-source scheme. The Canon must render these as physically plausible light with shadows and depth — NOT flat colored surfaces. This validates rejecting "dressed-up blockout" results.

### 6. Environment Art / Art Pass (Canon stage)
- An art pass adds visual detail WHILE PRESERVING functionality.
- Work iteratively, don't try 100% on first pass.
- Start big (shapes, palette, themes) → then details.
- Readability: "everything is ivy" — every visual detail has a navigation/legibility function.
- Avoid deeply saturated flat colors; leave space for lighting to work.
- Color coding should be consistent across the level.
- Materials should read clearly as distinct substances.

**Application:** The Canon art pass (FLUX.2 conditioned generation) must:
- Preserve blockout geometry (counter, stools, pendants, door, window).
- Replace flat blockout colors with physically realistic materials.
- Maintain readable silhouettes and proportions.
- Add atmospheric lighting consistent with described sources.
- NOT introduce new objects or change layout.

### 7. The Process Is Iterative
- Layout → Blockout → Playtest → Diverge → Iterate → Playtest again.
- "99% of the time, your blockout will not survive a playtest."
- Plans are communication tools, not magic. The player never plays the drawing.
- Keep an open mind about what playtests tell you.

**Application:** Our Compare stage enables this iteration loop: user captures a World render, feeds back, scene graph is revised, assets regenerated. The revision_history records each cycle.

### 8. Construction Methods
Five approaches: primitives, brushes/modeling, modular kit, sculpting, splines.
- Our pipeline uses **primitives** (trimesh boxes, cylinders, capsules) for the blockout/world.
- Could introduce **modular kit** thinking for future tile-based construction.
- The LDB strongly recommends building in-engine and playtesting immediately — aligns with our World viewer.

### 9. Against Over-Engineering
- "Metrics are not magic." Don't believe any single method is foolproof.
- Shape psychology is "99% bullshit" — don't rely on abstract universal meaning of shapes.
- Plans become obsolete; blockouts are the truth.
- Some projects (narrative exploration) gain less from blockout and more from vertical slice.

**Application:** Our six-stage workflow with retained artifacts and immutable snapshots provides auditability without over-constraining the creative loop. The user can always revise.

---

## Direct Integration Opportunities

1. **Blockout textures**: LDB recommends grid/checkerboard textures to help gauge scale. Our canonical prompt already uses "glossy black-and-cream checkerboard linoleum floor" — this serves double duty as both an aesthetic choice and a spatial reference grid.

2. **Scale figures**: LDB recommends placing human-sized reference figures during blockout. We could add a ghost-scale figure in the blockout render for metric verification (height markers, clearance check).

3. **Modular kit thinking**: For the World stage asset generation, thinking in terms of reusable modular pieces (wall panels, counter segments, stool bases) could improve mesh quality without bespoke modeling per object.

4. **D6 lighting in scene graph**: Currently our SceneLight uses type/position/color/intensity. We could annotate lights with their D6 strategy (focal point, path, area) to guide both generation and revision.

5. **Wayfinding validation**: After World generation, a post-check could verify that key landmarks (counter, door, window) are visible from the camera contract position, matching the reference_landmarks in the contract.

6. **Paintover / Compare workflow**: The Compare stage is essentially a "paintover feedback" loop — user sees the world render, provides text revision, and the system iterates. This exactly matches professional environment art workflows.

---

## Source Attribution

All principles derived from The Level Design Book by Robert Yang et al.
Available at https://book.leveldesignbook.com under CC BY-NC-SA 4.0.
Content was rephrased for compliance with licensing restrictions.
