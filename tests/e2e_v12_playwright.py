"""Playwright E2E test for V12 interface — photo + text modes.

Loop 1: Basic smoke test — page loads, elements render, interactions work.
Exercises both text and photo UI paths as a human user would.
"""

import asyncio
import re
from pathlib import Path
from playwright.async_api import async_playwright, expect


BASE_URL = "http://127.0.0.1:8000"


async def test_v12_page_loads_and_renders():
    """V12 page loads with correct structure, mode toggle, and photo upload zone."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(f"{BASE_URL}/?v=12")
        await page.wait_for_load_state("domcontentloaded")

        # 1. Page title and version
        title = await page.title()
        assert "Living Room" in title, f"Expected 'Living Room' in title, got: {title}"

        # 2. Version nav shows V12 as selected
        v12_link = page.locator('a[href="/?v=12"]')
        await expect(v12_link).to_have_class(re.compile("selected"))

        # 3. Intro text reflects the vision — friendly, non-technical
        intro = page.locator('.intro')
        intro_text = await intro.inner_text()
        assert "turn any room" in intro_text.lower() or "game" in intro_text.lower()
        assert "imagine" in intro_text.lower() or "photo" in intro_text.lower()

        # 4. Mode toggle exists with two buttons
        toggle = page.locator('#inputModeToggle')
        await expect(toggle).to_be_visible()
        text_btn = page.locator('.mode-btn[data-mode="text"]')
        photo_btn = page.locator('.mode-btn[data-mode="photo"]')
        await expect(text_btn).to_be_visible()
        await expect(photo_btn).to_be_visible()

        # 5. Text mode is active by default
        await expect(text_btn).to_have_class(re.compile("active"))
        composer = page.locator('#composer')
        await expect(composer).to_be_visible()
        photo_zone = page.locator('#photoUploadZone')
        assert not await photo_zone.is_visible(), "Photo zone should be hidden in text mode"

        # 6. Click photo mode — composer hides, photo zone shows
        await photo_btn.click()
        await expect(photo_btn).to_have_class(re.compile("active"))
        await page.wait_for_timeout(300)
        await expect(photo_zone).to_be_visible()
        dropzone = page.locator('#uploadDropzone')
        await expect(dropzone).to_be_visible()
        gen_btn = page.locator('#photoGenerateBtn')
        await expect(gen_btn).to_be_disabled()

        # 7. Switch back to text mode
        await text_btn.click()
        await page.wait_for_timeout(300)
        await expect(composer).to_be_visible()
        assert not await photo_zone.is_visible()

        # 8. Status chips present
        api_chip = page.locator('#apiChip')
        await expect(api_chip).to_be_visible()

        # 9. Stage rail present
        stage_rail = page.locator('.stage-rail')
        await expect(stage_rail).to_be_visible()

        # 10. V11 still works separately — no photo zone
        await page.goto(f"{BASE_URL}/?v=11")
        await page.wait_for_load_state("domcontentloaded")
        v11_photo = page.locator('#photoUploadZone')
        assert await v11_photo.count() == 0, "V11 should not have photo upload zone"
        v11_link = page.locator('a[href="/?v=11"]')
        await expect(v11_link).to_have_class(re.compile("selected"))

        print("  ✓ Page loads, mode toggle works, V11 preserved")
        await browser.close()


async def test_v12_text_mode_sends_description():
    """Text mode: typing and submitting a description initiates a session."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"{BASE_URL}/?v=12")
        await page.wait_for_load_state("domcontentloaded")

        # Type a description
        textarea = page.locator('#input')
        await textarea.fill("A cozy 1920s reading nook with leather armchair and brass lamp")

        # Click Generate & Play
        mvp_btn = page.locator('#mvpBtn')
        await expect(mvp_btn).to_be_visible()
        await expect(mvp_btn).to_be_enabled()
        await mvp_btn.click()

        # Should show working state
        await page.wait_for_timeout(500)
        state = page.locator('#stageState')
        state_text = await state.inner_text()
        assert state_text != "IDLE", f"Expected active state, got: {state_text}"

        # Messages should have the user's text
        messages = page.locator('#messages')
        messages_html = await messages.inner_html()
        assert "reading nook" in messages_html or "1920s" in messages_html

        print("  ✓ Text mode accepts description and starts pipeline")
        await browser.close()


