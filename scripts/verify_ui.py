"""
verify_ui.py
Automated Headless Playwright Verification Harness for Badge3D Coin Studio
Triple-Viewport Responsiveness, Zero Console Errors, Zero Horizontal Overflow,
and 100% Open-Access Export Verification.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SHOT_DIR = Path(os.environ.get("BADGE3D_SHOT_DIR", Path(tempfile.gettempdir()) / "badge3d_shots"))
SHOT_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(os.environ.get("PORT", "8084"))
BASE_URL = f"http://127.0.0.1:{PORT}"


def verify() -> int:
    print(f"[TEST] Starting Playwright Headless Verification on {BASE_URL}...")

    viewports = [
        {"name": "home_mobile.jpg", "width": 390, "height": 844, "device": "Mobile"},
        {"name": "home_tablet.jpg", "width": 820, "height": 1180, "device": "Tablet"},
        {"name": "home_desktop.jpg", "width": 1425, "height": 900, "device": "Desktop"},
    ]

    results = {"viewports": [], "openAccessPass": False, "consoleErrors": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )

        for vp in viewports:
            page = browser.new_page(viewport={"width": vp["width"], "height": vp["height"]})
            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            page.goto(BASE_URL, wait_until="networkidle")
            time.sleep(0.5)

            overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            shot_path = SHOT_DIR / vp["name"]
            page.screenshot(path=str(shot_path), full_page=False, type="jpeg", quality=85)

            passed = len(console_errors) == 0 and overflow <= 1
            print(f"[VIEWPORT] {vp['device']}: ConsoleErrors={len(console_errors)}, Overflow={overflow}px -> {'PASS' if passed else 'FAIL'}")

            for err in console_errors:
                results["consoleErrors"].append(f"[{vp['device']}] {err}")

            results["viewports"].append({"device": vp["device"], "passed": passed})
            page.close()

        page = browser.new_page(viewport={"width": 1425, "height": 900})
        page.goto(BASE_URL, wait_until="networkidle")
        results["openAccessPass"] = page.locator("#btn-export-stl").is_visible()
        page.close()
        browser.close()

    all_passed = (
        len(results["consoleErrors"]) == 0
        and results["openAccessPass"]
        and all(v["passed"] for v in results["viewports"])
    )
    print(f"OVERALL RESULT: {'ALL PASS' if all_passed else 'FAIL'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(verify())
