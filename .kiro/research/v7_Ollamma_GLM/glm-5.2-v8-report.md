# V8 Research Report — The Living Room

## Executive recommendation

The V7 bundle has two architectural gaps that cause the observed defect: (1) the stage rail is decorative for most stages — only PLAN and BLOCKOUT carry click handlers, and even those only swap images without restoring full stage context; (2) the snapshot API (`_snapshot_payload` in `src/web/app.py`) collapses session state to the single most-advanced artifact, discarding the ability to inspect earlier stages or prior runs. There is no session-index API, no cross-version selection surface, and no real execution telemetry — progress is a list of opaque strings with no timing, heartbeat, or data-backed ETA.

The smallest robust V8 architecture adds three read-only layers on top of the existing immutable provenance records that already exist in `output/{session_id}/workflow/`:

1. **A session index** built from existing `session.json` + `workflow_manifest.json` files, grouped by `interface_version`, exposing per-stage evidence availability and artifact hashes without filesystem paths.
2. **A stage-evidence API** that serves verified, hash-checked artifacts from immutable snapshots for any stage/revision of any session, with explicit "unverifiable legacy" handling.
3. **A telemetry channel** that records real substep start/elapsed timestamps, a worker heartbeat, and persisted timing samples with sample-count disclosure and a "collecting timing data" fallback.

All new behavior is isolated behind `?v=8` and the `X-App-Version: 8` header. V3–V7 routes, profiles, and DOM remain untouched. No generation models or pipeline stages change. No existing sessions are mutated.

---

## Verified current-state findings

### Finding 1 — Stage rail is non-interactive for BRIEF, CANON, WORLD, COMPARE

**Verified from code.** In `src/web/templates.py`, the stage rail is emitted as:

```html
<span class="stage-step active" data-stage="brief">BRIEF</span>
<span class="stage-step" data-stage="plan"__PLAN_STAGE_ATTR__>PLAN</span>
<span class="stage-step" data-stage="blockout"__BLOCKOUT_STAGE_ATTR__>BLOCKOUT</span>
<span class="stage-step" data-stage="canon">CANON</span>
<span class="stage-step" data-stage="world">WORLD</span>
<span class="stage-step" data-stage="compare">COMPARE</span>
```

`__PLAN_STAGE_ATTR__` and `__BLOCKOUT_STAGE_ATTR__` are set only when `version >= 4`:

```python
plan_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'floor\')"' if version >= 4 else ""
blockout_attr = ' role="button" tabindex="0" onclick="showPlanArtifact(\'blockout\')"' if version >= 4 else ""
```

BRIEF, CANON, WORLD, and COMPARE have **no `onclick`, no `role="button"`, no `tabindex`** in any version. They are pure display spans.

In `src/web/static/app.js`, `setStage(name)` only toggles the `active` CSS class:

```javascript
function setStage(name) {
  document.querySelectorAll('.stage-step').forEach(step => {
    step.classList.toggle('active', step.dataset.stage === name);
  });
  logEvent('process', 'stage_change', {stage:name});
}
```

It does **not** load any stage content. The only functions that populate `stageBody` are `showPlanArtifact`, `showCanon`, and `buildViewer`, each called from specific workflow action handlers, not from rail clicks.

### Finding 2 — Restored session collapses to most advanced artifact

**Verified from code.** In `src/web/app.py`, `_snapshot_payload`:

```python
def _snapshot_payload(builder: WorldBuilder) -> dict:
    session = builder.session
    common = { ... }
    if session.scene_graph and session.output_path:
        return { **common, "artifact": "world", ... }
    if session.canon_image_path and session.scene_concept:
        return { **common, "artifact": "canon", ... }
    if session.floor_plan and session.scene_concept:
        return { **_plan_payload(builder, session.floor_plan), ... }
    return { **common, "artifact": "empty" }
```

This is a waterfall that returns the **first matching** artifact and ignores all earlier stages. A restored session that has reached WORLD will never return plan, blockout, or canon data through this endpoint.

In `src/web/static/app.js`, `restoreSession` calls `/api/session/{id}/snapshot` or `/api/session/latest/snapshot` and branches on `data.artifact`:

```javascript
if (data.artifact === 'plan') { showPlan(data); }
else if (data.artifact === 'canon') { showCanon(data); }
else if (data.artifact === 'world') {
  addMessage('assistant', '<h3>Restored world</h3>...');
  buildViewer(data.scene_graph, data.download_url);
}
```

There is no code path to restore or navigate to an earlier stage once a later stage exists.

### Finding 3 — No session index or cross-version selection API

**Verified from code.** The API surface in `src/web/app.py` contains:

- `POST /api/session` — create new
- `GET /api/session/latest/snapshot` — latest by mtime
- `GET /api/session/{session_id}/snapshot` — single session
- `GET /api/session/{session_id}/workflow` — workflow manifest
- `GET /api/session/{session_id}/status` — status

