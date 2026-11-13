import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "render"))
from specs import all_specs, estimate_timing, add_pops
from render import render
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "videos"); os.makedirs(OUT, exist_ok=True)
pack = json.load(open(os.path.join(HERE, sys.argv[1]), encoding="utf-8")); only = sys.argv[2:] 
names = {"long": "judicial-review-discretionary-powers-administrative-law-llb", "datadrop": "judicial-review-asked-4-times-llb-shorts",
         "myth": "arrest-without-warrant-myth-bnss-shorts", "quiz": "basic-structure-doctrine-quiz-llb-shorts", "case": "dk-basu-arrest-guidelines-case-shorts",
         "compare": "murder-ipc-vs-bns-sections-shorts", "flow": "criminal-case-fir-to-judgment-shorts"}
for s in all_specs(pack):
    if only and s["name"] not in only: continue
    estimate_timing(s); add_pops(s); n = names.get(s["name"], s["name"])
    t0 = time.time(); render(s, f"{OUT}/{n}.mp4", thumb=f"{OUT}/{n}-thumbnail.png", fps=30, log=lambda *a: None)
    print(f"{s['name']}: {s['duration']}s video in {time.time()-t0:.0f}s")
