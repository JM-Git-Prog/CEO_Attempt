# sim-player — the Sam Loop

A ten-year-old ("Sam") plays The Living Room on repeat, every round is analyzed, unmet wishes go to the
capability-gaps ledger, defects go to a mechanic that patches inside a test gate, and the loop's own
Living Room (:8001) restarts to prove the fix. Design and the rules it keeps:
`Projects/CEO-of-My-Life-Inc/briefings/SAM-LOOP-DESIGN-2026-09-10.md`. John's depth: **C** (2026-09-10).

| file | role |
|---|---|
| `common.py` | paths, the sim namespace (`sim-` sessions, `sim-neighborhood`, :8001), one Ollama call, the capture writer |
| `sam.py` | Sam: the persona + the state machine (vision → plan card → pictures on the garage wall → build) through V17's HTTP API |
| `fake_living_room.py` | a stand-in V17 + Pick Board + builder for tests |
| `seed_world.py` | Sam's copy of the neighborhood, seeded from Mr. John's latest version; reset between rounds; refuses any non-`sim-` slug |
| `analysis.py` | counts → judge (draft) → gaps filed → `REPORT.md` + the rolling `SAM-LOOP-REPORT.md` |
| `mechanic.py` | the code agent: allowlist, human-touch guard, exact-match, backups, the pytest gate, revert; `--revert-all` |
| `sam_loop.py` | the runner: dependencies started or waited for, pause windows, STOP file, heartbeat, rounds |

Cards in the repo root: `RUN-SAM-ONCE.bat` (one round, depth A) · `START-SAM-LOOP.bat` (depth C, all night) ·
`STOP-SAM-LOOP.bat` · `REVERT-SAM-PATCHES.bat` · `RUN-SAM-SELFTESTS.bat`. Every module also has `--selftest`.

Runs land in `sim-player/sim-runs/<round>/` — transcript, calls, world before/after, analysis, report,
patches. Sam's V17 events go to `training-data/events-sim.jsonl`, never `events.jsonl`; a sim session's
confirm is stamped `by: "sim"` so the nightly student never trains on it.