There is **no endpoint** to list sessions, group them by interface version, or expose per-stage evidence. The `latest_session_snapshot` endpoint picks `max(candidates, key=lambda path: path.stat().st_mtime)` — a single winner with no grouping.

### Finding 4 — Immutable provenance records already exist but are underused

**Verified from code.** In `src/workflow_provenance.py`, `snapshot_session` writes:

```python
path = output_dir / "workflow" / f"snapshot_{sequence:04d}_{session.state.value}.json"
```

Each snapshot contains:
```python
snapshot = {
    "schema_version": WORKFLOW_SCHEMA_VERSION,
    "recorded_at": ...,
    "sequence": sequence,
    "session_id": session.session_id,
    "interface_version": session.interface_version,
    "workflow_profile": profile,
    "session": session.model_dump(mode="json"),
    "artifacts": [artifact_metadata(artifact) for artifact in sorted(artifact_paths)],
}
```

`artifact_metadata` computes `sha256`, `bytes`, and image dimensions. These snapshots are written with `exclusive=True` (mode `"x"`), making them immutable — a second write to the same path raises `FileExistsError`.

The `workflow_manifest.json` indexes these:
```python
{
    "schema_version": ...,
    "session_id": ...,
    "interface_version": ...,
    "workflow_profile": profile,
    "latest_snapshot": str(path),
    "records": list(session.workflow_records),
    "generation_manifests": list(session.generation_manifests),
}
```

**This is the foundation V8 can build on.** The data exists; it is simply not exposed through a stage-navigation or cross-session API.

### Finding 5 — No real telemetry, heartbeat, or ETA

**Verified from code.** Progress is tracked as a list of strings in `WorldSession.progress_messages` (see `src/models.py`). The `_progress` method in `src/pipeline.py`:

```python
def _progress(self, msg: str):
    self.session.progress_messages.append(msg)
    print(f"[{self.session.session_id}] {msg}")
```

No timestamps, no substep boundaries, no elapsed time, no worker heartbeat. The frontend polls `/api/session/{id}/status` every 900ms (`startPolling` in `app.js`) and displays only `data.progress.at(-1)` — the last string.

There is no ETA computation anywhere. No timing samples are persisted. The `status` endpoint returns:

```python
return {"session_id": session_id, "state": ..., "progress": ..., "error": ..., 
        "provider": ..., "has_image": ..., "has_project": ..., ...}
```

No `started_at`, no `substeps`, no `heartbeat`, no `eta`.

### Finding 6 — Filesystem paths are exposed in API responses

**Verified from code.** In `src/web/app.py`, `approve` returns:

```python
return { ..., "project_path": str(project_path), ... }
```

And `revise_world` returns `"project_path": str(project_path)`. The `artifact_metadata` function in `src/workflow_provenance.py` includes `"path": str(artifact)` in every artifact record. Snapshots and manifests therefore contain absolute or relative filesystem paths.

### Finding 7 — Legacy sessions may lack provenance

**Verified from code.** In `src/pipeline.py`, `_infer_legacy_interface_version` scans `output/logs/v{N}.jsonl` for the earliest event matching a session ID. The `WorldBuilder.__init__` restoration path:

```python
if payload.get("workflow_profile"):
    profile = profile_by_id(payload["workflow_profile"]["id"])
    ...
elif profile_id:
    profile = profile_by_id(profile_id)
else:
    profile = historical_profile_for(version)
```

Pre-provenance sessions (V3/V4 era) may have no `workflow_profile`, no `workflow_profile_id`, and no `workflow/` snapshot directory. Their `session.json` may predate the snapshot system. The release checklist confirms: "Click history before this instrumentation was installed cannot be reconstructed."

### Finding 8 — Revision-specific logging exists and excludes prompt/feedback content

**Verified from code.** In `src/web/event_log.py`, `append_event` sanitizes details:

```python
details = {
    _text(key, 40): value if isinstance(value, (bool, int, float)) else _text(value, 200)
    for key, value in list(raw_details.items())[:16]
}
```

The release checklist states: "User-entered prompt and revision-feedback text are intentionally not logged." The `_ALLOWED_TYPES` set is `{"click", "process", "lifecycle", "test"}`. This boundary is already enforced and V8 must preserve it.

### Finding 9 — UI versioning policy is explicit and must be followed

**Verified from code.** In `.kiro/steering/ui-versioning.md`:

> 1. Increment the interface query version (`?v=N`).
> 2. Keep the preceding version accessible and behaviorally stable.
> 3. Make the newest version the default when no `v` is supplied.

In `src/web/templates.py`, `get_index_html` clamps version to {3,4,5,6,7}. In `src/workflow_provenance.py`, `normalize_interface_version` clamps to the same set. V8 must extend both.

---

## V8 UX contract

### Stage rail clickability rules

