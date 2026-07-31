# Requirements Document

## Introduction

This specification adds amodal completion to the object isolation stage — the ability to complete partially occluded objects via controlled inpainting before mesh generation. The MVP uses raw SAM segmentation directly. This upgrade produces cleaner, more complete Object_Canons with full geometry on hidden sides.

**Prerequisite:** unified-world-pipeline MVP (object isolator working with raw segmentation)

## Glossary

- **Amodal_Completion**: The process of generating plausible hidden portions of a partially occluded object.
- **Object_Canon**: The approved appearance reference for one object — may be original extraction or completed version.
- **Completion_Quality_Gate**: Automated check rejecting blank, fused, or broken inpainting results.

## Requirements

### Requirement 1: Occlusion Detection

#### Acceptance Criteria

1. THE system SHALL detect partial occlusion by analyzing the object mask boundary against the image edge and other object masks.
2. OBJECTS with >15% of their expected boundary touching another mask or image edge SHALL be flagged for completion.
3. THE occlusion analysis SHALL use the object's bounding box vs visible mask area ratio as a confidence metric.

### Requirement 2: Controlled Inpainting

#### Acceptance Criteria

1. FOR flagged objects, THE system SHALL generate a completed version using FLUX inpainting with the visible portion as conditioning.
2. THE inpainting prompt SHALL include the semantic label and material to guide coherent completion (e.g., "complete the hidden legs of a wooden dining chair").
3. THE inpainting SHALL produce an RGBA image on transparent background showing the full object.
4. THE system SHALL generate 2-4 completion candidates and select the best via automated scoring.

### Requirement 3: Completion Quality Gate

#### Acceptance Criteria

1. THE gate SHALL reject completions where: corners are not pure transparent (alpha < 5), subject covers <20% or >80% of frame, a ground shadow band is detected below the subject.
2. THE gate SHALL verify the completed object has reasonable aspect ratio compared to the visible portion (not wildly stretched or compressed).
3. FAILED completions SHALL fall back to raw segmentation (MVP behavior) rather than blocking the pipeline.

### Requirement 4: User Choice

#### Acceptance Criteria

1. THE system SHALL present both the raw extraction and the best completion side-by-side.
2. THE user SHALL choose which version becomes the authoritative Object_Canon.
3. THE choice SHALL be recorded with provenance: which pixels are original vs inpainted.
4. IF the user rejects all completions, raw segmentation SHALL be used.

### Requirement 5: Provenance Tracking

#### Acceptance Criteria

1. THE Object_Canon record SHALL include: original_mask_coverage_pct, was_completed (boolean), completion_prompt, completion_model, selected_candidate_index, approval_timestamp.
2. THE provenance SHALL be sufficient to distinguish "this mesh was generated from a partially visible object" from "this mesh was generated from a fully visible object."