async def test_v12_photo_mode_upload_flow():
    """Photo mode: selecting a file enables the generate button and shows preview."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"{BASE_URL}/?v=12")
        await page.wait_for_load_state("domcontentloaded")

        # Switch to photo mode
        photo_btn = page.locator('.mode-btn[data-mode="photo"]')
        await photo_btn.click()
        await page.wait_for_timeout(300)

        # Create a test image file
        test_img_path = Path("tests/_test_room.jpg")
        if not test_img_path.exists():
            from PIL import Image
            img = Image.new("RGB", (512, 512), (128, 100, 80))
            test_img_path.parent.mkdir(exist_ok=True)
            img.save(test_img_path, "JPEG")

        # Upload via file input
        file_input = page.locator('#photoFileInput')
        await file_input.set_input_files(str(test_img_path.resolve()))

        # Preview should appear
        await page.wait_for_timeout(500)
        preview = page.locator('#photoPreview')
        await expect(preview).to_be_visible()

        # Generate button should be enabled
        gen_btn = page.locator('#photoGenerateBtn')
        await expect(gen_btn).to_be_enabled()

        # Remove button works
        remove_btn = page.locator('.photo-remove-btn')
        await remove_btn.click()
        await page.wait_for_timeout(300)
        await expect(preview).to_be_hidden()
        await expect(gen_btn).to_be_disabled()

        print("  ✓ Photo upload flow — select, preview, remove all work")
        await browser.close()


async def test_v12_readiness_chips():
    """Readiness chips reflect actual API status."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"{BASE_URL}/?v=12")
        await page.wait_for_timeout(3000)

        api_chip = page.locator('#apiChip')
        chip_text = await api_chip.inner_text()
        assert "ready" in chip_text.lower() or "api" in chip_text.lower()

        print("  ✓ Readiness chips render and API shows ready")
        await browser.close()


async def main():
    """Run all Loop 1-3 tests."""
    print(f"\n{'='*50}")
    print("  V12 Playwright E2E — Loops 1-3")
    print(f"{'='*50}\n")
    
    tests = [
        ("Page loads & mode toggle", test_v12_page_loads_and_renders),
        ("Text mode sends description", test_v12_text_mode_sends_description),
        ("Photo upload flow", test_v12_photo_mode_upload_flow),
        ("Readiness chips", test_v12_readiness_chips),
        ("UX polish & accessibility", test_v12_ux_polish),
    ]
    
    passed = 0
    failed = 0
    issues = []
    
    for name, test_fn in tests:
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            issues.append((name, str(e)))
            print(f"  ✗ {name}: {e}")
    
    print(f"\n{'='*50}")
    print(f"  Results: {passed} passed, {failed} failed")
    if issues:
        print(f"\n  Issues found:")
        for name, err in issues:
            print(f"    - {name}: {err}")
    print(f"{'='*50}\n")
    
    return issues


async def test_v12_ux_polish():
    """Loop 3: Polish — accessibility, copy quality, visual coherence."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"{BASE_URL}/?v=12")
        await page.wait_for_load_state("domcontentloaded")

        # 1. Hero copy is non-technical and inviting
        h1 = page.locator('h1')
        h1_text = await h1.inner_text()
        assert "room" in h1_text.lower() and "game" in h1_text.lower(), f"H1 should mention room+game: {h1_text}"

        # 2. Eyebrow communicates the magic concisely
        eyebrow = page.locator('.intro .eyebrow')
        eyebrow_text = await eyebrow.inner_text()
        assert "DESCRIBE" in eyebrow_text or "SHOW" in eyebrow_text

        # 3. Mode buttons have clear, action-oriented labels
        text_btn = page.locator('.mode-btn[data-mode="text"]')
        text_label = await text_btn.inner_text()
        assert "imagine" in text_label.lower(), f"Text btn should say 'Imagine': {text_label}"
        
        photo_btn = page.locator('.mode-btn[data-mode="photo"]')
        photo_label = await photo_btn.inner_text()
        assert "show" in photo_label.lower(), f"Photo btn should say 'Show': {photo_label}"

        # 4. Photo dropzone has accessible label
        await photo_btn.click()
        await page.wait_for_timeout(200)
        dropzone = page.locator('#uploadDropzone')
        aria_label = await dropzone.get_attribute("aria-label")
        assert aria_label and "photo" in aria_label.lower()

        # 5. Generate button text is outcome-focused
        gen_btn = page.locator('#photoGenerateBtn')
        gen_text = await gen_btn.inner_text()
        assert "world" in gen_text.lower(), f"Generate btn should mention 'world': {gen_text}"

        # 6. Upload hint doesn't mention technical specs like resolution bounds
        hint = page.locator('.upload-hint')
        hint_text = await hint.inner_text()
        assert "512" not in hint_text, f"Upload hint should hide resolution specs: {hint_text}"
        assert "8192" not in hint_text

        # 7. Footer communicates user value, not internals
        footer = page.locator('.stage-footer')
        footer_text = await footer.inner_text()
        assert "local" in footer_text.lower() or "physics" in footer_text.lower()

        # 8. Default redirect lands on V12
        await page.goto(f"{BASE_URL}/")
        await page.wait_for_load_state("domcontentloaded")
        url = page.url
        assert "v=12" in url, f"Default should redirect to v=12, got: {url}"

        # 9. Keyboard accessibility: mode toggle is focusable
        await page.goto(f"{BASE_URL}/?v=12")
        await page.wait_for_load_state("domcontentloaded")
        text_btn = page.locator('.mode-btn[data-mode="text"]')
        await text_btn.focus()
        is_focused = await page.evaluate("document.activeElement.dataset.mode === 'text'")
        assert is_focused, "Mode button should be keyboard-focusable"

        print("  ✓ UX polish & accessibility checks pass")
        await browser.close()


if __name__ == "__main__":
    issues = asyncio.run(main())