| Stage | Clickable when | Disabled when | Click action |
|------|----------------|---------------|--------------|
| BRIEF | `scene_concept` exists in session or snapshot | No concept yet | Load concept/brief view (read-only in historical mode) |
| PLAN | `floor_plan` exists | No plan yet | Load plan SVG + plan JSON summary |
| BLOCKOUT | `blockout_path` artifact exists | No blockout yet | Load blockout PNG |
| CANON | `canon_image_path` artifact exists | No canon yet | Load canon PNG + provider + attempt |
| WORLD | `scene_graph` + `output_path` exist | No world built | Load 3D viewer + download |
| COMPARE | ≥1 world revision exists (`world_revision >= 1`) | No revisions | Load revision history list + diff view |

**Disabled state**: `aria-disabled="true"`, `tabindex="-1"`, visual class `stage-step.disabled` (greyed, no cursor pointer, no click handler).

**Available state**: `role="button"`, `tabindex="0"`, `cursor: pointer`, keyboard Enter/Space activation.

### Run/version selection model

A new **run picker** panel (V8 only) appears in the stage header area or as a collapsible drawer:

1. **Grouped by interface version**: V3, V4, V5, V6, V7, V8 — each group lists completed sessions for that version.
2. **Session card** shows: session ID (truncated), interface version badge, final stage reached, artifact count, timestamp.
3. **Selecting a session** enters **historical mode**: the stage rail populates from that session's evidence; all stages are read-only; a banner reads "Inspecting session `{id}` · V{N} · Read-only".
4. **Returning to live**: a "Return to current session" button exits historical mode and reloads the active session's latest state.

### Historical vs. current mode

| Aspect | Current mode (default) | Historical mode |
|--------|----------------------|-----------------|
| Stage rail | Reflects active session progress | Reflects selected session's evidence |
| Stage clicks | Navigate within active session | Navigate within selected session (read-only) |
| Composer | Enabled | Disabled with tooltip "Read-only historical session" |
| Approve/revise buttons | Visible | Hidden |
| Download | Available if world exists | Available if world artifact is verified |
| Telemetry | Live updates | Frozen snapshot of recorded telemetry |

### Returning to live output

A persistent banner in historical mode: `[← Return to current session]`. Clicking it:
1. Clears historical session ID from URL params.
2. Calls `/api/session/{active_id}/snapshot` (the live session).
3. Restores the stage rail to live state.
4. Re-enables the composer.

---

## Data/provenance model

### Session index record (V8)

Built by scanning `output/*/session.json` and `output/*/workflow_manifest.json`:

```json
{
  "schema_version": 2,
  "sessions": [
    {
      "session_id": "0500f42f",
      "interface_version": 7,
      "workflow_profile_id": "v7-reference-full-r1",
      "created_at": "2026-07-20T18:32:01+00:00",
      "last_updated_at": "2026-07-20T19:15:44+00:00",
      "final_state": "ready",
      "stages": {
        "brief": {"available": true, "evidence_count": 1, "verified": true},
        "plan": {"available": true, "revisions": 2, "latest_hash": "sha256:...", "verified": true},
        "blockout": {"available": true, "revisions": 2, "latest_hash": "sha256:...", "verified": true},
        "canon": {"available": true, "attempts": 1, "latest_hash": "sha256:...", "provider": "FLUX.2 Klein · blockout conditioned", "verified": true},
        "world": {"available": true, "revisions": 0, "object_count": 8, "verified": true},
        "compare": {"available": false, "revisions": 0}
      },
      "artifact_summary": {"snapshots": 4, "generation_manifests": 2}
    }
  ],
  "grouped_by_version": {
    "3": ["71462fa9"],
    "4": ["46452b46"],
    "5": ["b68ba004"],
    "6": ["86c40bc8", "0e7252d6"],
    "7": ["0500f42f"],
    "8": []
  }
}
```

### Stage evidence record (V8)

```json
{
  "schema_version": 2,
  "session_id": "0500f42f",
  "interface_version": 7,
  "stage": "canon",
  "revision": 1,
  "mode": "historical",
  "verified": true,
  "artifact": {
    "artifact_id": "canon_v1.png",
    "sha256": "abc123...",
    "bytes": 1048576,
    "width": 1024,
    "height": 768,
    "served_url": "/api/v8/session/0500f42f/stage/canon/artifact?revision=1"
  },
  "context": {
    "concept": { "era": "...", "mood": "...", ... },
    "provider": "FLUX.2 Klein · blockout conditioned",
    "generation_manifests": ["workflow/canon_v1_conditioned_completed.json"]
  },
  "provenance": {
    "workflow_profile_id": "v7-reference-full-r1",
    "snapshot_sequence": 3,
    "recorded_at": "2026-07-20T18:45:12+00:00"
  }
}
```

### Legacy snapshot handling

For sessions where `workflow/` does not exist or artifact hashes cannot be verified:

