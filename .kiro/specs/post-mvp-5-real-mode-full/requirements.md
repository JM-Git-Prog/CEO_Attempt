# Requirements Document

## Introduction

This specification completes the REAL mode implementation — full MCP tool integration, budget earning from verified work, consequential action approval, and multi-tool surface binding. The MVP ships with one working read-only binding. This upgrade delivers the full "your room runs your life" promise.

**Prerequisite:** unified-world-pipeline MVP (mode toggle working, one read-only REAL binding demonstrated)

## Glossary

- **REAL_Overlay**: Per-room behavior bindings connecting external tools to room surfaces.
- **Tool_Binding**: An MCP-server connection that maps external data to a specific object surface.
- **Budget**: Currency earned from verified real work, spendable on land/rooms.
- **Consequential_Action**: A write operation (reply, send, delete, pay) requiring explicit user approval.
- **Surface_Display**: Read-only visualization of external data on an in-world object surface.

## Requirements

### Requirement 1: Multi-Tool MCP Integration

#### Acceptance Criteria

1. THE system SHALL support connecting multiple MCP servers simultaneously per room.
2. SUPPORTED binding types: email (inbox on desk), calendar (schedule on whiteboard), documents (files in cabinet), terminal (shell on screen), model (inference on computer surface).
3. EACH binding SHALL be configured via conversation: "wire my Gmail to the desk."
4. THE system SHALL discover available MCP servers and present compatible binding options.
5. BINDINGS SHALL survive room reloads and mode switches.

### Requirement 2: Live Data Display

#### Acceptance Criteria

1. BOUND surfaces SHALL display live data from connected tools, refreshed at configurable intervals (default 30s).
2. DATA SHALL be rendered as texture overlays on the bound object surface without altering geometry.
3. THE display SHALL respect the room's Art_Bible aesthetic (font, color palette, density appropriate to era).
4. IF an MCP server is unreachable, THE surface SHALL display "disconnected" rather than crashing.
5. DATA density SHALL be appropriate to surface size (desk shows more than a sticky note).

### Requirement 3: Budget and Land Economy

#### Acceptance Criteria

1. REAL work SHALL be verified by monitoring connected tool activity (emails read, documents edited, tasks completed).
2. VERIFIED work SHALL earn budget at a configurable rate per activity type.
3. BUDGET SHALL be spendable on: new rooms (floor area), new buildings, terrain expansion.
4. THE budget ledger SHALL be append-only and auditable.
5. ONLY real work earns budget — GAME play never earns budget (asymmetric scoring bridge).

### Requirement 4: Consequential Actions (v2)

#### Acceptance Criteria

1. WRITE operations (reply to email, send message, delete file, make payment) SHALL NOT execute without explicit user approval.
2. THE approval gate SHALL show the exact content that will be sent/deleted/paid before execution.
3. THE system SHALL present a clear "this action is real and irreversible" warning.
4. APPROVED actions SHALL be logged with timestamp, content hash, and user confirmation record.
5. THE user SHALL be able to disable consequential actions entirely (read-only-forever mode).

### Requirement 5: Template Rooms

#### Acceptance Criteria

1. WHEN a user wires tools to a room configuration, THE system SHALL offer to save it as a template.
2. TEMPLATES SHALL include: tool bindings, surface assignments, layout preferences.
3. TEMPLATES SHALL be reusable: "I wired Gmail to this desk layout; do the same in the satellite office."
4. TEMPLATES SHALL be stored in the Asset_Warehouse alongside geometry assets.
5. APPLYING a template SHALL not override existing bindings without confirmation.
