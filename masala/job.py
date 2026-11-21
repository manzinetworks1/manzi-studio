"""M, Kaggle step: the AI clips of a Masala Short (Manzi Engine on Kaggle).

python masala/job.py --story <slug> --mode draft|final [--build-only]

Each scene's clip is named <scene>-<key> (e.g. s02-3fa91c): the key changes when anything that shapes the clip
changes (its prompt, line, sound, seed, size, or the scene it continues from). Clips already made in any earlier run
of this story (its "engine-masala-<slug>-..." Releases) are re-used, so only new or changed scenes use the GPU.

- draft: every scene at 544p, no 720p sharpening, no second takes (about 11 min a clip). The latents are kept.
- final: every scene sharpened to 720p. An approved draft is sharpened itself (about 9 min a clip, the same clip you
  approved); a scene with no draft is made from scratch.

When everything needed already exists, downloads it to out/masala/<slug>/engine/ and prints ai=ready. Otherwise
sends the missing scenes to "3 - Manzi Engine" (in the 11 am-3 pm IST slot, or straight away with "send_now") and
prints ai=sent or ai=waiting; "3b - Collect" starts "M - Make masala short" again when Kaggle is done.
Writes "ai=<ready|sent|waiting>" to $GITHUB_OUTPUT when run in GitHub Actions.
"""
import argparse, datetime, hashlib, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
sys.path.insert(0, HERE)
from common import ROOT, log  # noqa: E402
from story import SETTINGS, SHOTS, check, is_animal, load  # noqa: E402

LOOK = ("Photorealistic live-action Indian television drama, shot on a cinema camera, natural skin texture and pores, "
        "real human actors, warm practical lighting, shallow depth of field")
SPOT = {"left": "On the LEFT of the frame", "right": "On the RIGHT of the frame", "centre": "In the CENTRE of the frame",
        "foreground-left": "In the FOREGROUND on the left", "foreground-right": "In the FOREGROUND on the right",
        "background": "In the BACKGROUND", "background-left": "In the BACKGROUND on the left",
        "background-right": "In the BACKGROUND on the right"}
TURN = {"left": "body and face turned towards the left of the frame",
        "right": "body and face turned towards the right of the frame",
        "camera-left": "turned three-quarters towards the camera, angled to the left of the frame",
        "camera-right": "turned three-quarters towards the camera, angled to the right of the frame",
        "camera": "facing the camera", "away": "back to the camera"}


def seed_for(slug, sid):
    return int(hashlib.sha1(f"masala/{slug}/{sid}".encode()).hexdigest()[:8], 16) % 900_000_000 + 10_000


def who(c, outfit=None, face=None):
    g = c.get("gender", "")
    d = f"{c['name']} (a {c['age']}-year-old Indian {g}: {(face or c['face']).strip().rstrip('.')}"
    return d + (f"; wearing {outfit.strip().rstrip('.')})" if outfit else ")")


