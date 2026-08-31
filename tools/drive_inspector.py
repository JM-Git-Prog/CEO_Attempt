"""Headed Playwright driver for the V2.0 pipeline + Inspector.

Drives the running server at http://127.0.0.1:8000/?v=2.0 end to end:
  1. Opens the V2.0 page (visible browser).
  2. Types a room prompt and clicks Send.
  3. Waits for the hero Canon + Build button, then clicks Build.
  4. Reads the live session id from the Inspect Pipeline link.
  5. Opens the 8-stage HITL Inspector for that session in a new tab.

Usage:
    python tools/drive_inspector.py ["your room prompt"]

If no prompt is given, a fast kitchenette default is used. The server must
already be running (launch Day1.bat first, or use Day1-Auto.bat which starts
the server then invokes this).
"""

from __future__ import annotations

import re
import sys
import time
from urllib.parse import urlparse, parse_qs

BASE = "http://127.0.0.1:8000"
V2_URL = f"{BASE}/?v=2.0"

DEFAULT_PROMPT = (
    "Danny's kitchenette — a small, warm kitchen with a round table, two "
    "chairs, a counter with a coffee maker, and a window looking out at rain."
)

# The build/describe step can take a while (FLUX hero Canon generation).
HERO_TIMEOUT_MS = 180_000  # 3 min for the hero Canon + Build button to appear


def _log(msg: str) -> None:
    print(f"[drive] {msg}", flush=True)


def main() -> int:
    prompt = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else DEFAULT_PROMPT

    try:
        from playwright.sync_api import (
            TimeoutError as PWTimeout,
            sync_playwright,
        )
    except ImportError:
        _log("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return 3

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        except Exception as exc:  # noqa: BLE001
            _log(f"Could not launch Chromium: {exc}")
            _log("Try: python -m playwright install chromium")
            return 3

        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        try:
            _log(f"Opening {V2_URL}")
            try:
                page.goto(V2_URL, timeout=30_000, wait_until="domcontentloaded")
            except PWTimeout:
                _log("Server not responding at :8000 — is Day1.bat running?")
                return 2

            # 1. Type the prompt and send.
            _log(f"Prompt: {prompt[:70]}{'...' if len(prompt) > 70 else ''}")
            page.wait_for_selector("#chatInput", timeout=15_000)
            page.fill("#chatInput", prompt)
            page.click("#chatSend")
            _log("Submitted description — waiting for hero Canon (up to 3 min)...")

            # 2. Wait for the Build button to become visible (Canon is ready).
            try:
                page.wait_for_selector("#buildBtn:not(.hidden)", timeout=HERO_TIMEOUT_MS)
            except PWTimeout:
                _log("Hero Canon / Build button did not appear in time.")
                _log("The describe step may have failed — check the browser window.")
                page.screenshot(path="output/_drive_hero_timeout.png")
                return 2
            _log("Hero Canon ready. Build button visible.")

            # 3. Grab the session id from the inspect link before building.
            session_id = ""
            try:
                page.wait_for_selector("#inspectBtn:not(.hidden)", timeout=5_000)
                href = page.get_attribute("#inspectBtn", "href") or ""
                q = parse_qs(urlparse(href).query)
                session_id = (q.get("session") or [""])[0]
            except PWTimeout:
                pass

            # 4. Click Build to launch the automated pipeline.
            page.click("#buildBtn")
            _log("Clicked Build — pipeline launching (Phases 2-5).")

            # 5. Open the Inspector for this session (right after Build, per design:
            #    watch the 8 stages populate live).
            if not session_id:
                # Fallback: re-read the inspect link after build starts.
                try:
                    page.wait_for_selector("#inspectBtn:not(.hidden)", timeout=8_000)
                    href = page.get_attribute("#inspectBtn", "href") or ""
                    q = parse_qs(urlparse(href).query)
                    session_id = (q.get("session") or [""])[0]
                except PWTimeout:
                    pass

            if session_id:
                inspect_url = f"{BASE}/api/v2/inspect?session={session_id}"
                _log(f"Session id: {session_id}")
                _log(f"Opening Inspector: {inspect_url}")
                inspector = context.new_page()
                inspector.goto(inspect_url, wait_until="domcontentloaded", timeout=30_000)
                # Give the filmstrip a moment to fetch inspect-data + render.
                inspector.wait_for_timeout(2_500)
                inspector.screenshot(path="output/_drive_inspector.png", full_page=False)
                _log("Inspector opened. Screenshot: output/_drive_inspector.png")
            else:
                _log("Could not determine session id from the Inspect link.")
                _log("Open the '🔍 Inspect Pipeline' button in the browser manually.")

            _log("")
            _log("=" * 60)
            _log("Build is running in the pipeline. The two browser tabs stay")
            _log("open: tab 1 = live world build, tab 2 = 8-stage Inspector.")
            _log("This window will hold them open. Close it (or press Enter)")
            _log("when you're done reviewing.")
            _log("=" * 60)
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
            return 0

        finally:
            try:
                context.close()
                browser.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    raise SystemExit(main())
