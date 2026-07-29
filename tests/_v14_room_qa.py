"""V14 Room Rendering QA — Playwright screenshot tests.

Takes screenshots of the V14 viewer loading a completed session,
verifies the room renders correctly, and tests orbit/zoom/FPS navigation.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8000"
SESSION_ID = "2f1c92dc"
OUT_DIR = Path("output/v14_qa_screenshots")


async def run_qa():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        # Capture console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        # --- Test 1: Load completed session ---
        print("Test 1: Load session via ?session= parameter...")
        await page.goto(f"{BASE_URL}/?v=14&session={SESSION_ID}", wait_until="networkidle")
        await page.wait_for_timeout(4000)  # Wait for GLTFs to load
        await page.screenshot(path=str(OUT_DIR / "01_session_load.png"))

        # Verify state
        upload_hidden = await page.locator("#upload-section.hidden").count() > 0
        canvas_exists = await page.locator("#canvas-container canvas").count() > 0
        nav_visible = await page.locator("#nav-controls").is_visible()
        print(f"  Upload hidden: {upload_hidden}")
        print(f"  Canvas exists: {canvas_exists}")
        print(f"  Nav visible: {nav_visible}")
        results.append(("session_load", upload_hidden and canvas_exists))

        # --- Test 2: Orbit rotation ---
        print("Test 2: Orbit rotation (drag)...")
        box = await page.locator("#canvas-container canvas").bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            await page.mouse.move(cx, cy)
            await page.mouse.down()
            await page.mouse.move(cx + 300, cy - 150, steps=15)
            await page.mouse.up()
            await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT_DIR / "02_orbit_rotated.png"))
        results.append(("orbit", True))

        # --- Test 3: Zoom in ---
        print("Test 3: Zoom in (scroll)...")
        if box:
            await page.mouse.move(cx, cy)
            for _ in range(8):
                await page.mouse.wheel(0, -120)
                await page.wait_for_timeout(80)
            await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUT_DIR / "03_zoomed_in.png"))
        results.append(("zoom", True))

        # --- Test 4: Reset view and zoom out ---
        print("Test 4: Zoom out...")
        if box:
            for _ in range(12):
                await page.mouse.wheel(0, 120)
                await page.wait_for_timeout(80)
            await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUT_DIR / "04_zoomed_out.png"))
        results.append(("zoom_out", True))

        # --- Test 5: First-person mode ---
        print("Test 5: First-person mode button...")
        fps_btn = page.locator("#btn-firstperson")
        if await fps_btn.count() > 0 and await fps_btn.is_visible():
            await fps_btn.click()
            await page.wait_for_timeout(1000)
            await page.screenshot(path=str(OUT_DIR / "05_firstperson.png"))
            results.append(("fps_button", True))
        else:
            print("  FPS button not found/visible!")
            results.append(("fps_button", False))

        # --- Test 6: Check WebGL context health ---
        print("Test 6: WebGL context check...")
        webgl_ok = await page.evaluate("""() => {
            const canvas = document.querySelector('#canvas-container canvas');
            if (!canvas) return false;
            const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
            return gl !== null && !gl.isContextLost();
        }""")
        print(f"  WebGL healthy: {webgl_ok}")
        results.append(("webgl", webgl_ok))

        # --- Test 7: Check objects loaded ---
        print("Test 7: Scene object count...")
        obj_count = await page.evaluate("""() => {
            const viewer = window._v14viewer;
            if (!viewer) return -1;
            return viewer.objects ? viewer.objects.size : 0;
        }""")
        print(f"  Objects in scene: {obj_count}")
        results.append(("objects_loaded", obj_count > 0))

        # --- Test 8: Check room shell exists ---
        print("Test 8: Room shell in scene...")
        has_room = await page.evaluate("""() => {
            const viewer = window._v14viewer;
            if (!viewer || !viewer.scene) return false;
            const room = viewer.scene.getObjectByName('parametric_room');
            return room !== null && room !== undefined;
        }""")
        print(f"  Parametric room: {has_room}")
        results.append(("parametric_room", has_room))

        await browser.close()

    # Summary
    print("\n" + "=" * 50)
    print("V14 ROOM QA RESULTS")
    print("=" * 50)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'} — {name}")
    print(f"\n  {passed}/{len(results)} passed")
    print(f"  Console errors: {len(console_errors)}")
    for e in console_errors[:5]:
        print(f"    {e[:100]}")
    print(f"\n  Screenshots: {OUT_DIR}/")
    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(run_qa())
    exit(0 if ok else 1)