def scene_prompt(st, s):
    """The whole scene as plain, ordered sentences: frame, then every person with place, direction, eyes and action,
    then who speaks, then a head count, then the look. Nothing is left for the AI to guess."""
    chars = {c["id"]: c for c in st["characters"]}
    wear = {**{str(k): v for k, v in st["wardrobe"].items()}.get(str(s["day"]), {}), **(s.get("wear") or {})}
    stg = s["stage"]
    people = stg.get("people") or {}
    name = lambda x: chars[x]["name"] if x in chars else x
    parts = [SHOTS[stg["shot"]][1] + ".", f"Setting: {s['place'].strip().rstrip('.')}."]
    sh = stg.get("shoulder")
    if sh:
        side = "right" if any("left" in p.get("where", "") for p in people.values()) else "left"
        parts.append(f"In the near foreground at the {side} edge of the frame, out of focus: only the shoulder and the "
                     f"back of the head of {chars[sh]['name']} (wearing {wear[sh].strip().rstrip('.')}); "
                     f"{chars[sh]['name']}'s face is NOT visible.")
    for pid, p in people.items():
        eyes = p["eyes"]
        line = (f"{SPOT.get(p['where'], p['where'])}: {who(chars[pid], wear[pid], p.get("face"))}, {TURN.get(p['faces'], p['faces'])}, "
                f"eyes on {name(eyes)} the whole time")
        if eyes in chars and eyes not in people and eyes != sh:
            line += " (who is off-screen)"
        line += f"; {p['does'].strip().rstrip('.')}"
        if p.get("expression"):
            line += f", {p['expression'].strip().rstrip('.')}"
        if p.get("sound"):
            line += f"; {chars[pid]['name']} {p['sound'].strip().rstrip('.')}"
        parts.append(line + ".")
    parts.append(f"What happens: {s['action'].strip().rstrip('.')}.")
    if (s.get("line") or "").strip():
        sp = chars[s["speaker"]]
        others = [x for x in people if x != s["speaker"]]
        txt = (f"Only {sp['name']} speaks, in Hindi, clearly, looking at {name(people[s['speaker']]['eyes'])} while "
               f"speaking, with natural, well-synchronised lip movements; {sp['name']} finishes speaking a moment before "
               "the shot ends.")
        quiet = [x for x in others if not people[x].get("sound")]
        if quiet:
            txt += (f" {' and '.join(name(x) for x in quiet)} {'stays' if len(quiet) == 1 else 'stay'} silent, "
                    + ("only reacting." if all(is_animal(chars[x]) for x in quiet) else "lips closed, only reacting."))
        for x in others:
            if people[x].get("sound"):
                txt += (f" {name(x)} {people[x]['sound'].strip().rstrip('.')}, and is quiet while "
                        f"{sp['name']} speaks.")
        parts.append(txt)
    elif s.get("narrator"):
        nv = s["narrator"]["voice"].strip().rstrip(".")
        parts.append(f"Nobody on screen speaks: the only voice is an unseen narrator ({nv}) speaking a voice-over "
                     "in Hindi, straight to the viewer. Every mouth on screen stays closed; nobody's lips move."
                     + "".join(f" {name(x)} {people[x]['sound'].strip().rstrip('.')}." for x in people
                               if people[x].get("sound")))
    else:
        noisy = [x for x in people if people[x].get("sound")]
        parts.append("Nobody speaks." + "".join(f" {name(x)} {people[x]['sound'].strip().rstrip('.')}." for x in noisy))
    if people:
        humans = [x for x in people if not is_animal(chars[x])]
        animals = [x for x in people if is_animal(chars[x])]
        if animals:  # say humans and animals apart: "a two-shot" with a dog made H3 add a second man
            cnt = lambda n, one, many: f"{'ONE' if n == 1 else n} {one if n == 1 else many}"
            txt = (f"Who is in this shot: {cnt(len(humans), 'human', 'humans') if humans else 'no humans'}"
                   + (f" ({', '.join(name(x) for x in humans)})" if humans else "")
                   + f" and {cnt(len(animals), 'animal', 'animals')} ({', '.join(name(x) for x in animals)})"
                   + (f", plus the shoulder of {name(sh)}" if sh else "")
                   + f". There is only {'one' if len(humans) == 1 else len(humans) or 'no'} human and only "
                     f"{'one' if len(animals) == 1 else len(animals)} animal in this shot; nobody appears twice; "
                     "no other people and no other animals anywhere, not even in the background.")
            parts.append(txt.replace("only no human", "no human"))
        else:
            seen = [name(x) for x in people] + ([f"the shoulder of {name(sh)}"] if sh else [])
            parts.append(f"Exactly {len(people)} {'figure' if len(people) == 1 else 'figures'} fully in the frame "
                         f"({', '.join(seen)}); each appears only once; nobody else.")
    if not any(p.get("to_camera") for p in people.values()):
        parts.append("Nobody looks into the camera lens: the camera is an invisible observer that nobody notices.")
    if not people or any(not is_animal(chars[x]) for x in people) or sh:
        parts.append("Everyone is clearly Indian, with brown skin and Indian features, like real actors in an Indian TV "
                     "serial; never cartoon, anime or plastic-looking.")
    else:
        parts.append("A real, photographed animal; never cartoon, anime or plastic-looking.")
    parts.append(f"Film look: {(st.get('look') or LOOK).strip().rstrip('.')}. Upright, normal orientation (never rotated "
                 "or upside down). Vertical 9:16 frame for a phone screen, "
                 "faces in the upper-middle of the picture. No text, no captions, no logos, no watermarks, no signboards, "
                 "no shop signs, no posters, no name plates, no vehicle number plates, no readable letters anywhere.")
    return " ".join(parts)