```json
{
  "schema_version": 2,
  "session_id": "71462fa9",
  "interface_version": 4,
  "stage": "canon",
  "verified": false,
  "verification_status": "legacy_no_snapshot",
  "artifact": {
    "artifact_id": "canon_v1.png",
    "sha256": null,
    "bytes": null,
    "served_url": "/api/v8/session/71462fa9/stage/canon/artifact?revision=1"
  },
  "warning": "This legacy session predates hash-verified provenance. Artifact bytes are served from session storage but identity cannot be cryptographically verified."
}
```

**Behavior for unverifiable legacy sessions**:
- Stage rail still shows available stages as clickable.
- A visible "unverified" badge appears on the stage body.
- The artifact is served if the file exists, but no hash claim is made.
- The UI banner reads: "Legacy session — artifact identity not verified."

### Hash verification flow

1. For each artifact served, compute SHA-256 of the file bytes at serve time.
2. If a snapshot exists for that session+stage, compare the computed hash to the snapshot's recorded hash.
3. If they match: `verified: true`, `verification_status: "hash_matched"`.
4. If they differ: `verified: false`, `verification_status: "hash_mismatch"`, serve is blocked, error returned.
5. If no snapshot exists: `verified: false`, `verification_status: "legacy_no_snapshot"`, serve proceeds with warning.

### Indexing model

- **Session index**: in-memory cache rebuilt on demand from filesystem scan of `output/*/session.json`. Cache invalidated when any `session.json` mtime changes or on explicit refresh.
- **Stage/revision index**: derived from `workflow_manifest.json` `records` list + glob of `floor_plan_v*.json`, `blockout_v*.png`, `canon_v*.png`, `scene_graph_v*.json` in the session directory.
- **Revision selection**: each stage endpoint accepts `?revision=N` query param. If omitted, serves the latest revision. If `revision=0` or omitted, serves latest.

---

## API contracts with example payload shapes

### `GET /api/v8/sessions`

Returns the session index grouped by interface version.

```json
{
  "schema_version": 2,
  "sessions": [ /* see Session index record above */ ],
  "grouped_by_version": { "3": [...], "4": [...], ... }
}
```

### `GET /api/v8/session/{session_id}/stages`

Returns per-stage evidence availability for one session.

```json
{
  "session_id": "0500f42f",
  "interface_version": 7,
  "stages": {
    "brief": {"available": true, "revisions": [], "verified": true},
    "plan": {"available": true, "revisions": [
      {"revision": 1, "hash": "sha256:...", "artifact_url": "/api/v8/session/0500f42f/stage/plan/artifact?revision=1"},
      {"revision": 2, "hash": "sha256:...", "artifact_url": "/api/v8/session/0500f42f/stage/plan/artifact?revision=2"}
    ], "verified": true},
    "blockout": {"available": true, "revisions": [
      {"revision": 1, "hash": "sha256:...", "artifact_url": "..."},
      {"revision": 2, "hash": "sha256:...", "artifact_url": "..."}
    ], "verified": true},
    "canon": {"available": true, "revisions": [
      {"revision": 1, "hash": "sha256:...", "provider": "...", "artifact_url": "..."}
    ], "verified": true},
    "world": {"available": true, "revisions": [], "object_count": 8, "download_url": "/api/v8/session/0500f42f/download", "verified": true},
    "compare": {"available": false, "revisions": []}
  }
}
```

### `GET /api/v8/session/{session_id}/stage/{stage}?revision=N`

Returns the stage evidence record (metadata + context, not the binary artifact).

Example for `stage=canon`:
```json
{
  "schema_version": 2,
  "session_id": "0500f42f",
  "interface_version": 7,
  "stage": "canon",
  "revision": 1,
  "mode": "historical",
  "verified": true,
  "verification_status": "hash_matched",
  "artifact": {
    "artifact_id": "canon_v1.png",
    "sha256": "abc123...",
    "bytes": 1048576,
    "width": 1024,
    "height": 768,
    "served_url": "/api/v8/session/0500f42f/stage/canon/artifact?revision=1"
  },
  "context": {
    "concept": { "era": "1950s", "mood": "...", "palette": "...", ... },
    "provider": "FLUX.2 Klein · blockout conditioned",
    "attempt": 1
  },
  "provenance": {
    "workflow_profile_id": "v7-reference-full-r1",
    "snapshot_sequence": 3
  }
}
```

Example for `stage=world`:
```json
{
  "schema_version": 2,
  "session_id": "0500f42f",
  "stage": "world",
  "revision": 0,
  "verified": true,
  "verification_status": "hash_matched",
  "artifact": {
    "scene_graph": { /* full SceneGraph model dump */ },
    "download_url": "/api/v8/session/0500f42f/download",
    "mesh_urls": { "counter_01": "/api/v8/session/0500f42f/mesh/counter_01", ... }
  },
  "provenance": { ... }
}
```

