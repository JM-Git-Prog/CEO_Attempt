---
inclusion: always
---

# Ops Ownership — who owns what (learned the hard way, 2026-07-23)

The overnight stall of 2026-07-22→23 happened because the qualification watch lived
inside an agent-managed terminal: background processes die when Kiro closes, and agent
sessions end at context boundaries. Per Kiro's own docs (dev-servers, hooks), the fix
is layered ownership. Every session must respect it:

## The layers

1. **Windows owns the PROCESS.** The Ratchet watch is revived by the "Ratchet Watch
   Keepalive" Scheduled Task every 5 minutes via `WATCH-KEEPALIVE.bat` (idempotent —
   the loop's lock refuses duplicates). NEVER own the watch in a Kiro-managed terminal.
   It is fine to SEE it in the terminal list; it is not yours to hold.
2. **Hooks self-heal for FREE.** `ratchet-keepalive.kiro.hook` re-runs the same bat on
   SessionStart and on every agent Stop (command actions — zero credits), and injects
   NEXT.md into new-session context. Do not replace these with agent-prompt hooks.
3. **You (the agent) own CODE and JUDGMENT.** Surgery protocol when editing loop files:
   the keep-alive will revive the watch within 5 minutes of any stop — so simply stop
   the watch, edit, and let the keep-alive (or your Stop hook) restart it. Verify the
   revival happened (lock + fresh iteration) before declaring a step done.
4. **Overnight = measurement only.** Do not assume an agent session survives the night
   (context boundaries are normal). Anything that must happen unattended belongs in the
   loop itself (trials, briefing generation, corpus extraction at idle) — never in a
   promise to "keep iterating."

## Standing facts

- ComfyUI serves on port 8188 ONLY via the Comfy Desktop local instance with startup
  args `--port 8188` (fixed 2026-07-22 18:23 after an evening lost to the default port).
- The briefing job must degrade gracefully when Ollama models are unavailable (it did
  on its first night — keep it that way) and never block the loop.
- Driver-lane policy: cheap session models (Qwen3 Coder Next 0.05x) for stewardship
  and bounded mechanical work only; escalate to a strong model for cross-layer
  debugging. Record lane verdicts in the ratchet design doc's wake log.
- A failed test session is diagnostic evidence, never release evidence. No commits
  without John's explicit request (tasks.md 13.6).

- Harvest trials (F0.5) run inside the single managed watch's idle callback and their evidence is DIAGNOSTIC only — never qualification evidence, never release evidence.
