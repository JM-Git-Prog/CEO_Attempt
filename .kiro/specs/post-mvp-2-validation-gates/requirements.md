# Requirements Document

## Introduction

This specification adds the 5 remaining pre-publication validation gates that were deferred from the MVP. The MVP ships with 3 core gates (geometry, physics, semantic). This spec adds provenance, circulation, material, asset integrity, and cross-runtime parity verification.

**Prerequisite:** unified-world-pipeline MVP (3 core gates working, WorldContract hash stable)

## Glossary

- **Provenance_Gate**: Verifies unbroken evidence → intent → plan → contract chain with nonzero revisions.
- **Circulation_Gate**: Verifies minimum walkable path clearance (≥0.6m) between all required navigation points.
- **Material_Gate**: Verifies every mesh has verifiable material or is honestly labeled degraded.
- **Asset_Gate**: Verifies every final mesh has SHA-256 digest matching the registry binding.
- **Parity_Gate**: Verifies browser and compiled engine outputs derive from the same WorldContract hash.

## Requirements

### Requirement 1: Provenance Gate

#### Acceptance Criteria

1. THE gate SHALL verify nonzero evidence provenance revision exists.
2. THE gate SHALL verify nonzero approved plan revision exists.
3. THE gate SHALL verify an unbroken chain: evidence → intent → plan → contract.
4. FAILURE SHALL identify which link in the chain is broken or missing.

### Requirement 2: Circulation Gate

#### Acceptance Criteria

1. THE gate SHALL verify all required circulation paths have ≥0.6m clearance.
2. THE gate SHALL check: room entry to every object, door swing clearance, exit accessibility.
3. FAILURE SHALL identify the specific path segment and its measured clearance.
4. THE gate SHALL use a 2D floor-plane projection for pathfinding (not full 3D navigation mesh).

### Requirement 3: Material Gate

#### Acceptance Criteria

1. THE gate SHALL verify every mesh in the WorldContract has at least one verifiable material.
2. MESHES with Pass 1 only (no PBR) SHALL be labeled "degraded" but still pass.
3. MESHES with NO material (missing texture, corrupted GLB) SHALL fail.
4. FAILURE SHALL identify the specific mesh and what material data is missing.

### Requirement 4: Asset Integrity Gate

#### Acceptance Criteria

1. THE gate SHALL verify every final mesh file exists at its declared path.
2. THE gate SHALL verify SHA-256 of each file matches the registry binding.
3. THE gate SHALL verify positive triangle count for each mesh.
4. FAILURE SHALL identify the specific asset, expected vs actual hash, and file status.

### Requirement 5: Cross-Runtime Parity Gate

#### Acceptance Criteria

1. THE gate SHALL verify browser payload carries the same WorldContract hash as compiled engine output.
2. THE gate SHALL verify equivalent: camera values, room dimensions, instance transforms, asset bindings.
3. TOLERANCE: position differences <1e-3m, rotation <0.01 radians.
4. FAILURE SHALL identify which runtime diverges and on which specific value.