### `GET /api/v8/session/{session_id}/stage/{stage}/artifact?revision=N`

Serves the binary artifact (image PNG, SVG, or JSON) with hash verification. Response headers:

```
Content-Type: image/png
X-Artifact-Hash: abc123...
X-Artifact-Verified: true
X-Artifact-Revision: 1
Cache-Control: no-store
```

If hash mismatch: `409 Conflict` with `{"error": "Artifact hash mismatch", "expected": "...", "actual": "..."}`.

### `GET /api/v8/session/{session_id}/telemetry`

Returns recorded telemetry for a session.

```json
{
  "session_id": "0500f42f",
  "active": true,
  "current_state": "ready",
  "heartbeat": {
    "last_seen_at": "2026-07-20T19:15:44.123+00:00",
    "staleness_seconds": 2.1,
    "status": "alive"
  },
  "substeps": [
    {
      "name": "interpret_description",
      "stage": "brief",
      "status": "completed",
      "started_at": "2026-07-20T18:32:01.000+00:00",
      "completed_at": "2026-07-20T18:32:04.500+00:00",
      "elapsed_seconds": 3.5
    },
    {
      "name": "build_floor_plan",
      "stage": "plan",
      "status": "completed",
      "started_at": "2026-07-20T18:32:04.500+00:00",
      "completed_at": "2026-07-20T18:32:08.200+00:00",
      "elapsed_seconds": 3.7
    }
  ],
  "eta": {
    "current_substep": "assemble_godot_project",
    "stage": "world",
    "estimate_seconds": null,
    "status": "collecting_timing_data",
    "sample_count": 0,
    "confidence": "insufficient"
  }
}
```

### `POST /api/v8/session` (create with V8 default)

```json
// Response
{
  "session_id": "a1b2c3d4",
  "interface_version": 8,
  "workflow_profile_id": "v8-reference-full-r1",
  "workflow_url": "/api/v8/session/a1b2c3d4/workflow"
}
```

---

## Telemetry/ETA design

### Real substep recording

**Recommendation.** Add a `TelemetryRecorder` class that wraps each pipeline step:

```python
@dataclass
class SubstepRecord:
    name: str
    stage: str
    status: str  # "started", "completed", "failed", "cancelled"
    started_at: str  # ISO UTC
    completed_at: str | None
    elapsed_seconds: float | None
```

In `src/pipeline.py`, each `step_*` method would record:
- `started_at` at entry (via `time.monotonic()` for elapsed, `datetime.now(timezone.utc).isoformat()` for timestamp).
- `completed_at` at exit.
- `elapsed_seconds = completed_at - started_at`.

Records are appended to a session-scoped `output/{session_id}/telemetry/substeps.jsonl` (append-only, one JSON object per line). This file is **not** the same as the event log — it contains only timing, no user content.

### Worker heartbeat

**Recommendation.** A heartbeat thread or async task writes `output/{session_id}/telemetry/heartbeat.json` every 2 seconds while a pipeline step is active:

```json
{
  "last_seen_at": "2026-07-20T19:15:44.123+00:00",
  "active_substep": "generate_conditioned_canon",
  "pid": 12345
}
```

**Staleness signal**: if `now - last_seen_at > 10 seconds`, status is `"stale"`. If `> 30 seconds`, status is `"dead"`. The frontend reads this via `/api/v8/session/{id}/telemetry` and displays:
- `alive` (green): "Worker active"
- `stale` (amber): "Worker may be stalled — last seen {N}s ago"
- `dead` (red): "Worker lost — session may need restart"

### Persisted timing samples

**Recommendation.** A global `output/telemetry_samples/{stage}_{substep}.jsonl` accumulates elapsed times across all sessions:

```json
{"session_id": "0500f42f", "elapsed_seconds": 3.5, "recorded_at": "...", "interface_version": 7}
{"session_id": "86c40bc8", "elapsed_seconds": 3.2, "recorded_at": "...", "interface_version": 6}
```

### Estimator/fallback rules

**Recommendation.** ETA is computed only when sufficient samples exist:

1. **Sample count < 3**: `status: "collecting_timing_data"`, `estimate_seconds: null`, `confidence: "insufficient"`. UI shows: "Collecting timing data — no estimate yet."
2. **Sample count 3–9**: `status: "estimated"`, `estimate_seconds: median(samples)`, `confidence: "low"`, `sample_count: N`. UI shows: "Estimated ~{N}s (low confidence, {sample_count} samples)."
3. **Sample count ≥ 10**: `status: "estimated"`, `estimate_seconds: median(samples)`, `confidence: "medium"`, `sample_count: N`. UI shows: "Estimated ~{N}s ({sample_count} samples)."

**Never invent percentages.** Progress display shows completed substeps as a count ("Step 3 of 6"), not a percentage bar. If the total substep count is unknown (e.g., revision loops), show "Step {N}" without "of {total}".

