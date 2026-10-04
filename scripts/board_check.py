"""Write the board for a lab and drive every control on it, asserting the page's structure after each step.

    uv run --with playwright scripts/board_check.py <lab dir>

Run it after any change to src/lab/views/web/board.*; it must report 0 failing steps. It checks, at desktop,
tablet and phone widths: one chart and one Next section, the run panel showing the selected run, no sideways
overflow, no number cell cut off, tables as wide as their card, and no script errors.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

STATE = """() => {
  const q = s => document.querySelectorAll(s).length, h = location.hash, insp = document.getElementById('insp');
  const panel = insp.classList.contains('open') || innerWidth > 1100;
  const wide = [...document.querySelectorAll('#mainin *' + (panel ? ', #insp *' : ''))]
    .filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1; }).slice(0, 3).map(e => e.className || e.tagName);
  const clipped = [...document.querySelectorAll('.c-id, .c-v, .c-d, .c-c, .at td, .ph-v, .rh-v, .vs-v')]
    .filter(e => e.offsetParent && e.scrollWidth > e.clientWidth + 1).slice(0, 3).map(e => e.className + ': ' + e.textContent.trim().slice(0, 12));
  const t = document.querySelector('table.runs'), tb = document.getElementById('tbody');
  return { h, board: h.startsWith('#r/') || h === '', sel: h.split('/')[2] || null, wide, clipped,
    narrow: !!(t && tb && t.getBoundingClientRect().width < tb.getBoundingClientRect().width - 24),
    overflow: document.documentElement.scrollWidth > innerWidth, chart: q('#chart'), next: q('section.next'), tcard: q('#tcard'),
    insp: document.querySelector('#insp .ph-t b')?.textContent, runpage: q('.rh'), vs: q('.vs') };
}"""


def drive(browser, url: str, width: int, height: int, scheme: str, fails: list[str]) -> int:
    """Every control at one viewport; returns 1 when the lab has too few runs to drive the page."""
    page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(url)
    page.wait_for_timeout(500)
    data = page.evaluate("JSON.parse(document.getElementById('data').textContent)")
    camp = data["campaigns"][0]
    scored = [r for r in camp["runs"] if r["value"] is not None and r["parent"]]
    if len(scored) < 2:
        print(f"{camp['name']} needs two scored runs with parents to drive the page")
        return 1
    a, b = scored[-1]["id"], scored[0]["id"]
    has_next = 1 if camp["next"] else 0
    narrow = width <= 1100

    def check(step: str) -> None:
        st = page.evaluate(STATE)
        bad = list(errors)
        errors.clear()
        bad += ["page scrolls sideways"] * st["overflow"] + [f"sticks out: {st['wide']}"] * bool(st["wide"])
        bad += [f"clipped: {st['clipped']}"] * bool(st["clipped"]) + ["table narrower than its card"] * st["narrow"]
        if st["board"]:
            if st["chart"] != 1 or st["tcard"] != 1:
                bad.append(f"chart x{st['chart']}, run list x{st['tcard']}")
            if st["next"] != has_next:
                bad.append(f"Next x{st['next']}, want {has_next}")
            if st["sel"] and st["insp"] != st["sel"]:
                bad.append(f"panel shows {st['insp']}, selected {st['sel']}")
        if st["h"].startswith("#run/") and st["runpage"] != 1:
            bad.append("run page missing")
        if st["h"].startswith("#cmp/") and st["vs"] != 1:
            bad.append("compare header missing")
        print(("FAIL " if bad else "ok   ") + f"[{width}] {step} {st['h']} " + "; ".join(bad))
        if bad:
            fails.append(step)

    def click(selector: str, wait: int = 200) -> None:
        page.click(selector, force=True)
        page.wait_for_timeout(wait)

    check("load")
    for kind in ["spend", "result", "spend", "result"]:
        click(f'[data-chart="{kind}"]')
        check(f"chart {kind}")
    for order in ["tree", "exp", "newest"]:
        click(f'[data-order="{order}"]')
        check(f"order {order}")
    page.select_option("#vf", index=1)
    check("verdict filter")
    page.select_option("#vf", "all")
    page.fill("#q", b)
    check("search")
    page.fill("#q", "")
    if camp["findings"]:
        click('[data-tab="findings"]')
        check("findings tab")
        click(".flist li")
        check("finding opened")
        click('[data-tab="runs"]')
    click(f'tr.r[data-run="{b}"]', 300)
    check(f"select {b}")
    if narrow:
        click("#close", 300)
    click(f'#chart [data-run="{a}"]', 300)
    check(f"chart point {a}")
    if narrow:
        click("#close", 300)
    else:
        click(f'#insp .lr[data-run="{scored[-1]["parent"]}"]')
        check("lineage row")
        for key in "jk":
            page.keyboard.press(key)
            page.wait_for_timeout(100)
            check(f"key {key}")
    page.goto(f"{url}#r/{camp['name']}/{a}")
    page.wait_for_timeout(300)
    if narrow:
        click(f'tr.r[data-run="{a}"]', 300)
    click("#insp a.btn.pri", 400)
    check("open run")
    click('[data-sec="claim"] .sh', 250)
    check("fold claim")
    click('[data-sec="claim"] .sh', 250)
    if page.query_selector("#tailbtn"):
        click("#tailbtn")
        check("log tail")
    click("[data-other]")
    check("compare with parent")
    page.select_option("#other", b)
    page.wait_for_timeout(200)
    check(f"compare with {b}")
    click("#diffonly")
    check("all attributes")
    click(".cbar a.btn", 400)
    check("full compare")
    click("#swap", 400)
    check("swap")
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    check("esc")
    for view in ["term", "notes"]:
        page.goto(f"{url}#{view}/{camp['name']}/{a}" if view == "term" else f"{url}#notes")
        page.wait_for_timeout(300)
        check(view)
    if len(data["campaigns"]) > 1:
        page.goto(f"{url}#r/{camp['name']}/{a}")
        page.wait_for_timeout(300)
        page.select_option("#camp", "1")
        page.wait_for_timeout(500)
        check("second campaign")
        click('[data-chart="spend"]')
        check("second campaign spend")
    click("#theme")
    click("#theme")
    check("theme")
    page.close()
    return 0


def main(lab: Path) -> int:
    out = Path(tempfile.mkdtemp())
    subprocess.run(
        [sys.executable, "-m", "lab.cli", "board", "--out", str(out)], cwd=lab, check=True, capture_output=True
    )
    url = (out / "index.html").as_uri()
    fails = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height, scheme in [(1440, 900, "dark"), (1024, 768, "light"), (390, 844, "light")]:
            if drive(browser, url, width, height, scheme, fails):
                return 1
        browser.close()
    print(f"\n{len(fails)} failing steps")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).expanduser().resolve()))
