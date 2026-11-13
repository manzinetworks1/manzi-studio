import json, os, sys, base64
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from specs import all_specs, estimate_timing, add_pops
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(HERE, "..", "render"); OUT = os.path.join(HERE, "stills"); os.makedirs(OUT, exist_ok=True)
pack = json.load(open(os.path.join(HERE, sys.argv[1] if len(sys.argv) > 1 else "pack_admin_q2.json"), encoding="utf-8"))
specs = [add_pops(estimate_timing(s)) for s in all_specs(pack)]
json.dump(specs, open(os.path.join(HERE, "specs.json"), "w"), ensure_ascii=False, indent=1)
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--allow-file-access-from-files"]); pg = b.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file://" + os.path.abspath(os.path.join(R, "page.html")))
    for s in specs:
        pg.evaluate("s => R.setup(s)", s)
        # one still near the end of each beat (+ start of a few)
        for i, bt in enumerate(s["beats"]):
            t = bt["t1"] - 0.05
            pg.evaluate("t => R.frame(t)", t)
            open(f"{OUT}/{s['name']}_{i:02d}_{bt['k']}.jpg", "wb").write(base64.b64decode(pg.evaluate("() => R.jpeg(0.85)")))
        for x in s.get("pops", [])[:1]:
            pg.evaluate("t => R.frame(t)", x + 1.5); open(f"{OUT}/{s['name']}_pop.jpg", "wb").write(base64.b64decode(pg.evaluate("() => R.jpeg(0.85)")))
        pg.evaluate("() => R.thumb()"); open(f"{OUT}/{s['name']}_thumb.png", "wb").write(base64.b64decode(pg.evaluate("() => R.png()")))
        print(s["name"], s["duration"], "s", len(s["beats"]), "beats", "pops", s.get("pops"))
    b.close()
print("errors:", errs or "none")