def sound_for(st, s):
    base = (s.get("sound") or "Natural room tone that matches the place").strip().rstrip(".")
    chars = {c["id"]: c for c in st["characters"]}
    for pid, p in (s["stage"].get("people") or {}).items():
        if p.get("sound"):
            base += f", {chars[pid]['name']} {p['sound'].strip().rstrip('.')}"
    if (s.get("line") or "").strip():
        sp = next(c for c in st["characters"] if c["id"] == s["speaker"])
        return f"{base}, and {sp['name']}'s voice: {sp['voice'].strip().rstrip('.')}, speaking Hindi."
    if s.get("narrator"):
        return (f"{base}, and an off-screen narrator's voice-over: {s['narrator']['voice'].strip().rstrip('.')}, "
                "speaking Hindi warmly and playfully, close to the microphone.")
    return f"{base}, no voices."


def plan(st):
    """[(scene, clip id, engine fields, clip id it continues from)] in story order."""
    out, prev = [], None
    for s in st["scenes"]:
        take = int(s.get("take", 1))  # "take": 2 -> a new seed for a remake that came out wrong
        f = {"seed": seed_for(st["slug"], s["id"] if take == 1 else f"{s['id']}#{take}"), "scene": scene_prompt(st, s),
             "dialogue": ((s.get("narrator") or {}).get("line") or s.get("line") or "").strip(),
             "language": SETTINGS["language"], "sound": sound_for(st, s), "aspect": SETTINGS["aspect"],
             "duration": f"{s.get('seconds', SETTINGS['clip_seconds'])} s", "preview": SETTINGS["preview"]}
        cont = prev if (s.get("continue") and prev) else None
        key = hashlib.sha1(json.dumps([f, cont], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:6]
        cid = s.get("clip") or f"{s['id']}-{key}"  # "clip": an approved clip, kept even if the prompt rules change
        out.append((s, cid, f, cont))
        prev = cid
    return out


def assets(slug):
    """{asset name: release tag} over every engine run of this story (newest wins)."""
    from engine_week import gh
    rels = [r for r in json.loads(gh("releases?per_page=100")) if r["tag_name"].startswith(f"engine-masala-{slug}-")]
    found = {}
    for r in sorted(rels, key=lambda r: r["created_at"]):
        for a in r.get("assets", []):
            found[a["name"]] = r["tag_name"]
    return found


def build_job(st, mode, have):
    """(job or None when nothing is missing, [(clip id, release, file)] to download for the Short)."""
    p = plan(st)
    want = "720p" if mode == "final" else SETTINGS["preview"]
    needed, scenes, inputs, frames = [], [], [], {}
    todo = {cid for _, cid, _, _ in p if f"{cid}_{want}.mp4" not in have}
    for s, cid, f, cont in p:
        clip = f"{cid}_{want}.mp4"
        if clip in have:
            needed.append((cid, have[clip], clip))
            continue
        sc = {"id": cid, "kind": "scene", **f, "preview_fallback": SETTINGS["preview_fallback"]}
        if mode == "final":
            sc.update(output=SETTINGS["output"], preset=SETTINGS["preset"])
            draft = f"{cid}_{SETTINGS['preview']}"
            if f"{draft}.pt" in have:
                sc["upscale_from"] = draft
                inputs.append({"release": have[f"{draft}.pt"], "file": f"{draft}.pt"})
                if f"{draft}.json" in have:
                    inputs.append({"release": have[f"{draft}.json"], "file": f"{draft}.json"})
                if f"{draft}.mp4" in have:                  # its sound (the sharpened clip keeps it)
                    inputs.append({"release": have[f"{draft}.mp4"], "file": f"{draft}.mp4"})
        else:
            sc["keep_latents"] = True
        if cont and not sc.get("upscale_from"):
            sc["start_image"] = cont
            if cont not in todo and f"{cont}_frame.png" in have:  # the scene before was made in an earlier run
                frames[cont] = f"{cont}_frame.png"
                inputs.append({"release": have[f"{cont}_frame.png"], "file": f"{cont}_frame.png"})
        scenes.append(sc)
    feeds = {cont for _, _, _, cont in p if cont}  # scenes that a later scene continues from keep their last picture
    for sc in scenes:
        if sc["id"] in feeds and "upscale_from" not in sc:
            sc.update(save_frame=True, frame_time="end")
    if not scenes:
        return None, needed
    limit = sum(13 if mode == "draft" else (11 if "upscale_from" in sc else 22) for sc in scenes) + 15
    key = hashlib.sha1(json.dumps([sc["id"] for sc in scenes]).encode()).hexdigest()[:6]
    return ({"run_id": f"masala-{st['slug']}-{mode}-{key}", "purpose": f"Masala Short ({mode}): {st['title']}",
             "scenes": scenes, "inputs": inputs, "frames": frames, "scene_time_limit_min": min(330, limit)}, needed)


def download(needed, dest):
    from engine_week import gh
    os.makedirs(dest, exist_ok=True)
    by_rel = {}
    for _, rel, n in needed:
        by_rel.setdefault(rel, []).append(n)
    repo = os.environ.get("GITHUB_REPOSITORY", "manzinetworks1/manzi-studio")
    for rel, names in by_rel.items():
        ids = {a["name"]: a["id"] for a in json.loads(gh(f"releases/tags/{rel}"))["assets"]}
        for n in names:
            data = subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                                   f"repos/{repo}/releases/assets/{ids[n]}"], capture_output=True, check=True).stdout
            open(os.path.join(dest, n), "wb").write(data)
    log(f"downloaded {len(needed)} clip(s)")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--story", required=True)
    ap.add_argument("--mode", choices=["draft", "final", "final-544p"], default="draft",
                    help="final-544p: the Short from the approved 544p draft clips, no GPU")
    ap.add_argument("--build-only", action="store_true", help="write the job file and stop (for checking)")
    a = ap.parse_args()
    out = os.environ.get("GITHUB_OUTPUT")

    def say(state):
        log(f"AI part: {state}")
        if out:
            open(out, "a").write(f"ai={state}\n")

    st = load(a.story)
    errs, _ = check(st)
    if errs:
        raise SystemExit("The story has problems:\n" + "\n".join(errs))
    have = {} if a.build_only else assets(a.story)
    job, needed = build_job(st, a.mode, have)
    if a.build_only:
        path = os.path.join(ROOT, "engine", "jobs", f"{job['run_id']}.json")
        json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return log(f"job written: {len(job['scenes'])} clips -> {os.path.relpath(path, ROOT)}")
    if job is None:
        dest = os.path.join(ROOT, "out", "masala", a.story, "engine")
        download(needed, dest)
        json.dump({"mode": a.mode, "clips": [c for c, _, _ in needed]}, open(os.path.join(dest, "clips.json"), "w"))
        return say("ready")
    log(f"{a.mode}: {len(job['scenes'])} clip(s) to make, {len(needed)} re-used")
    name = f"{job['run_id']}.json"
    path = os.path.join(ROOT, "engine", "jobs", name)
    pending = os.path.join(ROOT, "engine", "state", "pending.json")
    if os.path.exists(pending) and json.load(open(pending)).get("run_id") == job["run_id"]:
        log("this run is already on Kaggle: '3b - Collect' will start 'M - Make masala short' again when it is done")
        return say("sent")
    waiting = os.path.join(ROOT, "engine", "state", f"waiting-{job['run_id']}.json")
    if os.path.exists(waiting):
        log("this run is already waiting for the 11 am slot")
        return say("waiting")
    json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    then = f"masala:{a.story}:{a.mode}"
    now = datetime.datetime.now(datetime.timezone.utc)
    in_slot = datetime.time(5, 30) <= now.time() <= datetime.time(9, 30)     # 11:00 am - 3:00 pm India time
    if st.get("send_now"):  # "send_now": true in the story file: don't wait for the slot (the queue may be long)
        log("send_now: sending straight away, outside the 11 am-3 pm slot")
        in_slot = True
    if not in_slot:
        os.makedirs(os.path.dirname(waiting), exist_ok=True)
        json.dump({"job": name, "week": then, "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                  open(waiting, "w"), indent=2)
    subprocess.run(["git", "add", "-A", path, os.path.dirname(waiting)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Manzi Engine job: masala short {a.story} ({a.mode})"], cwd=ROOT, check=False)
    subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"], cwd=ROOT, check=False)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    if in_slot:
        subprocess.run(["gh", "workflow", "run", "engine.yml", "-f", f"job={name}", "-f", "wait_minutes=0",
                        "-f", f"then_make={then}"], cwd=ROOT, check=True)
        return say("sent")
    say("waiting")


if __name__ == "__main__":
    main()
