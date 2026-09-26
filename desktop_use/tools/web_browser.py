from __future__ import annotations

from typing import Any

from desktop_use.tools.system_utils import SystemUtilsError


async def headless_web_scrape(
    url: str,
    action: str,
    selector: str | None = None,
    input_value: str | None = None,
) -> dict[str, Any]:
    """Use a headless browser to read or interact with a page without stealing focus."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise SystemUtilsError(
            "Playwright is not installed. Run: uv pip install playwright && playwright install chromium"
        ) from error

    normalized = action.strip().casefold()
    allowed = {"extract_text", "extract_html", "fill_input", "click"}
    if normalized not in allowed:
        raise SystemUtilsError(f"Unsupported web action: {action!r}. Use one of {sorted(allowed)}.")
    if normalized in {"fill_input", "click"} and not selector:
        raise SystemUtilsError("selector is required for fill_input and click.")
    if normalized == "fill_input" and not input_value:
        raise SystemUtilsError("input_value is required for fill_input.")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if normalized == "extract_text":
                if selector:
                    element = page.locator(selector)
                    text = await element.inner_text(timeout=10_000)
                else:
                    text = await page.inner_text("body")
                return {"url": url, "action": normalized, "text": text.strip()}

            if normalized == "extract_html":
                if selector:
                    element = page.locator(selector)
                    html = await element.inner_html(timeout=10_000)
                else:
                    html = await page.content()
                return {"url": url, "action": normalized, "html": html}

            locator = page.locator(selector)
            if normalized == "fill_input":
                await locator.fill(input_value or "", timeout=10_000)
                return {"url": url, "action": normalized, "selector": selector, "filled": True}

            await locator.click(timeout=10_000)
            return {"url": url, "action": normalized, "selector": selector, "clicked": True}
        finally:
            await browser.close()
