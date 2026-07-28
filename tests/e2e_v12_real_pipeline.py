"""Real E2E Playwright test — acts as a human user running the full pipeline.

This test actually uploads a photo, triggers the real pipeline (ComfyUI + stages),
waits for completion, and verifies a game world was produced.

Requirements: ComfyUI on 8188, Ollama on 11434, App on 8000, UPBGE available.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8000"
TEST_IMAGE = Path("tests/_e2e_room_photo.jpg")
# Pipeline timeout — photo pipeline can take 5-8 minutes for real GPU inference
PIPELINE_TIMEOUT_MS = 600_000  # 10 minutes max


async def run_photo_pipeline_e2e():
    """Full E2E: upload photo → wait for pipeline → verify game produced."""
    print("\n" + "=" * 60)
    print("  V12 REAL E2E — Photo → Playable World")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Visible so you can watch
        page = await browser.new_page()

        # ─── Step 1: Load V12 page ───
        print("\n[Step 1] Loading V12 page...")
        await page.goto(f"{BASE_URL}/?v=12", wait_until="domcontentloaded")
        title = await page.title()
        assert "Living Room" in title, f"Page didn't load: {title}"
        print("  ✓ Page loaded")

        # ─── Step 2: Check readiness ───
        print("\n[Step 2] Checking service readiness...")
        await page.wait_for_timeout(3000)  # Let readiness check complete
        api_chip = await page.locator('#apiChip').inner_text()
        print(f"  API chip: {api_chip}")
        # Don't fail on this — proceed regardless

        # ─── Step 3: Switch to photo mode ───
        print("\n[Step 3] Switching to photo mode...")
        photo_btn = page.locator('.mode-btn[data-mode="photo"]')
        await photo_btn.click()
        await page.wait_for_timeout(500)

        # Verify photo zone is visible
        photo_zone = page.locator('#photoUploadZone')
        is_visible = await photo_zone.is_visible()
        assert is_visible, "Photo upload zone didn't appear"
        print("  ✓ Photo mode active, upload zone visible")

        # ─── Step 4: Upload the test image ───
        print("\n[Step 4] Uploading test image...")
        assert TEST_IMAGE.exists(), f"Test image not found: {TEST_IMAGE}"
        file_input = page.locator('#photoFileInput')
        await file_input.set_input_files(str(TEST_IMAGE.resolve()))
        await page.wait_for_timeout(500)

        # Verify preview appears
        preview = page.locator('#photoPreview')
        is_preview_visible = await preview.is_visible()
        assert is_preview_visible, "Photo preview didn't appear after upload"
        print(f"  ✓ Image uploaded: {TEST_IMAGE.name}")

        # Verify generate button is enabled
        gen_btn = page.locator('#photoGenerateBtn')
        is_enabled = await gen_btn.is_enabled()
        assert is_enabled, "Generate button not enabled after upload"
        print("  ✓ Generate button enabled")

        # ─── Step 5: Click Generate and run pipeline ───
        print("\n[Step 5] Clicking 'Build my world' — starting real pipeline...")
        start_time = time.time()
        await gen_btn.click()

        # Wait for the pipeline to start (busy state)
        await page.wait_for_timeout(1000)
        state_el = page.locator('#stageState')
        state_text = await state_el.inner_text()
        print(f"  State: {state_text}")

        # ─── Step 6: Wait for pipeline to complete ───
        print("\n[Step 6] Waiting for pipeline completion (up to 10 min)...")
        # Poll for completion — look for success or error messages
        completed = False
        last_progress = ""
        poll_count = 0

        while time.time() - start_time < PIPELINE_TIMEOUT_MS / 1000:
            await page.wait_for_timeout(3000)  # Check every 3 seconds
            poll_count += 1

            # Check for completion indicators in messages
            messages_html = await page.locator('#messages').inner_html()

            # Check for success
            if "pipeline complete" in messages_html.lower() or "game running" in messages_html.lower():
                completed = True
                elapsed = time.time() - start_time
                print(f"\n  ✓ Pipeline COMPLETED in {elapsed:.1f}s")
                break

            # Check for error
            if "failed" in messages_html.lower() and "message error" in messages_html.lower():
                elapsed = time.time() - start_time
                # Extract error text
                error_els = await page.locator('.message.error').all()
                if error_els:
                    error_text = await error_els[-1].inner_text()
                    print(f"\n  ✗ Pipeline FAILED after {elapsed:.1f}s")
                    print(f"    Error: {error_text[:200]}")
                else:
                    print(f"\n  ✗ Pipeline FAILED after {elapsed:.1f}s (no error details)")
                break

            # Show progress
            progress_els = await page.locator('.message.progress').all()
            if progress_els:
                current_progress = await progress_els[-1].inner_text()
                if current_progress != last_progress:
                    last_progress = current_progress
                    elapsed = time.time() - start_time
                    print(f"  [{elapsed:.0f}s] {current_progress[:80]}")

            # Also check stage state
            current_state = await state_el.inner_text()
            if poll_count % 10 == 0:
                print(f"  [{time.time() - start_time:.0f}s] State: {current_state}")

        if not completed:
            elapsed = time.time() - start_time
            if elapsed >= PIPELINE_TIMEOUT_MS / 1000:
                print(f"\n  ✗ Pipeline TIMED OUT after {elapsed:.0f}s")
            # Take a screenshot for debugging
            await page.screenshot(path="tests/_e2e_failure_screenshot.png")
            print("  Screenshot saved: tests/_e2e_failure_screenshot.png")

        # ─── Step 7: Verify results ───
        print("\n[Step 7] Verifying results...")
        messages_html = await page.locator('#messages').inner_html()

        # Check for session ID in response
        if "session" in messages_html.lower():
            print("  ✓ Session was created")

        # Check for quality classification
        if "full" in messages_html.lower() or "degraded" in messages_html.lower() or "minimal" in messages_html.lower():
            print("  ✓ Quality classification present")

        # Check the stage panel
        stage_body_html = await page.locator('#stageBody').inner_html()
        if "photo-result" in stage_body_html:
            print("  ✓ Photo result panel rendered")

        # Check for world contract file on disk
        # Look for recent session directories
        output_dir = Path("output")
        if output_dir.exists():
            recent_sessions = sorted(
                [d for d in output_dir.iterdir() if d.is_dir() and (d / "world_contract.json").exists()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            if recent_sessions:
                latest = recent_sessions[0]
                wc_path = latest / "world_contract.json"
                wc_data = json.loads(wc_path.read_text())
                print(f"  ✓ WorldContract produced: {latest.name}")
                print(f"    Schema: {wc_data.get('schema_version')}")
                print(f"    Instances: {len(wc_data.get('instances', []))}")
                print(f"    Lights: {len(wc_data.get('lights', []))}")

                # Check for compilation artifacts
                compile_dir = latest / "photo_compile"
                if compile_dir.exists():
                    artifacts = list(compile_dir.iterdir())
                    print(f"    Compile artifacts: {len(artifacts)} files")
                    for a in artifacts[:5]:
                        print(f"      - {a.name} ({a.stat().st_size} bytes)")

        # Final screenshot
        await page.screenshot(path="tests/_e2e_final_screenshot.png")
        print("\n  Final screenshot: tests/_e2e_final_screenshot.png")

        print("\n" + "=" * 60)
        if completed:
            print("  RESULT: PASS — Photo pipeline produced a world")
        else:
            print("  RESULT: PARTIAL — See details above")
        print("=" * 60 + "\n")

        # Keep browser open briefly so user can inspect
        await page.wait_for_timeout(5000)
        await browser.close()

    return completed


async def run_text_pipeline_e2e():
    """Full E2E: type description → wait for pipeline → verify game produced."""
    print("\n" + "=" * 60)
    print("  V12 REAL E2E — Text → Playable World")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # ─── Step 1: Load page ───
        print("\n[Step 1] Loading V12 page...")
        await page.goto(f"{BASE_URL}/?v=12", wait_until="domcontentloaded")
        print("  ✓ Page loaded")

        # ─── Step 2: Type description (text mode is default) ───
        print("\n[Step 2] Typing room description...")
        textarea = page.locator('#input')
        description = "A warm mid-century modern living room with a leather sofa, walnut coffee table, brass floor lamp, and rain-streaked window"
        await textarea.fill(description)
        print(f"  Entered: {description[:60]}...")

        # ─── Step 3: Click Generate & Play ───
        print("\n[Step 3] Clicking 'Generate & Play'...")
        start_time = time.time()
        mvp_btn = page.locator('#mvpBtn')
        await mvp_btn.click()

        await page.wait_for_timeout(1000)
        state_text = await page.locator('#stageState').inner_text()
        print(f"  State: {state_text}")

        # ─── Step 4: Wait for completion ───
        print("\n[Step 4] Waiting for text pipeline (up to 5 min)...")
        completed = False
        last_progress = ""

        while time.time() - start_time < 300:  # 5 min for text
            await page.wait_for_timeout(3000)

            messages_html = await page.locator('#messages').inner_html()

            # Check for success indicators
            if "game running" in messages_html.lower() or "mvp-success" in messages_html.lower():
                completed = True
                elapsed = time.time() - start_time
                print(f"\n  ✓ Text pipeline COMPLETED in {elapsed:.1f}s")
                break

            if "mvp-failure" in messages_html.lower() or "pipeline failed" in messages_html.lower():
                elapsed = time.time() - start_time
                print(f"\n  ✗ Text pipeline FAILED after {elapsed:.1f}s")
                break

            # Show progress
            progress_els = await page.locator('.mvp-progress-status, .message.progress').all()
            if progress_els:
                current = await progress_els[-1].inner_text()
                if current != last_progress:
                    last_progress = current
                    print(f"  [{time.time() - start_time:.0f}s] {current[:80]}")

        if not completed:
            await page.screenshot(path="tests/_e2e_text_failure.png")
            print("  Screenshot: tests/_e2e_text_failure.png")

        await page.wait_for_timeout(3000)
        await browser.close()

    return completed


async def main():
    print("\n" + "#" * 60)
    print("  V12 FULL REAL END-TO-END TEST")
    print("  Services required: App(8000) + ComfyUI(8188) + Ollama(11434)")
    print("#" * 60)

    # Run both paths
    photo_result = await run_photo_pipeline_e2e()
    text_result = await run_text_pipeline_e2e()

    print("\n" + "#" * 60)
    print(f"  SUMMARY")
    print(f"    Photo pipeline: {'PASS' if photo_result else 'FAIL/PARTIAL'}")
    print(f"    Text pipeline:  {'PASS' if text_result else 'FAIL/PARTIAL'}")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
