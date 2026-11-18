"""M, Kaggle step: the AI clips of a Masala Short (Manzi Engine on Kaggle).

python masala/job.py --story <slug> [--build-only]

- Results already published (Release "engine-masala-<slug>-<hash>-..."): downloads them to out/masala/<slug>/engine/
  and prints ai=ready.
- Otherwise builds the job (one upright 8 s clip per scene, the Hindi line spoken inside the clip), sends it to
  "3 - Manzi Engine" in the 11 am-3 pm IST slot or leaves it waiting for "3c", and prints ai=sent or ai=waiting.
  When Kaggle is done, "3b - Collect" publishes the results and starts "M - Make masala short" again by itself.
Writes "ai=<ready|sent|waiting>" to $GITHUB_OUTPUT when run in GitHub Actions.
"""
import argparse, datetime, hashlib, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
sys.path.insert(0, HERE)
from common import ROOT, log  # noqa: E402
from story import SETTINGS, load, story_hash  # noqa: E402

LOOK = ("Photorealistic live-action Indian television drama, shot on a cinema camera, natural skin texture and pores, "
        "real human actors, warm practical lighting, shallow depth of field")


def run_id(st):
    return f"masala-{st['slug']}-{story_hash(st)}"


def release_for(st):
    from engine_week import gh
    rels = json.loads(gh("releases?per_page=100"))
    rels = [r for r in rels if r["tag_name"].startswith(f"engine-{run_id(st)}-")]
    return sorted(rels, key=lambda r: r["created_at"])[-1] if rels else None


def seed_for(slug, sid):
    return int(hashlib.sha1(f"masala/{slug}/{sid}".encode()).hexdigest()[:8], 16) % 900_000_000 + 10_000


def person(c, outfit):
    g = c.get("gender", "")
    who = f"{c['name']}, a {c['age']}-year-old Indian {g}".replace("  ", " ").strip()
    return f"{who}: {c['face'].strip().rstrip('.')}; wearing {outfit.strip().rstrip('.')}"


def scene_prompt(st, s):
    chars = {c["id"]: c for c in st["characters"]}
    wear = {str(k): v for k, v in st["wardrobe"].items()}[str(s["day"])]
    people = [chars[c] for c in s["cast"]]
    parts = [s["action"].strip().rstrip(".") + ".", f"Setting: {s['place'].strip().rstrip('.')}."]
    if people:
        parts.append(("The people in the shot, each one clearly different: " if len(people) > 1 else "In the shot: ")
                     + "; ".join(person(p, wear[p["id"]]) for p in people) + ".")
    if (s.get("line") or "").strip():
        sp = chars[s["speaker"]]
        parts.append(f"Only {sp['name']} speaks, in Hindi, clearly, with natural, well-synchronised lip movements and "
                     f"no long pauses; {sp['name']} finishes speaking a moment before the shot ends; "
                     "everyone else stays silent.")
    else:
        parts.append("Nobody speaks.")
    parts.append("Everyone is clearly Indian, with brown skin and Indian features, like real actors in an Indian TV "
                 "serial; never cartoon, anime or plastic-looking.")
    parts.append(f"Film look: {(st.get('look') or LOOK).strip().rstrip('.')}. Vertical 9:16 frame for a phone screen, "
                 "faces framed in the upper-middle of the picture. No text, no captions, no logos, no watermarks, "
                 "no signboards, no shop signs, no posters, no name plates, no readable letters anywhere.")
    return " ".join(parts)


def sound_for(st, s):
    base = (s.get("sound") or "Natural room tone that matches the place").strip().rstrip(".")
    if (s.get("line") or "").strip():
        sp = next(c for c in st["characters"] if c["id"] == s["speaker"])
        return f"{base}, and {sp['name']}'s voice: {sp['voice'].strip().rstrip('.')}, speaking Hindi."
    return f"{base}, no voices."


def build_job(st):
    scenes, ids = [], [s["id"] for s in st["scenes"]]
    feeds = {ids[i - 1] for i, s in enumerate(st["scenes"]) if i and s.get("continue")}
    for i, s in enumerate(st["scenes"]):
        talk = bool((s.get("line") or "").strip())
        sc = {"id": s["id"], "kind": "scene", "seed": seed_for(st["slug"], s["id"]), "scene": scene_prompt(st, s),
              "dialogue": s.get("line", "").strip(), "language": SETTINGS["language"],
              "sound": sound_for(st, s), "aspect": SETTINGS["aspect"], "duration": f"{SETTINGS['clip_seconds']} s",
              "preview": SETTINGS["preview"], "preview_fallback": SETTINGS["preview_fallback"],
              "output": SETTINGS["output"], "preset": SETTINGS["preset"]}
        if talk:
            sc.update(min_end_silence=0.4, retries=1)
        if s.get("continue") and i:
            sc["start_image"] = ids[i - 1]
        if s["id"] in feeds:
            sc.update(save_frame=True, frame_time="end")
        scenes.append(sc)
    return {"run_id": run_id(st), "purpose": f"Masala Short: {st['title']}", "scenes": scenes,
            "scene_time_limit_min": min(330, 14 * len(scenes) + 15)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--story", required=True)
    ap.add_argument("--build-only", action="store_true", help="write the job file and stop (for checking)")
    a = ap.parse_args()
    out = os.environ.get("GITHUB_OUTPUT")

    def say(state):
        log(f"AI part: {state}")
        if out:
            open(out, "a").write(f"ai={state}\n")

    st = load(a.story)
    job = build_job(st)
    name = f"{job['run_id']}.json"
    path = os.path.join(ROOT, "engine", "jobs", name)
    if a.build_only:
        json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return log(f"job written: {len(job['scenes'])} clips -> {os.path.relpath(path, ROOT)}")
    rel = release_for(st)
    if rel:
        from engine_week import download
        download(rel, os.path.join(ROOT, "out", "masala", a.story, "engine"))
        return say("ready")
    pending = os.path.join(ROOT, "engine", "state", "pending.json")
    if os.path.exists(pending) and json.load(open(pending)).get("run_id") == job["run_id"]:
        log("this Short is already on Kaggle: '3b - Collect' will start 'M - Make masala short' again when it is done")
        return say("sent")
    waiting = os.path.join(ROOT, "engine", "state", f"waiting-{job['run_id']}.json")
    if os.path.exists(waiting):
        log("this Short is already waiting for the 11 am slot")
        return say("waiting")
    json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"job: {len(job['scenes'])} clips")
    now = datetime.datetime.now(datetime.timezone.utc)
    in_slot = datetime.time(5, 30) <= now.time() <= datetime.time(9, 30)     # 11:00 am - 3:00 pm India time
    if st.get("send_now"):  # "send_now": true in the story file: don't wait for the slot (the queue may be long)
        log("send_now: sending straight away, outside the 11 am-3 pm slot")
        in_slot = True
    if not in_slot:
        os.makedirs(os.path.dirname(waiting), exist_ok=True)
        json.dump({"job": name, "week": f"masala:{a.story}", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                  open(waiting, "w"), indent=2)
    subprocess.run(["git", "add", "-A", path, os.path.dirname(waiting)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Manzi Engine job: masala short {a.story}"], cwd=ROOT, check=False)
    subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"], cwd=ROOT, check=False)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    if in_slot:
        subprocess.run(["gh", "workflow", "run", "engine.yml", "-f", f"job={name}", "-f", "wait_minutes=170",
                        "-f", f"then_make=masala:{a.story}"], cwd=ROOT, check=True)
        return say("sent")
    say("waiting")


if __name__ == "__main__":
    main()
