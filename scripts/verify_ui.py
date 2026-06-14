"""Playwright UI smoke test: render KO/EN, run a method, assert the graph draws.

Usage: python scripts/verify_ui.py [base_url]
Starts nothing itself — point it at a running `python -m backend.app` (or the
port passed as argv). Exits non-zero on failure. Saves screenshots to runs/ui/.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parents[1] / "runs" / "ui"
OUT.mkdir(parents=True, exist_ok=True)

CASES = [("ko", "cqbycq"), ("ko", "code-de-kg"), ("en", "peshevski-product-kg")]


def check(page, lang, method):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{BASE}/{lang}/", wait_until="networkidle")
    page.click(f'.method-item[data-id="{method}"]')
    page.wait_for_selector("#runBtn", timeout=8000)
    page.click("#runBtn")
    # cytoscape renders <canvas> elements inside #graph once a graph is drawn
    page.wait_for_selector("#graph canvas", timeout=20000)
    canvases = page.eval_on_selector_all("#graph canvas", "els => els.length")
    steps = page.eval_on_selector_all("#stepRange", "els => els.length")
    shot = OUT / f"{lang}-{method}.png"
    page.screenshot(path=str(shot), full_page=True)
    ok = canvases > 0 and steps == 1
    print(f"[{ 'OK' if ok else 'FAIL'}] {lang}/{method}: canvases={canvases} "
          f"stepSlider={steps} consoleErrors={len(errors)} -> {shot.name}")
    if errors:
        for e in errors[:5]:
            print("    console.error:", e[:160])
    return ok and not errors


def main():
    all_ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        for lang, method in CASES:
            try:
                all_ok &= check(page, lang, method)
            except Exception as exc:
                all_ok = False
                print(f"[FAIL] {lang}/{method}: {exc}")
        browser.close()
    print("RESULT:", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
