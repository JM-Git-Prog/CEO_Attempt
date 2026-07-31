# Requirements Document

## Introduction

This specification defines the full GAME mode implementation — the AI-driven persistent game system that transforms any room into a playable experience. It depends on the unified-world-pipeline MVP being complete (stable WorldContract, mode toggle working, GameOverlay data model defined).

**Prerequisite:** unified-world-pipeline MVP (toggle works, GAME stub returns theme suggestion)

## Glossary

- **GameOverlay**: Per-room behavior bindings that assign gameplay roles to stable object identities.
- **GameConcept**: The AI-generated game design including theme, mechanics, scoring, and win condition.
- **ObjectRole**: A gameplay binding that assigns function to a WorldContract object by UUID (e.g., desk → puzzle surface).
- **GameState**: Persistent per-room progress including score, unlocks, completed objectives, and active rules.
- **RemodePatch**: The AI-generated repair that re-homes affected game bindings when room geometry changes.

## Requirements

### Requirement 1: AI Game Concept Generation

**User Story:** As a user, I want the AI to design a game tailored to my room's theme and objects.

#### Acceptance Criteria

1. THE AI SHALL generate a GameConcept from the Brief containing: theme (matched to room era/purpose), mechanics (3-5 core interactions), scoring rules, win condition, and difficulty progression.
2. THE GameConcept SHALL be generated via Ollama using the Brief's room_purpose, era, object_manifest, and atmosphere as input.
3. THE user SHALL approve, modify, or reject the proposed GameConcept before it activates.
4. GENRE selection SHALL be contextual: noir → investigation/deduction, kitchen → cooking/service, office → puzzle/management, bar → rhythm/social.

### Requirement 2: Object Role Binding

**User Story:** As a developer, I want game mechanics bound to specific objects by their stable identity.

#### Acceptance Criteria

1. EACH ObjectRole SHALL reference a WorldContract object by its stable UUID from the Brief.
2. THE AI SHALL propose role bindings appropriate to the object's semantic label and game theme.
3. VALID role types: puzzle_surface, loot_container, portal, quest_giver, collectible, hazard, power_source, scoring_zone.
4. THE user SHALL approve or override AI-proposed bindings.
5. UNBOUND objects SHALL retain default physics behavior with no gameplay function.

### Requirement 3: Game State Persistence

**User Story:** As a user, I want my game progress to persist across sessions.

#### Acceptance Criteria

1. GameState SHALL be saved to disk as JSON after every scoring event or state change.
2. GameState SHALL include: current_score, high_score, unlocked_items, completed_objectives, active_rules, play_time_seconds, last_played timestamp.
3. LOADING a room in GAME mode SHALL restore the last saved GameState.
4. THE system SHALL support multiple save slots per room (minimum 3).

### Requirement 4: Remodel Patching

**User Story:** As a user, I want my game to survive room changes without losing progress.

#### Acceptance Criteria

1. WHEN the WorldContract changes (object added/removed/moved), THE system SHALL detect affected ObjectRole bindings.
2. FOR removed objects: THE AI SHALL propose a re-home to a similar remaining object or mark the binding as orphaned.
3. FOR moved objects: THE binding SHALL follow the object (same UUID, new position) — no patch needed.
4. THE user SHALL be informed of all patches with an explanation of what changed and why.
5. ORPHANED bindings SHALL not crash the game — they become inactive until resolved.

### Requirement 5: Scoring Bridge

**User Story:** As a user, I want game achievements to unlock game content but not buy land.

#### Acceptance Criteria

1. GAME points SHALL unlock: new game modes, cosmetic variations, difficulty levels, and bonus objectives.
2. GAME points SHALL NOT earn budget, buy land, or unlock REAL mode capabilities.
3. THE scoring bridge SHALL be one-directional: REAL work → budget → land; GAME play → game content only.
4. A leaderboard per room SHALL track personal bests.
