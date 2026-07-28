"""Debug the game tab activation flow."""
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}") if msg.type in ("error", "warning") else None)
    page.goto("http://localhost:8000/?v=11", timeout=15000)
    page.wait_for_load_state("networkidle")

    # Submit prompt
    page.locator("#input").fill("A small bedroom with a bed and door")
    page.locator("#mvpBtn").click()

    # Wait for ENTER GAME button
    start = time.time()
    while time.time() - start < 90:
        time.sleep(3)
        btn = page.locator("text=ENTER GAME")
        if btn.count() > 0 and btn.is_visible():
            print(f"World ready at {time.time()-start:.0f}s")
            break
        state = page.locator("#stageState").inner_text()
        if "READY" in state.upper():
            print(f"State READY at {time.time()-start:.0f}s")
            break
    else:
        print("TIMEOUT waiting for world")
        browser.close()
        exit(1)

    # Click ENTER GAME
    enter_btn = page.locator("text=ENTER GAME")
    if enter_btn.count() > 0:
        enter_btn.click()
        print("Clicked ENTER GAME")
    else:
        # Try clicking the GAME tab
        page.locator('[data-stage="game"]').click()
        print("Clicked GAME tab")

    time.sleep(2)

    # Debug stageBody contents
    stage_body = page.locator("#stageBody")
    html = stage_body.inner_html()
    print(f"stageBody length: {len(html)}")
    print(f"First 600 chars:\n{html[:600]}")
    print()

    # Check selectors
    print(f"canvas.viewer: {page.locator('canvas.viewer').count()}")
    print(f"canvas: {page.locator('canvas').count()}")
    print(f"#gameOverlay: {page.locator('#gameOverlay').count()}")
    print(f".game-hud: {page.locator('.game-hud').count()}")

    # Active tab
    active = page.locator(".stage-step.active")
    if active.count() > 0:
        print(f"Active tab: {active.get_attribute('data-stage')}")
    else:
        print("No active tab")

    # Stage title
    print(f"Stage title: {page.locator('#stageTitle').inner_text()}")
    print(f"Stage state: {page.locator('#stageState').inner_text()}")

    # Console errors
    print(f"\nConsole errors/warnings: {len(errors)}")
    for e in errors[:15]:
        print(f"  {e}")

    page.screenshot(path="output/debug_game.png")
    print("\nScreenshot: output/debug_game.png")
    browser.close()
