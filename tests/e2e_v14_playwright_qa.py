"""Playwright E2E QA tests for V14 - headless roundtrip + human-like interaction.

Round 1-5: Headless browser roundtrip tests (fast, no GUI)
Round 6-10: Human-like interaction tests (visible browser, realistic timing)

Each round submits a photo, waits for the V14 pipeline, and validates
the 3D world output. Iterates and logs findings for UI/UX improvement.

Prerequisites:
- Server running at http://127.0.0.1:8000
- ComfyUI running at localhost:8188 (for real mesh generation)
- Playwright chromium installed: python -m playwright install chromium

Usage:
    python tests/e2e_v14_playwright_qa.py
    python tests/e2e_v14_playwright_qa.py --headless-only
    python tests/e2e_v14_playwright_qa.py --human-only
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright, Page, expect

BASE_URL = "http://127.0.0.1:8000"
TEST_PHOTOS = [
    Path(__file__).parent / "_v14_neon_bedroom.jpg",
    Path(__file__).parent / "_v14_kids_bedroom.jpg",
]
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "v14_qa_screenshots"


@dataclass
class RoundResult:
    """Result of a single QA round."""
    round_num: int
    photo: str
    headless: bool
    duration_s: float
    page_loaded: bool = False
    upload_worked: bool = False
    pipeline_started: bool = False
    pipeline_completed: bool = False
    objects_count: int = 0
    room_shell_loaded: bool = False
    threejs_rendered: bool = False
    navigation_works: bool = False
    errors: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    screenshot_path: str = ""


async def run_headless_roundtrip(
    round_num: int, photo_path: Path
) -> RoundResult:
    """Run a single headless roundtrip test.

    1. Load V14 page
    2. Submit photo via API (since headless can't do drag-drop easily)
    3. Connect to SSE and wait for completion
    4. Verify Three.js scene rendered
    5. Take screenshot
    """
    result = RoundResult(
        round_num=round_num,
        photo=photo_path.name,
        headless=True,
        duration_s=0.0,
    )
    start = time.monotonic()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # 1. Load V14 page
            response = await page.goto(f"{BASE_URL}/?v=14", wait_until="networkidle")
            result.page_loaded = response is not None and response.status == 200

            if not result.page_loaded:
                result.errors.append(f"Page load failed: status={response.status if response else 'None'}")
                return result

            # Check for V14-specific elements
            title = await page.title()
            if "V14" in title or "Living Room" in title:
                result.findings.append(f"Page title: {title}")

            # 2. Submit photo via API
            import httpx
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{BASE_URL}/api/session/v14/photo",
                    json={"source_image": str(photo_path.resolve())},
                )

            if resp.status_code == 200:
                result.upload_worked = True
                session_data = resp.json()
                session_id = session_data.get("session_id")
                result.pipeline_started = session_data.get("state") == "started"
                result.findings.append(f"Session created: {session_id}")
            else:
                result.errors.append(f"Photo upload failed: {resp.status_code} - {resp.text[:200]}")
                return result

            # 3. Wait for pipeline completion via SSE polling
            if session_id:
                max_wait = 15  # 15 seconds - just check if pipeline kicks off
                poll_start = time.monotonic()
                completed = False

                while time.monotonic() - poll_start < max_wait:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        try:
                            meta_resp = await client.get(
                                f"{BASE_URL}/api/session/{session_id}/room_shell"
                            )
                            if meta_resp.status_code == 200:
                                result.room_shell_loaded = True
                                completed = True
                                break
                        except Exception:
                            pass

                    await asyncio.sleep(2.0)

                if completed:
                    result.pipeline_completed = True
                    result.findings.append(f"Pipeline completed in {time.monotonic() - poll_start:.1f}s")
                else:
                    result.findings.append(f"Pipeline still running after {max_wait}s (expected - ComfyUI needed)")
                    result.pipeline_completed = False

            # 4. Navigate to the V14 viewer page and check Three.js
            await page.goto(f"{BASE_URL}/?v=14", wait_until="networkidle")
            await page.wait_for_timeout(2000)

            # Check if canvas element exists (Three.js renders to canvas)
            canvas = page.locator("#canvas-container canvas")
            canvas_count = await canvas.count()
            result.threejs_rendered = canvas_count > 0
            if canvas_count > 0:
                result.findings.append("Three.js canvas rendered")
            else:
                result.findings.append("No Three.js canvas found")

            # Check WebGL context
            has_webgl = await page.evaluate("""() => {
                const canvas = document.querySelector('#canvas-container canvas');
                if (!canvas) return false;
                const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
                return gl !== null;
            }""")
            if has_webgl:
                result.findings.append("WebGL context active")

            # 5. Take screenshot
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            ss_path = OUTPUT_DIR / f"headless_round{round_num}_{photo_path.stem}.png"
            await page.screenshot(path=str(ss_path), full_page=True)
            result.screenshot_path = str(ss_path)

            # Check navigation controls
            nav_controls = page.locator("#nav-controls")
            if await nav_controls.count() > 0:
                is_visible = await nav_controls.is_visible()
                result.navigation_works = is_visible
                result.findings.append(f"Nav controls visible: {is_visible}")

        except Exception as exc:
            result.errors.append(f"Exception: {type(exc).__name__}: {exc}")

        finally:
            await browser.close()

    result.duration_s = time.monotonic() - start
    return result


async def run_human_like_test(
    round_num: int, photo_path: Path
) -> RoundResult:
    """Run a human-like interaction test with visible browser.

    Simulates a real user:
    1. Opens the page
    2. Looks around the UI
    3. Uploads a photo (via file input)
    4. Watches the progress indicator
    5. Tries orbit and first-person navigation
    6. Takes screenshots at key moments
    """
    result = RoundResult(
        round_num=round_num,
        photo=photo_path.name,
        headless=False,
        duration_s=0.0,
    )
    start = time.monotonic()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=500,  # 500ms delay between actions (human-like)
        )
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        try:
            # 1. Open V14 page
            await page.goto(f"{BASE_URL}/?v=14", wait_until="networkidle")
            result.page_loaded = True
            await page.wait_for_timeout(1000)  # Human looks at page

            # 2. Check UI elements visible to user
            # Version nav
            v14_link = page.locator('a[href="/?v=14"]')
            if await v14_link.count() > 0:
                is_selected = await v14_link.get_attribute("class") or ""
                result.findings.append(f"V14 nav link: class='{is_selected}'")

            # Upload section
            upload_section = page.locator("#upload-section")
            if await upload_section.count() > 0 and await upload_section.is_visible():
                result.findings.append("Upload section visible - good first impression")

            # 3. Upload photo via file input
            file_input = page.locator("#photo-file-input")
            if await file_input.count() > 0:
                await file_input.set_input_files(str(photo_path.resolve()))
                result.upload_worked = True
                await page.wait_for_timeout(1000)

                # Check preview appears
                preview = page.locator("#photo-preview")
                if await preview.count() > 0:
                    is_visible = await preview.is_visible()
                    result.findings.append(f"Photo preview visible: {is_visible}")

                # Click "Build my world" button
                build_btn = page.locator("#build-btn")
                if await build_btn.count() > 0 and await build_btn.is_visible():
                    await build_btn.click()
                    result.pipeline_started = True
                    result.findings.append("Clicked 'Build my world' button")
                else:
                    # Try API submission as fallback
                    import httpx
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.post(
                            f"{BASE_URL}/api/session/v14/photo",
                            json={"source_image": str(photo_path.resolve())},
                        )
                    if resp.status_code == 200:
                        result.pipeline_started = True
                        result.findings.append("Submitted via API (button not found)")
            else:
                result.findings.append("No file input found - UI issue")
                # Fallback: API submission
                import httpx
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{BASE_URL}/api/session/v14/photo",
                        json={"source_image": str(photo_path.resolve())},
                    )
                if resp.status_code == 200:
                    result.upload_worked = True
                    result.pipeline_started = True

            # 4. Watch progress (human waits patiently)
            if result.pipeline_started:
                progress_overlay = page.locator("#progress-overlay")
                if await progress_overlay.count() > 0:
                    # Wait for progress to appear
                    await page.wait_for_timeout(2000)
                    is_visible = await progress_overlay.is_visible()
                    if is_visible:
                        result.findings.append("Progress overlay visible during generation")

                # Screenshot during generation
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                ss_progress = OUTPUT_DIR / f"human_round{round_num}_progress_{photo_path.stem}.png"
                await page.screenshot(path=str(ss_progress))

                # Wait briefly (don't block on full pipeline - ComfyUI needed)
                await page.wait_for_timeout(3000)

            # 5. Try navigation
            canvas = page.locator("#canvas-container canvas")
            if await canvas.count() > 0:
                result.threejs_rendered = True

                # Try orbit: click and drag on canvas
                box = await canvas.bounding_box()
                if box:
                    # Orbit drag
                    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    await page.mouse.down()
                    await page.mouse.move(box["x"] + box["width"] / 2 + 100, box["y"] + box["height"] / 2)
                    await page.mouse.up()
                    result.findings.append("Performed orbit drag on canvas")
                    await page.wait_for_timeout(500)

                # Try first-person mode
                fps_btn = page.locator("#btn-firstperson")
                if await fps_btn.count() > 0 and await fps_btn.is_visible():
                    await fps_btn.click()
                    result.navigation_works = True
                    result.findings.append("Clicked first-person mode button")
                    await page.wait_for_timeout(1000)

            # 6. Final screenshot
            ss_final = OUTPUT_DIR / f"human_round{round_num}_final_{photo_path.stem}.png"
            await page.screenshot(path=str(ss_final))
            result.screenshot_path = str(ss_final)

        except Exception as exc:
            result.errors.append(f"Exception: {type(exc).__name__}: {exc}")

        finally:
            await page.wait_for_timeout(2000)  # Let human see final state
            await browser.close()

    result.duration_s = time.monotonic() - start
    return result


def print_result(r: RoundResult) -> None:
    """Print a formatted result summary."""
    status = "PASS" if not r.errors else "FAIL"
    mode = "HEADLESS" if r.headless else "HUMAN"
    print(f"\n{'='*60}")
    print(f"  {status} Round {r.round_num} [{mode}] - {r.photo} ({r.duration_s:.1f}s)")
    print(f"{'='*60}")
    print(f"  Page loaded:        {'Y' if r.page_loaded else 'N'}")
    print(f"  Upload worked:      {'Y' if r.upload_worked else 'N'}")
    print(f"  Pipeline started:   {'Y' if r.pipeline_started else 'N'}")
    print(f"  Pipeline completed: {'Y' if r.pipeline_completed else 'N'}")
    print(f"  Room shell loaded:  {'Y' if r.room_shell_loaded else 'N'}")
    print(f"  Three.js rendered:  {'Y' if r.threejs_rendered else 'N'}")
    print(f"  Navigation works:   {'Y' if r.navigation_works else 'N'}")
    if r.findings:
        print(f"  Findings:")
        for f in r.findings:
            print(f"    - {f}")
    if r.errors:
        print(f"  Errors:")
        for e in r.errors:
            print(f"    ! {e}")
    if r.screenshot_path:
        print(f"  Screenshot: {r.screenshot_path}")


async def main():
    """Run all 10 QA rounds: 5 headless + 5 human-like."""
    args = sys.argv[1:]
    run_headless = "--human-only" not in args
    run_human = "--headless-only" not in args

    # Verify test photos exist
    for photo in TEST_PHOTOS:
        if not photo.exists():
            print(f"! Test photo not found: {photo}")
            print("  Run from project root or create test photos first.")
            return

    results: list[RoundResult] = []

    # --- HEADLESS ROUNDS (1-5) ---
    if run_headless:
        print("\n" + "=" * 60)
        print("  HEADLESS ROUNDTRIP TESTS (Rounds 1-5)")
        print("=" * 60)

        for i in range(5):
            photo = TEST_PHOTOS[i % len(TEST_PHOTOS)]
            print(f"\n  Starting headless round {i+1} with {photo.name}...")
            r = await run_headless_roundtrip(i + 1, photo)
            results.append(r)
            print_result(r)

    # --- HUMAN-LIKE ROUNDS (6-10) ---
    if run_human:
        print("\n" + "=" * 60)
        print("  HUMAN-LIKE QA TESTS (Rounds 6-10)")
        print("=" * 60)

        for i in range(5):
            photo = TEST_PHOTOS[i % len(TEST_PHOTOS)]
            print(f"\n  Starting human-like round {i+6} with {photo.name}...")
            r = await run_human_like_test(i + 6, photo)
            results.append(r)
            print_result(r)

    # --- SUMMARY ---
    print("\n" + "=" * 60)
    print("  OVERALL SUMMARY")
    print("=" * 60)
    total = len(results)
    passed = sum(1 for r in results if not r.errors)
    page_ok = sum(1 for r in results if r.page_loaded)
    upload_ok = sum(1 for r in results if r.upload_worked)
    pipeline_ok = sum(1 for r in results if r.pipeline_completed)
    threejs_ok = sum(1 for r in results if r.threejs_rendered)
    nav_ok = sum(1 for r in results if r.navigation_works)

    print(f"  Total rounds:       {total}")
    print(f"  Error-free:         {passed}/{total}")
    print(f"  Page loads:         {page_ok}/{total}")
    print(f"  Uploads:            {upload_ok}/{total}")
    print(f"  Pipeline completes: {pipeline_ok}/{total}")
    print(f"  Three.js renders:   {threejs_ok}/{total}")
    print(f"  Navigation works:   {nav_ok}/{total}")
    print(f"\n  Screenshots: {OUTPUT_DIR}")

    # Save results as JSON for iteration tracking
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results_path = OUTPUT_DIR / "qa_results.json"
    results_json = [
        {
            "round": r.round_num,
            "photo": r.photo,
            "headless": r.headless,
            "duration_s": r.duration_s,
            "page_loaded": r.page_loaded,
            "upload_worked": r.upload_worked,
            "pipeline_started": r.pipeline_started,
            "pipeline_completed": r.pipeline_completed,
            "room_shell_loaded": r.room_shell_loaded,
            "threejs_rendered": r.threejs_rendered,
            "navigation_works": r.navigation_works,
            "errors": r.errors,
            "findings": r.findings,
        }
        for r in results
    ]
    results_path.write_text(json.dumps(results_json, indent=2))
    print(f"  Results JSON: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
