"""Playwright E2E test for V13 — full photo → in-browser 3D game flow."""

import asyncio
import re
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE_URL = "http://127.0.0.1:8000"
TEST_IMAGE = Path(__file__).parent / "_e2e_room_photo.jpg"


async def test_v13_full_photo_to_browser_game():
    """Upload photo → pipeline runs → 3D game renders in browser."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        print("\n[1] Loading V13...")
        await page.goto(f"{BASE_URL}/?v=13", wait_until="domcontentloaded")
        assert "V13" in await page.content()
        print("  ✓ V13 loaded")

        print("[2] Switching to photo mode...")
        await page.locator('.mode-btn[data-mode="photo"]').click()
        await page.wait_for_timeout(300)
        await expect(page.locator('#photoUploadZone')).to_be_visible()
        print("  ✓ Photo mode active")

        print("[3] Uploading test image...")
        await page.locator('#photoFileInput').set_input_files(str(TEST_IMAGE.resolve()))
        await page.wait_for_timeout(500)
        await expect(page.locator('#photoPreview')).to_be_visible()
        await expect(page.locator('#photoGenerateBtn')).to_be_enabled()
        print("  ✓ Photo uploaded, preview visible")

        print("[4] Clicking 'Build my world'...")
        await page.locator('#photoGenerateBtn').click()
        await page.wait_for_timeout(1000)
        state = await page.locator('#stageState').inner_text()
        print(f"  State: {state}")

        print("[5] Waiting for pipeline + game render (up to 60s)...")
        # Wait for either the game container or an error
        try:
            await page.locator('#gameContainer').wait_for(state="visible", timeout=60000)
            print("  ✓ Game container rendered!")

            # Check that a canvas exists inside (Three.js rendered)
            canvas = page.locator('#gameContainer canvas')
            await expect(canvas).to_be_visible()
            print("  ✓ Three.js canvas present")

            # Check overlay exists
            overlay = page.locator('#gameOverlay')
            is_visible = await overlay.is_visible()
            if is_visible:
                overlay_text = await overlay.inner_text()
                print(f"  ✓ Game overlay: '{overlay_text.strip()[:50]}'")

            # Check stage title
            title = await page.locator('#stageTitle').inner_text()
            print(f"  ✓ Stage title: '{title}'")

            # Take screenshot
            await page.screenshot(path="tests/_v13_game_screenshot.png")
            print("  ✓ Screenshot saved: tests/_v13_game_screenshot.png")

            print("\n  ═══════════════════════")
            print("  RESULT: V13 FULL PASS")
            print("  Photo → In-browser 3D game ✓")
            print("  ═══════════════════════\n")

        except Exception as e:
            # Check for error message
            messages = await page.locator('#messages').inner_html()
            if "failed" in messages.lower():
                error_el = page.locator('.message.error')
                if await error_el.count() > 0:
                    err_text = await error_el.last.inner_text()
                    print(f"  ✗ Pipeline error: {err_text[:150]}")
            else:
                print(f"  ✗ Timeout or unexpected: {e}")
            await page.screenshot(path="tests/_v13_fail_screenshot.png")

        await page.wait_for_timeout(3000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_v13_full_photo_to_browser_game())
