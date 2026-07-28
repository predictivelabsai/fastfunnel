"""Capture deterministic FastFunnel demo frames with Playwright.

Start the app first:
    uv run python -m fastfunnel.app
Then:
    uv run playwright install chromium
    uv run python scripts/capture_demo.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "docs" / "demo" / "frames"
ROUTES = [
    ("01-dashboard.png", "/"),
    ("02-plan.png", "/plan"),
    ("03-content.png", "/content"),
    ("04-review.png", "/review"),
    ("05-calendar.png", "/calendar"),
    ("06-campaigns.png", "/campaigns"),
    ("07-integrations.png", "/integrations"),
    ("08-agency.png", "/agency"),
]


def main():
    FRAMES.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="en-GB")
        page.emulate_media(reduced_motion="reduce", color_scheme="light")
        for filename, route in ROUTES:
            page.goto(f"http://127.0.0.1:5005{route}", wait_until="networkidle")
            page.screenshot(path=FRAMES / filename, full_page=False)
        browser.close()


if __name__ == "__main__":
    main()