### Failure/cancellation behavior

- On exception: substep record gets `status: "failed"`, `error_type: str(type(exc))`. No error message content is logged (privacy). Heartbeat stops.
- On cancellation (if implemented): `status: "cancelled"`. Heartbeat stops.
- ETA for remaining steps becomes `null` with `status: "failed"`.

### Telemetry boundaries (what is NOT logged)

- No prompt text, feedback text, or user description content.
- No image bytes or model outputs.
- Only: substep name, stage, timestamps, elapsed seconds, status, error type name.
- This is consistent with the existing `event_log.py` privacy boundary.

---

## Security and compatibility constraints

### Filesystem path exposure

**Verified risk.** Current API responses include `str(project_path)` and `artifact_metadata` includes `"path": str(artifact)`. 

**Recommendation.** V8 APIs must:
- Never return filesystem paths in JSON responses.
- Use opaque artifact IDs and served URLs instead.
- Strip `path` from `artifact_metadata` before returning in V8 endpoints.
- V3–V7 endpoints remain unchanged (behavioral stability).

### Hash verification enforcement

**Recommendation.** V8 artifact-serving endpoints:
1. Compute SHA-256 at serve time.
2. Compare to snapshot record if available.
3. Block serve on mismatch with `409 Conflict`.
4. Serve with warning for legacy sessions without snapshots.
5. Never substitute a mutable current artifact for historical evidence — the V8 stage endpoint reads from the session directory or snapshot, never from the in-memory `sessions` dict when in historical mode.

### Backward compatibility

- V3–V7 routes (`/api/session/...`) remain unchanged.
- V3–V7 HTML templates remain unchanged.
- V3–V7 `app.js` behavior remains unchanged.
- V8 adds new routes under `/api/v8/...` and new HTML under `/?v=8`.
- `normalize_interface_version` must be extended to accept 8 and map to `v8-reference-full-r1`.
- A new profile `v8-reference-full-r1` must be added to `_PROFILE_VALUES` with the same Canon contract as V7 (no model changes).

### Concurrency

- Session index cache must be thread-safe (the existing `_LOCK` in `event_log.py` shows the pattern).
- Snapshot writes already use `exclusive=True` (mode `"x"`).
- V8 read endpoints are idempotent and can be cached aggressively except for telemetry/heartbeat.

### Migration

- No migration script needed. V8 reads existing `session.json` and `workflow/` files.
- Sessions created under V3–V7 remain accessible via their original endpoints and via V8 read-only inspection.
- The `telemetry/` subdirectory is created on first V8 session; pre-existing sessions simply have no telemetry data (handled by "collecting timing data" fallback).

### Privacy

- Telemetry files contain no user content.
- Event log continues to exclude prompt/feedback text.
- Session index exposes session IDs (already non-sensitive 8-char hex) but no descriptions or content.

### Performance

- Session index scan: O(number of sessions). For a prototype with <100 sessions, this is trivial. Cache with mtime invalidation.
- Hash computation at serve time: O(file size). Canon images are ~1MB; blockout PNGs ~100KB. Negligible.
- Heartbeat writes: 2-second interval, <1KB JSON. Negligible I/O.

---

## Ordered implementation plan

### Phase 1 — V8 scaffolding (no user-visible change)

1. Add `v8-reference-full-r1` to `_PROFILE_VALUES` in `src/workflow_provenance.py` with V7-identical Canon contract.
2. Extend `normalize_interface_version` to accept 8.
3. Extend `get_index_html` in `src/web/templates.py` to render V8 variant (initially identical to V7 DOM).
4. Add V8 link to `version_nav`.
5. Add `X-App-Version: 8` handling to `_request_version`.

**Validation**: V8 page loads at `/?v=8`, V3–V7 pages unchanged.

### Phase 2 — Session index API

6. Implement `GET /api/v8/sessions` in `src/web/app.py`: scan `output/*/session.json`, build index, group by `interface_version`, cache with mtime invalidation.
7. Implement `GET /api/v8/session/{session_id}/stages`: derive per-stage evidence from session directory + workflow manifest.

**Validation**: `curl /api/v8/sessions` returns grouped list. `curl /api/v8/session/0500f42f/stages` returns stage availability.

### Phase 3 — Stage evidence API

8. Implement `GET /api/v8/session/{session_id}/stage/{stage}?revision=N`: return metadata + context.
9. Implement `GET /api/v8/session/{session_id}/stage/{stage}/artifact?revision=N`: serve binary with hash verification.
10. Add hash mismatch detection (409) and legacy warning handling.
11. Strip filesystem paths from all V8 responses.

**Validation**: Each stage artifact is retrievable for a known session. Hash mismatch returns 409. Legacy session returns warning.

### Phase 4 — V8 frontend: stage rail clickability

