# Bugfix Requirements Document

## Introduction

This requirements phase governs `restart-session-continuity-fix` within the existing `unified-world-pipeline` specification. It prevents a computer or agent-session restart from reviving superseded checkpoints, overstating release readiness, or reusing failed qualification sessions. The recovered checkpoint must distinguish completed and validated implementation work from unvalidated working-tree repairs and incomplete live V16 qualification. The older `llm-driven-upbge-runtime` Task 10 checkpoint is historical: its Tasks 1–12 are complete, while Tasks 13–14 remain downstream work and do not replace the active V16 qualification critical path.

## Bug Analysis

### Current Behavior (Defect)

After a restart, available continuity sources can disagree in age, authority, and validation status, causing an inaccurate answer to “where did we leave off?”

1.1 WHEN a restart recovery encounters the historical `llm-driven-upbge-runtime` Task 10 continuation alongside newer task and validation records THEN the system can incorrectly report Task 10 as active even though Tasks 1–12 were subsequently completed

1.2 WHEN `unified-world-pipeline/tasks.md`, `CONTINUATION.md`, KiroGraph memory, qualification output, and the working tree describe different checkpoints THEN the system can select a stale record and direct work back to completed waves or past the current qualification blocker

1.3 WHEN focused and suite validation is green but no complete clean live V16 zero-state qualification exists THEN the system can incorrectly describe the interface as release-qualified or the release loop as complete

1.4 WHEN failed, restored, previous-version, or non-canonical sessions are present THEN the system can treat them as resumable or qualifying evidence instead of diagnostic-only evidence

1.5 WHEN uncommitted repairs exist after the latest validated checkpoint THEN the system can omit those repairs from the recovery answer or describe them as validated without supporting test evidence

1.6 WHEN restart recovery identifies remaining work THEN the system can activate downstream `llm-driven-upbge-runtime` Tasks 13–14 or change retained interfaces before the active V16 critical-path blocker and qualification sequence are complete

### Expected Behavior (Correct)

Restart recovery must reconcile chronology, validation, and release-evidence rules before reporting the checkpoint or recommending the next action.

2.1 WHEN a restart recovery encounters the historical `llm-driven-upbge-runtime` Task 10 continuation alongside newer task and validation records THEN the system SHALL report Tasks 1–12 as complete, identify Task 10 as superseded history, and leave Tasks 13–14 pending behind their declared dependencies

2.2 WHEN `unified-world-pipeline/tasks.md`, `CONTINUATION.md`, KiroGraph memory, qualification output, and the working tree describe different checkpoints THEN the system SHALL identify `unified-world-pipeline` as the governing active specification, prefer the newest non-superseded validated evidence, and explicitly label stale or unrelated records rather than merging them into execution truth

2.3 WHEN focused and suite validation is green but no complete clean live V16 zero-state qualification exists THEN the system SHALL report the validated implementation baseline separately from release qualification and SHALL state that release qualification remains incomplete

2.4 WHEN failed, restored, previous-version, or non-canonical sessions are present THEN the system SHALL retain them as diagnostic-only evidence, SHALL NOT resume or reuse them for release qualification, and SHALL require another brand-new empty V16 session after the observed cause is fixed

2.5 WHEN uncommitted repairs exist after the latest validated checkpoint THEN the system SHALL report them as in-progress and unvalidated, preserve them without modification during requirements recovery, and require focused validation before relying on them as the next checkpoint

2.6 WHEN restart recovery identifies remaining work THEN the system SHALL keep the active critical path on validating the in-progress V16 repair, verifying required local services, and running the exact canonical prompt in a brand-new empty V16 session before any required five fresh headless and five fresh human-like rounds; it SHALL NOT activate downstream `llm-driven-upbge-runtime` Tasks 13–14 or alter retained interfaces prematurely

### Unchanged Behavior (Regression Prevention)

Recovery accuracy must not weaken existing authority, versioning, or evidence-preservation guarantees.

3.1 WHEN a user opens a retained V3–V15 interface THEN the system SHALL CONTINUE TO expose that version at its existing selector or route with behavior unchanged

3.2 WHEN the active V16 pipeline resumes after a normal reload with a valid durable checkpoint and no superseding revision THEN the system SHALL CONTINUE TO reconcile external work idempotently under the existing single-worker and single-approval-writer rules

3.3 WHEN diagnostic sessions `8f24afd0`, `8b5057d3`, `473caae9`, `fb163c47`, `b7dd26d5`, `32c30b0f`, or `c4195e57` are inspected THEN the system SHALL CONTINUE TO preserve their evidence append-only while excluding them from release qualification

3.4 WHEN the latest validated implementation baseline is reported THEN the system SHALL CONTINUE TO preserve its exact evidence: 922 unified and strict-real tests passed, 36 V14/V16 route tests passed, 53 mesh-focused tests passed, and diagnostics, compile checks, workflow JSON checks, and diff checks were green

3.5 WHEN the next clean V16 qualification run begins THEN the system SHALL CONTINUE TO use the exact canonical prompt: “Danny's kitchenette — a small, warm kitchen with a round table, two chairs, a counter with a coffee maker, and a window looking out at rain.”

3.6 WHEN any new qualification defect appears THEN the system SHALL CONTINUE TO record the defect, fix its cause, discard that session as release evidence, and restart the entire qualification sequence with another brand-new empty V16 session
