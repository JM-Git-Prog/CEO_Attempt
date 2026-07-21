# GLM 5.2 Deep Research Instructions — V8

You are reviewing the complete sanitized V7 application bundle attached after these instructions. Act as a principal software architect, product UX reviewer, and reliability engineer. This is research only: do not claim that code was changed, and do not output a giant patch.

## User-observed defect
A V7 screenshot shows a restored World while the BRIEF, PLAN, BLOCKOUT, CANON, WORLD, and COMPARE rail remains mostly non-interactive. The user circled BRIEF/PLAN/BLOCKOUT/CANON because they cannot click back to inspect the final artifact from each stage. They also cannot select completed runs from V3–V7 to compare the workflow visually version over version. The current restored-session behavior collapses to the most advanced artifact.

## Required V8 outcomes
1. Make BRIEF, PLAN, BLOCKOUT, CANON, WORLD, and COMPARE clickable whenever that stage has retained evidence.
2. Let the user select a prior completed run/session grouped by interface version, then inspect its final stage outputs continuously and read-only; preserve complete inputs, outputs, workflow profile, revisions, and provenance.
3. Never silently substitute a mutable current artifact for historical evidence. Verify artifact identity/hashes and avoid exposing filesystem paths.
4. Keep V3–V7 accessible and behaviorally stable. New behavior must be isolated to V8, which becomes the default only when released.
5. Add truthful live execution telemetry: real backend substeps, elapsed time, a worker heartbeat/staleness signal, and data-backed ETA. Never invent percentages or ETA. Show “collecting timing data” when evidence is insufficient.
6. Do not change generation models or add pipeline stages. Do not delete or mutate existing user sessions.
7. Retain revision-specific logging without logging prompt or feedback content.

## Research questions
- Trace the exact current reasons stage navigation and cross-version replay fail, citing file paths and symbols.
- Propose the smallest robust V8 architecture and API/data contracts that preserve immutable historical evidence.
- Define stage/revision/session indexing, secure artifact serving, hash verification, and behavior for legacy snapshots whose bytes cannot be verified.
- Define the V8 interaction model for run/version selection, stage clicking, revision selection, historical/current mode, disabled/unavailable states, and returning to live output.
- Define backend telemetry boundaries tied to real work, heartbeat mechanics, persisted timing samples, estimator/fallback rules, confidence/sample-count disclosure, and failure/cancellation behavior.
- Identify backward-compatibility, concurrency, privacy, security, performance, and migration risks.
- Give an implementation sequence that can be released incrementally but culminates in one coherent V8 zero-state pass.
- Give a concrete validation matrix covering APIs, static JS, accessibility, responsive behavior, immutable replay, legacy sessions, telemetry truthfulness, and Brief→World release flow.

## Output format
Return a detailed report with: Executive recommendation; Verified current-state findings; V8 UX contract; Data/provenance model; API contracts with example payload shapes; Telemetry/ETA design; Security and compatibility constraints; Ordered implementation plan; Validation plan; Top risks and mitigations; Open decisions requiring the product owner. Clearly label facts verified from code versus recommendations. Prefer precise, implementable guidance over generic best practices.