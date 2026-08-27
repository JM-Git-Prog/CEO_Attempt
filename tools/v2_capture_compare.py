"""V2 Refine Loop — Capture Compare screenshots for visual assessment.

Uses Playwright (headless Chromium) to:
1. Load the V2.0 session restore page
2. Wait for meshes to load
3. Capture the 3D walkthrough view
4. Click Compare and capture the split view
5. Save both to output/{session}/artifacts/refine_captures/

These captures can then be sent to a vision model for assessment.
"""
import asyncio
import sys
from pathlib import Path


async def capture(session_id: str, base_url: str = "http://127.0.0.1:8000"):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("SKIP: playwright not installed. Install with: pip install playwright && playwright install chromium")
        return None, None

    session_dir = Path(f"output/{session_id}")
    captures_dir = session_dir / "artifacts" / "refine_captures"
    captures_dir.mkdir(parents=True, exist_ok=True)

    url = f"{base_url}/?v=2.0&session={session_id}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})

        print(f"Loading: {url}")
        await page.goto(url)

        # Wait for meshes to load (check for status bar clearing or timeout)
        try:
            await page.wait_for_function(
                "() => !document.getElementById('statusBar').textContent || document.getElementById('statusBar').textContent === ''",
                timeout=60000,
            )
        except Exception:
            print("  Timeout waiting for meshes — capturing anyway")

        # Extra wait for GPU to render
        await page.wait_for_timeout(3000)

        # Capture walkthrough view
        walk_path = captures_dir / "walkthrough.png"
        await page.screenshot(path=str(walk_path))
        print(f"  Walkthrough: {walk_path}")

        # Click Compare button
        try:
            await page.click("#compareBtn", timeout=5000)
            await page.wait_for_timeout(2000)

            # Capture compare view
            compare_path = captures_dir / "compare.png"
            await page.screenshot(path=str(compare_path))
            print(f"  Compare: {compare_path}")
        except Exception as e:
            print(f"  Compare click failed: {e}")
            compare_path = None

        await browser.close()
        return str(walk_path), str(compare_path) if compare_path else None


def main():
    session_id = sys.argv[1] if len(sys.argv) > 1 else "8df83612-1b81-4428-b711-7fbabc9536bb"
    walk, compare = asyncio.run(capture(session_id))
    if walk:
        print(f"\nCaptures saved. Use vision model to assess the gap.")
    else:
        print("\nCapture failed — check playwright installation.")


if __name__ == "__main__":
    main()
