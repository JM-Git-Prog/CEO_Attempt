"""Drive the V17 split-screen page like a human, stage by stage.

Diagnostic harness only (never qualification/release evidence). Opens
http://127.0.0.1:8000/?v=17, sends the canonical kitchenette prompt, then
watches the pipeline: it screenshots every stage transition, clicks the
Approve button whenever a human gate appears, and waits for each stage to
finish before moving on. Prints a running log and exits when the world
completes, errors, or the wall-clock budget is exhausted.

Usage: python tools/drive_v17_playwright.py [--headed] [--budget-seconds N]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROMPT = (
    "Danny's kitchenette — a small, warm kitchen with a round table, two "
    "chairs, a counter with a coffee maker, and a window looking out at rain."
)
URL = "http://127.0.0.1:8000/?v=17"
SHOTS = Path("output/_v17_drive")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--budget-seconds", type=int, default=1800)
    args = ap.parse_args()

    SHOTS.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.budget_seconds
    shot_n = 0

    def shot(page, tag: str) -> None:
        nonlocal shot_n
        shot_n += 1
        path = SHOTS / f"{shot_n:02d}_{tag}.png"
        try:
            page.screenshot(path=str(path), full_page=False)
            log(f"  screenshot -> {path.name}")
        except Exception as exc:  # noqa: BLE001
            log(f"  screenshot failed: {exc}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.on("console", lambda m: log(f"  console[{m.type}]: {m.text[:160]}"))
        page.on("pageerror", lambda e: log(f"  PAGEERROR: {str(e)[:200]}"))

        log(f"opening {URL}")
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("#message", timeout=15000)

        # Wait for the agent opening to appear (start() calls /unified/start).
        log("waiting for builder-agent opening…")
        try:
            page.wait_for_function(
                "document.querySelectorAll('#messages .message.assistant').length > 0",
                timeout=45000,
            )
            opening = page.eval_on_selector(
                "#messages .message.assistant", "el => el.textContent"
            )
            log(f"  agent opening: {opening[:120]!r}")
        except Exception:
            log("  no assistant opening within 45s (Ollama slow?) — continuing anyway")
        shot(page, "opening")

        # Send the canonical kitchenette prompt like a human.
        log("typing the kitchenette prompt and sending…")
        page.fill("#message", PROMPT)
        page.click("#send")
        shot(page, "prompt_sent")

        # A human reads the agent's reply, then confirms to lock the Brief.
        # The conversation engine treats confirmation phrases as "steering
        # stable", which triggers Brief extraction + pipeline launch. Without
        # this, the agent keeps proposing refinements and never builds.
        log("waiting for the agent's reply, then confirming to lock the Brief…")
        try:
            page.wait_for_function(
                "document.querySelectorAll('#messages .message.assistant').length >= 2",
                timeout=60000,
            )
        except Exception:
            log("  no second assistant reply within 60s — confirming anyway")
        time.sleep(1.0)
        # Only confirm if the pipeline hasn't already started (status still CONVERSATION).
        status_now = (page.text_content("#status") or "").strip()
        if status_now in ("CONVERSATION", "CONNECTING", ""):
            log("  sending confirmation: 'Yes, build it exactly like that.'")
            page.fill("#message", "Yes, build it exactly like that.")
            page.click("#send")
            shot(page, "confirmed_build")

        # Drive the pipeline: watch stage/status, click Approve at each gate,
        # wait for each stage to finish before moving on.
        last_signature = ""
        approvals_clicked = 0
        same_gate_clicks: dict[str, int] = {}
        idle_since = time.time()

        while time.time() < deadline:
            status = (page.text_content("#status") or "").strip()
            stage = (page.text_content("#stageTitle") or "").strip()
            signature = f"{stage} | {status}"

            if signature != last_signature:
                log(f"STAGE: {stage!r}  STATUS: {status!r}")
                shot(page, f"{stage.replace(' ', '_') or 'stage'}__{status.replace(' ', '_').replace('→','arrow')}")
                last_signature = signature
                idle_since = time.time()

            # Terminal conditions.
            if status.startswith("✓ COMPLETED"):
                log("PIPELINE COMPLETED — world ready.")
                shot(page, "completed")
                # Try walking in to prove the 3D panel is live.
                try:
                    page.click("#enterWorld")
                    time.sleep(1.0)
                    shot(page, "walk_in")
                except Exception:
                    pass
                browser.close()
                return 0
            if status == "ERROR" or status == "BLOCKED":
                log(f"PIPELINE {status} — stopping. This is diagnostic evidence.")
                shot(page, f"terminal_{status.lower()}")
                browser.close()
                return 2

            # Human approval gate: the Approve button becomes visible.
            try:
                if page.is_visible("#approval"):
                    # Cap repeated clicks on the SAME gate signature so a
                    # rejected approval (e.g. canon/Brief mismatch) does not spin
                    # forever. A human would click once and read the result.
                    gate_key = signature
                    clicks_here = same_gate_clicks.get(gate_key, 0)
                    if clicks_here >= 3:
                        log(f"  gate {label if (label:=(page.text_content('#approval') or '').strip()) else ''!r} not advancing after 3 clicks — stopping (diagnostic)")
                        shot(page, "gate_stuck")
                        browser.close()
                        return 2
                    label = (page.text_content("#approval") or "approve").strip()
                    log(f"  APPROVAL GATE visible: {label!r} — clicking like a human (attempt {clicks_here+1})")
                    shot(page, f"gate_{approvals_clicked+1}_{label.replace(' ','_')}")
                    page.click("#approval")
                    same_gate_clicks[gate_key] = clicks_here + 1
                    approvals_clicked += 1
                    idle_since = time.time()
                    time.sleep(2.5)  # let the approval POST + resume settle
                    continue
            except Exception as exc:  # noqa: BLE001
                log(f"  approval check error: {exc}")

            # Long idle without any stage change — report but keep waiting
            # (GPU stages legitimately take minutes; we do not force-fail).
            if time.time() - idle_since > 300:
                log(f"  …still on {stage!r}/{status!r} after 5 min idle (GPU stage?)")
                shot(page, "idle_checkpoint")
                idle_since = time.time()

            time.sleep(2.0)

        log(f"budget of {args.budget_seconds}s exhausted — stopping (diagnostic only).")
        shot(page, "budget_exhausted")
        browser.close()
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
