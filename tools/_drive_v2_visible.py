"""Open a VISIBLE browser and drive both v2.1 and v2.0 so John can watch.
Two tabs: v2.1 panorama room (restore session) + v2.0 for comparison.
Keeps the browser open until Enter is pressed in this terminal.
"""
import asyncio
from playwright.async_api import async_playwright

SID = "40d1662f-69d5-4895-8745-65b8456d642f"
BASE = "http://127.0.0.1:8000"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--enable-unsafe-swiftshader"],
        )
        ctx = await browser.new_context(no_viewport=True)

        # Tab 1: V2.1 panorama room (restore the built session)
        pano = await ctx.new_page()
        await pano.goto(f"{BASE}/?v=2.1&session={SID}", wait_until="load")
        await pano.wait_for_timeout(6000)
        # Slowly orbit the view so the 360 room is obvious: drag across the canvas.
        box = await pano.evaluate("() => { const c=document.querySelector('#scene canvas'); const r=c.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; }")
        cx = box["x"] + box["w"] / 2
        cy = box["y"] + box["h"] / 2
        await pano.mouse.move(cx, cy)
        for dx in range(0, 900, 30):
            await pano.mouse.move(cx - dx, cy, steps=2)
            await pano.wait_for_timeout(60)

        # Tab 2: V2.0 for side-by-side comparison
        v20 = await ctx.new_page()
        await v20.goto(f"{BASE}/?v=2.0", wait_until="load")
        await v20.wait_for_timeout(1500)

        # Bring the panorama tab back to the front
        await pano.bring_to_front()

        print("Both tabs open. V2.1 panorama room (front) + V2.0.")
        print("Browser will stay open. Press Enter here to close it.")
        # Hold open until Enter (run this from an interactive terminal).
        await asyncio.get_event_loop().run_in_executor(None, input)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