12. In V8 template, add `onclick`, `role="button"`, `tabindex="0"` to all six stage steps.
13. In V8 `app.js` (or version-gated branch), implement `loadStage(stage, revision)` that calls the stage evidence API and renders the appropriate viewer.
14. Implement disabled state for stages without evidence.
15. Implement keyboard activation (Enter/Space) for stage steps.

**Validation**: Clicking each available stage loads its content. Unavailable stages are disabled and not clickable.

### Phase 5 — V8 frontend: run/version picker

16. Add run picker UI component (collapsible panel in stage header).
17. Fetch `/api/v8/sessions` on V8 load, render grouped session list.
18. On session select: enter historical mode, fetch stages, populate rail, disable composer, show banner.
19. Implement "Return to current session" button.

**Validation**: User can select a V6 session from the picker, inspect its canon and world, and return to the live V8 session.

### Phase 6 — Telemetry backend

20. Implement `TelemetryRecorder` class with substep start/complete/fail recording.
21. Add heartbeat writer (2-second interval during active pipeline steps).
22. Implement `output/telemetry_samples/{stage}_{substep}.jsonl` append.
23. Implement `GET /api/v8/session/{session_id}/telemetry` endpoint.
24. Wire telemetry recording into `WorldBuilder.step_*` methods (non-breaking — wrapped in try/except so telemetry failure never breaks pipeline).

**Validation**: Running a V8 session produces `substeps.jsonl` and `heartbeat.json`. Telemetry endpoint returns real elapsed times.

### Phase 7 — Telemetry frontend

25. In V8 `app.js`, replace the 900ms status poll with a telemetry poll that reads `/api/v8/session/{id}/telemetry`.
26. Render substep list with elapsed times.
27. Render heartbeat status (alive/stale/dead).
28. Render ETA with sample-count disclosure and "collecting timing data" fallback.

**Validation**: During a V8 build, the UI shows real substep times, heartbeat status, and honest ETA or "collecting timing data".

### Phase 8 — V8 zero-state pass

29. Create a brand-new empty V8 session.
30. Run the canonical prompt from `.kiro/release-checklist.md` Step 1.
31. Inspect all six stages (BRIEF, PLAN, BLOCKOUT, CANON, WORLD, COMPARE) for clickability and correct content.
32. Select a prior V6 or V7 session from the run picker; verify historical mode works for all stages.
33. Verify telemetry shows real times and honest ETA.
34. Verify V3–V7 pages are unchanged.
35. Record clean pass in release checklist.

---

## Validation plan

| Category | Test | Expected result |
|----------|------|-----------------|
| **APIs** | `GET /api/v8/sessions` | Returns grouped session list with correct interface versions |
| **APIs** | `GET /api/v8/session/{id}/stages` | Returns per-stage availability matching filesystem evidence |
| **APIs** | `GET /api/v8/session/{id}/stage/canon?revision=1` | Returns canon metadata with hash |
| **APIs** | `GET /api/v8/session/{id}/stage/canon/artifact?revision=1` | Serves PNG with `X-Artifact-Verified: true` |
| **APIs** | Hash mismatch (tamper file) | Returns 409 Conflict |
| **APIs** | Legacy session (no workflow/) | Returns 200 with `verified: false` and warning |
| **APIs** | No filesystem paths in any V8 response | Grep response bodies for `output/` or `/home/` — none found |
| **Static JS** | V8 `app.js` loads without errors | Console clean |
| **Static JS** | V3–V7 `app.js` unchanged | Diff against V7 bundle — identical |
| **Accessibility** | Stage rail steps have `role="button"`, `tabindex="0"` when available | Axe/lighthouse audit |
| **Accessibility** | Disabled stages have `aria-disabled="true"`, `tabindex="-1"` | Axe/lighthouse audit |
| **Accessibility** | Keyboard Enter/Space activates stage step | Manual test |
| **Responsive** | V8 at 1440×500 | No overflow, compact layout works |
| **Responsive** | V8 at 375×667 (mobile) | Stacked layout, run picker accessible |
| **Responsive** | V8 at 1920×1080 | Splitter works, stage rail visible |
| **Immutable replay** | Select V6 session 86c40bc8, click CANON | Canon image from that session loads, not current session's |
| **Immutable replay** | Select V6 session, click WORLD | 3D viewer builds from that session's scene_graph |
| **Immutable replay** | Select V6 session, click BRIEF | Concept/brief from that session loads |
| **Immutable replay** | Historical mode composer is disabled | No input possible |
| **Immutable replay** | "Return to current session" restores live state | Active session's latest artifact loads |
| **Legacy sessions** | V3 session 71462fa9 stages accessible | Stages load with "unverified" badge |
| **Legacy sessions** | V3 session artifacts served without hash claim | Warning displayed |
| **Telemetry truthfulness** | V8 build shows real elapsed seconds per substep | Times match wall clock |
| **Telemetry truthfulness** | First-ever V8 build shows "collecting timing data" | No invented ETA |
| **Telemetry truthfulness** | After 3+ builds, ETA shows with sample count | "Estimated ~N.Ns (low confidence, 3 samples)" |
| **Telemetry truthfulness** | No percentage bars in V8 | Only step counts |
| **Telemetry truthfulness** | Heartbeat shows "alive" during build, "stale" after 10s stall | Manual stall test |
| **Brief→World flow** | Fresh V8 session, canonical prompt, full pass | All stages clickable after completion, telemetry recorded |
| **Brief→World flow** | V3–V7 pages still work | Full pass on each version |
| **Privacy** | Telemetry files contain no prompt/feedback text | Grep for known prompt strings — none found |
| **Privacy** | Event log still excludes prompt/feedback | Grep v8.jsonl — none found |

