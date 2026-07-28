"""Debug game tab: use existing world if available, or wait longer."""
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}") if msg.type in ("error",) else None)
    page.goto("http://localhost:8000/?v=11", timeout=15000)
    page.wait_for_load_state("networkidle")

    # Submit prompt and wait for completion
    page.locator("#input").fill("A tiny room with a desk and chair")
    page.locator("#mvpBtn").click()
    print("Submitted prompt, waiting...")

    # Wait for world with longer timeout
    start = time.time()
    world_ready = False
    while time.time() - start < 120:
        time.sleep(5)
        state = page.locator("#stageState").inner_text()
        title = page.locator("#stageTitle").inner_text()
        print(f"  [{time.time()-start:.0f}s] state={state}, title={title}")

        # Check for ENTER GAME button OR world viewer canvas
        if page.locator("text=ENTER GAME").count() > 0:
            world_ready = True
            print(f"ENTER GAME visible at {time.time()-start:.0f}s")
            break
        if page.locator("canvas.viewer").count() > 0:
            world_ready = True
            print(f"Canvas visible at {time.time()-start:.0f}s")
            break
        if "READY" in state.upper() and "GAME" in state.upper():
            world_ready = True
            break
        if "FAILED" in state.upper() or "ERROR" in state.upper():
            print(f"Pipeline failed: {state}")
            break

    if not world_ready:
        print("World not ready — checking stageBody content...")
        html = page.locator("#stageBody").inner_html()
        print(f"  stageBody: {html[:400]}")
        page.screenshot(path="output/debug_game2_timeout.png")
        browser.close()
        exit(1)

    # Try clicking ENTER GAME
    enter_btn = page.locator("text=ENTER GAME")
    if enter_btn.count() > 0 and enter_btn.is_visible():
        enter_btn.click()
        print("Clicked ENTER GAME button")
        time.sleep(2)
    else:
        # Click GAME tab
        page.locator('[data-stage="game"]').click()
        print("Clicked GAME tab")
        time.sleep(2)

    # Verify game view
    print(f"\ncanvas.viewer: {page.locator('canvas.viewer').count()}")
    print(f"canvas: {page.locator('canvas').count()}")
    print(f"#gameOverlay: {page.locator('#gameOverlay').count()}")
    print(f".game-hud: {page.locator('.game-hud').count()}")

    active = page.locator(".stage-step.active")
    if active.count() > 0:
        print(f"Active tab: {active.get_attribute('data-stage')}")

    print(f"Stage title: {page.locator('#stageTitle').inner_text()}")
    print(f"Stage state: {page.locator('#stageState').inner_text()}")

    # Console errors
    if errors:
        print(f"\nConsole errors: {len(errors)}")
        for e in errors[:10]:
            print(f"  {e}")
    else:
        print("\nNo console errors!")

    page.screenshot(path="output/debug_game2.png")
    print("\nScreenshot: output/debug_game2.png")
    browser.close()
