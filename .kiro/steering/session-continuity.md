# Session Continuity

For the `llm-driven-upbge-runtime` specification:

- After summarization or context transfer, resume from the latest validated checkpoint.
- Consult KiroGraph memory topic `continuation/llm-driven-upbge-runtime-task10` before changing code.
- Treat `.kiro/specs/llm-driven-upbge-runtime/tasks.md` and the latest validation evidence as execution truth.
- Do not restart planning, skip dependency order, reuse discarded release sessions, or mark downstream tasks active prematurely.
- Continue toward the user's governing engine-neutral WorldContract vision until all requirements and clean zero-state qualification are complete or the user interrupts.
- Preserve V3-V10 behavior, unrelated working-tree changes, and honest UPBGE/Godot fallback labeling.
- Use KiroGraph and local Ollama offload to conserve context and user credits; never use cloud offload without explicit permission.
- Treat a working end-to-end MVP within 6–8 active coding hours as a governing delivery constraint.
- Before deep work, verify that the subtask is on the MVP critical path and state the shortest usable outcome it unlocks.
- Timebox deep single-task investigations; if they stop advancing the end-to-end MVP, simplify, defer non-blocking polish/tooling, or switch to the next critical-path blocker.
- At each progress checkpoint, explicitly assess whether current scope still supports the 6–8 hour MVP target and revise the critical path when it does not.
- Provide an inline E2E progress/ETA checkpoint approximately every 60 minutes of active execution.
