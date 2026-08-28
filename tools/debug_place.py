"""Debug the placement page with Playwright — find why it's blank."""
import asyncio
from playwright.async_api import async_playwright


async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        url = "http://127.0.0.1:8000/api/v2/place?session=8df83612-1b81-4428-b711-7fbabc9536bb"
        print(f"Loading: {url}")

        errors = []
        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: errors.append(str(err)))

        resp = await page.goto(url, wait_until="networkidle")
        print(f"Status: {resp.status}")

        await page.wait_for_timeout(5000)

        # Print console output
        for log in logs:
            print(f"  {log}")
        for err in errors:
            print(f"  ERROR: {err}")

        # Check Canon image
        img_info = await page.evaluate("""() => {
            const img = document.getElementById('canon-bg');
            return img ? {src: img.src.slice(-40), w: img.naturalWidth, h: img.naturalHeight, complete: img.complete} : 'NOT FOUND';
        }""")
        print(f"Canon img: {img_info}")

        # Check sidebar
        obj_count = await page.evaluate("() => document.querySelectorAll('.obj-card').length")
        print(f"Object cards in sidebar: {obj_count}")

        # Check body visibility
        body_bg = await page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        print(f"Body bg: {body_bg}")

        # Screenshot
        await page.screenshot(path="output/debug_place.png")
        print("Screenshot saved: output/debug_place.png")

        await browser.close()


asyncio.run(debug())
