"""Measure the web UI in a real browser: overflow and tap targets, every screen, theme and width.

Run on a COPY of a database (the script copies it again and migrates the copy):

    uv run --with playwright python -m playwright install chromium     # once
    uv run --with playwright python scripts/ui_audit.py --db /path/copy.db --out /tmp/audit

It logs in as the admin of a throwaway app, renders each page to HTML with the stylesheet
inlined, opens it in Chromium and reports, per page, theme and width:

- horizontal overflow (the page scrolls sideways, or an element sticks out of the viewport);
- tap targets smaller than 40 px on phone widths (a finger needs about 44 px, 40 is the floor);
  a control inside a label counts as the label, and the hidden skip link is ignored.

Exit status 1 when anything overflows; small targets are reported but do not fail the run.
"""

import argparse
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from velkgram.apps.cli import MIGRATION_PACKAGES
from velkgram.apps.web.auth import hash_password
from velkgram.apps.web.main import create_app
from velkgram.shared.config import Settings
from velkgram.shared.db import connect
from velkgram.shared.migrate import apply_migrations

PASSWORD = "audit-password"
THEMES = ("dark", "light")
WIDTHS = (320, 360, 390, 768, 1139, 1440)
PHONE_MAX = 600
MIN_TAP = 40
STATIC = Path(__file__).parents[1] / "velkgram" / "apps" / "web" / "static"

_MEASURE_JS = """() => {
  const vw = document.documentElement.clientWidth;
  const fixed = (e) => getComputedStyle(e).position === 'fixed';
  const name = (e) => e.tagName.toLowerCase() + '.' + String(e.className).slice(0, 22);
  const out = [...document.querySelectorAll('body *')]
    .filter((e) => {
      const r = e.getBoundingClientRect();
      return r.width > 0 && !fixed(e) && (r.right > vw + 1 || r.left < -1);
    })
    .slice(0, 3)
    .map(name);
  const tappable = 'a[href], button, input:not([type=hidden]), select';
  const small = [...document.querySelectorAll(tappable)]
    .filter((e) => !e.classList.contains('sr-only'))
    .map((e) => [e, (e.closest('label') || e).getBoundingClientRect()])
    .filter(([e, r]) => {
      const hidden = getComputedStyle(e).visibility === 'hidden';
      return r.width > 0 && r.height > 0 && !hidden && (r.height < MIN || r.width < MIN);
    })
    .map(([e, r]) => {
      return name(e) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height);
    });
  return {scroll: document.documentElement.scrollWidth, vw, out, small};
}"""
MEASURE = _MEASURE_JS.replace("MIN", str(MIN_TAP))


def _render(client: TestClient, path: str, css: str) -> str:
    html = client.get(path).text
    html = re.sub(r"<link[^>]*velkgram\.css[^>]*>", lambda _: f"<style>{css}</style>", html)
    return re.sub(r"<script[^>]*velkgram\.js[^>]*></script>", "", html)


def _pages(db: Path) -> list[str]:
    pages = ["/", "/cupons", "/wishes", "/alerts", "/channels", "/status", "/usuarios", "/perfil"]
    conn = sqlite3.connect(db)
    try:
        offer = conn.execute(
            "SELECT channel_id, message_id FROM offers WHERE kind = 'product' "
            "AND price_cents IS NOT NULL ORDER BY posted_at DESC LIMIT 1"
        ).fetchone()
        wish = conn.execute("SELECT id FROM wishes ORDER BY id LIMIT 1").fetchone()
    finally:
        conn.close()
    if offer:
        pages.append(f"/produto/{offer[0]}/{offer[1]}")
    if wish:
        pages.append(f"/wishes/{wish[0]}")
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--themes", nargs="*", default=list(THEMES))
    parser.add_argument("--widths", nargs="*", type=int, default=list(WIDTHS))
    parser.add_argument("--shots", action="store_true", help="save a screenshot of every case")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    work = Path(tempfile.mkdtemp(prefix="ui-audit-"))
    db = work / "audit.db"
    shutil.copy(args.db, db)
    conn = connect(db)
    apply_migrations(conn, MIGRATION_PACKAGES)
    conn.close()
    app = create_app(
        Settings(db_path=db, web_password_hash=hash_password(PASSWORD), web_secret_key="k")
    )
    client = TestClient(app, follow_redirects=False)
    assert (
        client.post("/login", data={"username": "admin", "password": PASSWORD}).status_code == 303
    )
    css = (STATIC / "velkgram.css").read_text()
    args.out.mkdir(parents=True, exist_ok=True)
    overflows = small_targets = cases = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in args.themes:
            client.cookies.set("theme", theme)
            for path in _pages(db):
                name = re.sub(r"\W+", "_", path).strip("_") or "feed"
                html_path = work / f"{theme}-{name}.html"
                html_path.write_text(_render(client, path, css))
                for width in args.widths:
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.goto(f"file://{html_path}", wait_until="networkidle")
                    found = page.evaluate(MEASURE)
                    cases += 1
                    bad = found["scroll"] > found["vw"] + 1 or bool(found["out"])
                    small = found["small"] if width <= PHONE_MAX else []
                    overflows += bad
                    small_targets += bool(small)
                    if bad or small:
                        flag = "OVERFLOW" if bad else "tap"
                        detail = f"{found['out'] or ''} {small[:3] or ''}"
                        print(f"{flag:8} {theme:13} {width:5}px {path}  {detail}")
                    if args.shots:
                        page.screenshot(path=str(args.out / f"{theme}-{name}-{width}.png"))
                    page.close()
        browser.close()
    shutil.rmtree(work, ignore_errors=True)
    print(
        f"\n{cases} cases | overflow: {overflows} | "
        f"phone widths with targets under {MIN_TAP}px: {small_targets}"
    )
    return 1 if overflows else 0


if __name__ == "__main__":
    sys.exit(main())
