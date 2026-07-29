"""Quick check: does V14 render a Three.js canvas on page load?"""
import asyncio
from playwright.async_api import async_playwright

async def check():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("http://127.0.0.1:8000/?v=14", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        has_canvas = await page.evaluate("() => document.querySelector('#canvas-container canvas') !== null")
        nav_visible = await page.is_visible("#nav-controls")
        title = await page.title()
        print(f"Title: {title}")
        print(f"Canvas rendered: {has_canvas}")
        print(f"Nav controls visible: {nav_visible}")
        await browser.close()

asyncio.run(check())
