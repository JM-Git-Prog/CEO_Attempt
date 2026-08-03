# Bugfix Requirements Document

## Introduction

The V16 Unified World Pipeline has a split-brain state management defect. Two independent state files — `session.json` (managed by `SessionManager`) and `session_meta.json` (managed by `unified_routes.py`) — can hold contradictory session states. When the server restarts, `mark_failed_on_restart()` correctly stamps `session.json` with `state: ERROR`, but `session_meta.json` remains stale (showing "running" or "completed"). Because the frontend reads state exclusively from the SSE progress stream (which reads `session_meta.json`), users never see the error — they see a phantom completed/running session that is actually failed.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the server restarts and `mark_failed_on_restart()` executes THEN the system writes `state: ERROR` and `reason_code: server_restart` to `session.json` but does NOT update `session_meta.json`

1.2 WHEN the frontend connects to the SSE progress stream after a server restart THEN the system emits progress events sourced from `session_meta.json` which still shows `state: running` or `state: completed`

1.3 WHEN `session.json.state == "error"` AND `session_meta.json.state != "error"` THEN the frontend displays the session as RUNNING or COMPLETED while the backend ground truth is FAILED

1.4 WHEN the frontend establishes an SSE connection THEN the system replays cached progress events without first checking the authoritative session state in `session.json`

1.5 WHEN a user navigates to a session page after a server restart THEN there is no mechanism to fetch current ground-truth state — the frontend relies solely on SSE event replay

### Expected Behavior (Correct)

2.1 WHEN the server restarts and `mark_failed_on_restart()` executes THEN the system SHALL write `state: ERROR` and `reason_code: server_restart` to BOTH `session.json` AND `session_meta.json` atomically

2.2 WHEN the frontend connects to the SSE progress stream THEN the system SHALL check `session.json` for error state BEFORE emitting any progress events, and SHALL emit an error event if the session is in error state

2.3 WHEN `session.json.state == "error"` THEN the system SHALL ensure `session_meta.json.state == "error"` at all times (state consistency invariant)

2.4 WHEN a client requests session health via `GET /api/session/{id}/health` THEN the system SHALL return the ground-truth state by consulting both `session.json` and `session_meta.json`, reporting error if either indicates failure

2.5 WHEN the frontend establishes an SSE connection or navigates to a session page THEN the system SHALL first fetch current state from the `/api/session/{id}/health` endpoint before replaying SSE events

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a session is actively running and no restart has occurred THEN the system SHALL CONTINUE TO write progress events to `session_meta.json` and stream them via SSE as before

3.2 WHEN a session completes successfully without any restart THEN the system SHALL CONTINUE TO mark both state files as `state: completed` through the existing orchestration flow

3.3 WHEN the frontend is connected via SSE during normal operation THEN the system SHALL CONTINUE TO receive real-time progress updates without additional polling overhead

3.4 WHEN `mark_failed_on_restart()` is called THEN the system SHALL CONTINUE TO write `reason_code: server_restart` to `session.json` as it does today (additive change, not replacement)

3.5 WHEN a session has never been started or does not exist THEN the system SHALL CONTINUE TO return appropriate 404/not-found responses from session endpoints

---

## Bug Condition

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type SessionState
  OUTPUT: boolean
  
  // Returns true when session.json and session_meta.json disagree on error state
  RETURN X.session_json.state = "error" AND X.session_meta_json.state ≠ "error"
END FUNCTION
```

## Fix Checking Property

```pascal
// Property: Fix Checking — State files never disagree on error
FOR ALL X WHERE isBugCondition(X) DO
  result ← mark_failed_on_restart'(X)
  ASSERT result.session_json.state = "error"
    AND result.session_meta_json.state = "error"
    AND result.session_json.reason_code = result.session_meta_json.reason_code
END FOR
```

## Preservation Checking Property

```pascal
// Property: Preservation Checking — Non-error sessions behave identically
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
  // Sessions that are running, completed, or not-started behave the same as before
END FOR
```
