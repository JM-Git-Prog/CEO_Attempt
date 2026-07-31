# Requirements Document

## Introduction

This specification adds the remaining architectural finish elements deferred from the MVP: crown molding, wainscoting/chair rails, vent covers, ceiling treatments, and advanced trim profiles. The MVP ships baseboards, door/window frames, casing, and outlet/switch decals. This upgrade completes the "down to the last molding" product promise.

**Prerequisite:** unified-world-pipeline MVP (finish pass working with basic primitives)

## Glossary

- **Crown_Molding**: Decorative trim at the wall-ceiling junction, profile varies by era.
- **Wainscoting**: Lower wall paneling treatment, typically 32-36 inches high.
- **Chair_Rail**: Horizontal molding at chair-back height, separating upper and lower wall treatments.
- **Vent_Cover**: HVAC return/supply grille, placed per building code at floor or ceiling level.
- **Ceiling_Treatment**: Era-appropriate ceiling finish — pressed tin, coffered, tray, popcorn, smooth.

## Requirements

### Requirement 1: Crown Molding

#### Acceptance Criteria

1. THE system SHALL place crown molding at the wall-ceiling junction when the Art_Bible era demands it.
2. PROFILE selection SHALL be era-appropriate: ogee for Victorian, cove for mid-century, simple quarter-round for modern.
3. THE molding SHALL be generated as a 2D profile swept along the room perimeter, mitered at corners.
4. THE molding SHALL NOT be placed where walls meet openings (doors, windows) — it stops at casing.

### Requirement 2: Wainscoting and Chair Rails

#### Acceptance Criteria

1. WHEN the Art_Bible specifies wainscoting, THE system SHALL place panel geometry on the lower wall (default 36 inches height).
2. PANEL style SHALL be era-appropriate: raised panel for traditional, flat panel for Craftsman, beadboard for cottage.
3. A chair rail cap SHALL be placed at the top of the wainscoting.
4. WAINSCOTING SHALL wrap corners and terminate cleanly at openings.

### Requirement 3: Vent Covers

#### Acceptance Criteria

1. THE system SHALL place vent covers at code-appropriate positions (floor return near exterior walls, ceiling supply near interior).
2. VENT cover geometry SHALL be a flat rectangle with a louvered texture/material.
3. MAXIMUM 2 vents per room for MVP (one supply, one return).
4. PLACEMENT SHALL not conflict with baseboards or furniture.

### Requirement 4: Ceiling Treatments

#### Acceptance Criteria

1. THE system SHALL apply era-appropriate ceiling treatment as specified by the Art_Bible.
2. SUPPORTED treatments: smooth (modern), pressed tin (Victorian/industrial), coffered (traditional), exposed beam (rustic).
3. THE ceiling mesh SHALL receive appropriate material/texture from the Art_Bible palette.
4. BEAMS and coffers SHALL be procedural box geometry placed at regular intervals.

### Requirement 5: Advanced Trim Profiles

#### Acceptance Criteria

1. THE system SHALL support at least 6 trim profiles: ogee, cove, quarter-round, flat/square, dentil, and egg-and-dart.
2. PROFILES SHALL be stored as 2D polyline definitions and swept along placement paths.
3. THE user SHALL be able to override era-default profiles via conversation ("I want more ornate trim").
4. PROFILE resolution SHALL be configurable: 8 segments for performance, 16 for quality.