---

## Top risks and mitigations

### Risk 1 — Hash mismatch on legitimate sessions

**Scenario**: A user manually edits a canon image file in `output/{session_id}/`. V8 detects mismatch and blocks serve.

**Mitigation**: The 409 response includes a clear message. A "View unverified" fallback button can be offered (product owner decision) that serves the file with a prominent warning, but never claims it is verified.

### Risk 2 — Session index scan performance at scale

**Scenario**: Hundreds of sessions accumulate. Scanning all `session.json` files on every `/api/v8/sessions` call becomes slow.

**Mitigation**: Cache the index in memory. Invalidate on `session.json` mtime change. Add a manual refresh button. For >1000 sessions, consider a SQLite index (future work, not V8).

### Risk 3 — Telemetry overhead

**Scenario**: Heartbeat writes every 2 seconds add I/O load on slow disks.

**Mitigation**: Heartbeat file is <1KB. Write is atomic (`write_json` pattern). If I/O fails, telemetry silently degrades — pipeline continues, UI shows "collecting timing data".

### Risk 4 — Historical mode confusion

**Scenario**: User forgets they are in historical mode and tries to interact with the composer.

**Mitigation**: Composer is visually disabled (greyed, `disabled` attribute). Banner is persistent and high-contrast. "Return to current session" button is always visible.

### Risk 5 — Legacy session artifact corruption

**Scenario**: A V3 session's canon image file is missing or corrupted.

**Mitigation**: Stage endpoint returns 404 with a clear message. Stage rail shows that stage as unavailable (disabled). Other stages for the same session remain accessible if their files exist.

### Risk 6 — Concurrent session creation while index is building

**Scenario**: New session created while `/api/v8/sessions` is scanning.

**Mitigation**: Scan is a point-in-time snapshot. New session appears on next refresh. No locking needed — reads are non-blocking.

### Risk 7 — V8 profile drift

**Scenario**: V8 profile is accidentally changed to use a different Canon model.

**Mitigation**: The `_pinned_profile` function in `workflow_provenance.py` already raises `ValueError` if a session's profile differs from the immutable registry. V8 profile must be added to `_PROFILE_DOCUMENTS` as a frozen JSON string, identical to V7's Canon contract.

---

## Open decisions requiring the product owner

1. **COMPARE stage scope**: The COMPARE stage currently has no implementation in V7 (no revision diff UI). Should V8 COMPARE show: (a) a side-by-side image comparison of canon vs. world render, (b) a revision history list with metadata only, or (c) both? The backend has `revision_history.json` and `render_paths` but no diff visualization.

2. **Run picker placement**: Should the run/version picker be (a) a collapsible drawer in the stage header, (b) a modal overlay triggered by a "Browse sessions" button, or (c) a dedicated `/sessions` page? This affects the V8 DOM structure.

3. **Legacy artifact fallback**: When a hash mismatch is detected, should V8 (a) block serve entirely, (b) serve with a prominent "UNVERIFIED" warning, or (c) offer both as a user choice? This is a security/UX tradeoff.

4. **Telemetry persistence scope**: Should timing samples be (a) global across all sessions (as proposed), (b) per-interface-version (separate sample files per V3/V4/.../V8), or (c) per-workflow-profile? Per-version would give more accurate ETAs but slower to reach sufficient sample counts.

5. **V8 default timing**: Should V8 become the default immediately upon release (per the UI versioning policy: "Make the newest version the default when no `v` is supplied"), or should there be a grace period where V7 remains default? The policy says newest becomes default, but the product owner may want to override.

6. **Cross-version comparison**: The user mentioned "select completed runs from V3–V7 to compare the workflow visually version over version." Should V8 support (a) selecting two sessions and viewing them side-by-side, or (b) selecting one session at a time and switching between them? True side-by-side would require a split-stage UI which is a larger change.

7. **Telemetry for legacy sessions**: Should V8 attempt to reconstruct approximate timing for legacy sessions from event log timestamps, or should legacy sessions simply show "No telemetry data — predates V8 instrumentation"?
