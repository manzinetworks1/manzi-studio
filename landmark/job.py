"""L2, first step: the AI part of a landmark case video (Manzi Engine on Kaggle).

python landmark/job.py --case <slug> [--no-ai]

- Engine results already published (Release "engine-landmark-<slug>-..."): downloads them to
  out/landmark/<slug>/engine/ and prints ai=ready.
- Otherwise builds the job (every story scene, the Professor's start/end clips, every narration sentence in his
  cloned voice), sends it to "3 - Manzi Engine" in the 11 am-3 pm IST slot or leaves it waiting for "3c", and prints
  ai=sent or ai=waiting. When Kaggle is done, "3b - Collect" publishes the results and starts L2 again by itself.
Writes "ai=<off|ready|sent|waiting>" to $GITHUB_OUTPUT when run in GitHub Actions.

Two rounds, to save GPU (Manzi's choice, 21 Nov 2026):
- draft (no landmark/cases/<slug>/approved.json yet): every scene only as its preview (384p, 544p when someone speaks),
  latents kept; plus the narration. The video is made from these so the scenes can be reviewed.
- final (approved.json exists): {"approved": ["s01", ...] or "all", "remake": {"s05": "what to change"}}. Approved
  scenes are sharpened to 720p from their own draft (the same clip); scenes in "remake" are made again (new seed) at
  720p. The draft's narration is re-used.
landmark/cases/<slug>/reuse.json (optional): {"release": "<engine release tag>", "clips": {"<beat id>": "<clip name in
that release>"}}: clips already made and approved elsewhere (e.g. a test run); they are not made again.
"""
import argparse, datetime, hashlib, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
from common import ROOT, log  # noqa: E402
from voice import speakable  # noqa: E402
from engine_week import gh, download  # noqa: E402  (GitHub helpers of the weekly flow)

CAST = os.path.join(ROOT, "engine", "cast", "professor.json")


def load_story(sl):
    path = os.path.join(HERE, "cases", sl, "story.json")
    if not os.path.exists(path):
        raise SystemExit(f"No storyboard at landmark/cases/{sl}/story.json: run 'L1 - Write landmark storyboard' first.")
    try:
        return json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        raise SystemExit(f"landmark/cases/{sl}/story.json has a typing mistake after your edit: {e}. Fix that line on GitHub and run again.")


def release_for(sl, final=False):
    rels = json.loads(gh("releases?per_page=100"))
    rels = [r for r in rels if r["tag_name"].startswith(f"engine-landmark-{sl}-")
            and r["tag_name"].startswith(f"engine-landmark-{sl}-final-") == final]
    return sorted(rels, key=lambda r: r["created_at"])[-1] if rels else None


def release_by_tag(tag):
    return json.loads(gh(f"releases/tags/{tag}"))


def case_file(sl, name):
    p = os.path.join(HERE, "cases", sl, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def fetch_reuse(reuse, dest):
    """Copies re-used clips into the engine folder under this case's beat ids (720p if there, else the preview)."""
    if not reuse:
        return
    rel = release_by_tag(reuse["release"])
    ids = {a["name"]: a["id"] for a in rel["assets"]}
    os.makedirs(dest, exist_ok=True)
    for beat, src in reuse.get("clips", {}).items():
        for size in ("720p", "544p", "384p"):
            if f"{src}_{size}.mp4" in ids:
                open(os.path.join(dest, f"{beat}_{size}.mp4"), "wb").write(
                    gh(f"releases/assets/{ids[f'{src}_{size}.mp4']}", "application/octet-stream"))
                break
    log(f"re-used clips: {', '.join(reuse.get('clips', {}))}")


def seed_for(sl, sid):
    return int(hashlib.sha1(f"{sl}/{sid}".encode()).hexdigest()[:8], 16) % 900_000_000 + 10_000


def scene_prompt(st, b):
    cast = {c["id"]: c for c in st["cast"]}
    people = [cast[c] for c in b.get("cast", []) if c in cast]
    parts = [b["scene"].strip().rstrip(".") + "."]
    if people:
        parts.append(("The people in the shot, each one different: " if len(people) > 1 else "In the shot: ") +
                     "; ".join(f"{p['label']}: {p['look'].strip().rstrip('.')}" for p in people) + ".")
    if b.get("dialogue"):
        who = cast.get(b.get("speaker"), {}).get("label", "the speaker")
        parts.append(f"Only {who} speaks, clearly, with crisp, well-articulated mouth movements and no long pauses; "
                     f"everyone else stays silent.")
    else:
        parts.append("Nobody speaks.")
    parts.append("Everyone is clearly Indian, with brown skin.")
    parts.append(f"Film look: {st['look'].strip().rstrip('.')}. Realistic and cinematic. "
                 "No text, no captions, no logos, no watermarks, no signboards, no shop signs, no posters, "
                 "no banners, no name plates, no readable letters anywhere in the picture.")
    return " ".join(parts)


def build_job(st, lcfg, mode="draft", reuse=None, draft_have=None, approved=None):
    sl = st["slug"]
    prof = json.load(open(CAST, encoding="utf-8"))
    beats = st["beats"]
    scene_ids = [b["id"] for b in beats if b["type"] == "scene"]
    next_continues = {scene_ids[i - 1] for i, sid in enumerate(scene_ids)
                      if i and next(b for b in beats if b["id"] == sid).get("cont")}
    reuse = reuse or {"clips": {}}
    rclips = reuse.get("clips", {})
    draft_have = draft_have or {}                 # {asset name: release tag} of the draft run
    approved = approved or {}
    ok_ids = approved.get("approved", [])
    remake = approved.get("remake", {}) or {}
    scenes, pieces, prev, inputs, frames = [], [], None, [], {}
    for b in beats:
        if b["id"] in rclips:
            prev = b["id"] if b["type"] == "scene" else prev
        elif b["type"] == "professor" and mode == "final" and (ok_ids == "all" or b["id"] in ok_ids) \
                and f"{b['id']}_720p.mp4" in draft_have:
            pass
        elif b["type"] == "professor":
            scenes.append({"id": b["id"], "kind": "professor", "seed": prof["seed"], "scene": prof["scene"],
                           "dialogue": b["line"], "sound": prof["sound"],
                           # 384p like the approved takes: the same seed at another size would give another face
                           "preview": "384p", "duration": "5 s", "output": "720p", "preset": "Fast"})
        elif b["type"] == "scene":
            sc = {"id": b["id"], "kind": "scene", "seed": seed_for(sl, b["id"]), "scene": scene_prompt(st, b),
                  "dialogue": b.get("dialogue", ""), "language": "English", "duration": "5 s",
                  "sound": (b.get("sound") or "Quiet room tone").strip().rstrip(".") +
                           (", the speaker's clear Indian-accented voice." if b.get("dialogue") else ", no voices."),
                  "output": lcfg.get("scene_output", "720p"), "preset": lcfg.get("scene_preset", "Fast")}
            if b.get("dialogue"):  # house rules from the lip-sync tests
                sc.update(preview="544p", min_end_silence=0.4, retries=1)
            else:
                sc["preview"] = "384p"
            if b.get("cont") and prev:
                sc["start_image"] = prev       # continues from the previous scene's last picture
                if prev in rclips:             # ... which was made in another run
                    f = f"{rclips[prev]}_frame.png"
                    frames[prev] = f; inputs.append({"release": reuse["release"], "file": f})
            if b["id"] in next_continues:
                sc.update(save_frame=True, frame_time="end")
            if mode == "draft":
                sc.pop("output", None); sc.pop("preset", None); sc["keep_latents"] = True
            else:
                draft = f"{b['id']}_{sc['preview']}"
                if b["id"] not in remake and (ok_ids == "all" or b["id"] in ok_ids) and f"{draft}.pt" in draft_have:
                    sc = {"id": b["id"], "kind": "scene", "upscale_from": draft, "output": sc["output"],
                          "preset": sc["preset"], "preview": sc["preview"]}
                    inputs.append({"release": draft_have[f"{draft}.pt"], "file": f"{draft}.pt"})
                    if f"{draft}.json" in draft_have:
                        inputs.append({"release": draft_have[f"{draft}.json"], "file": f"{draft}.json"})
                    if f"{draft}.mp4" in draft_have:                  # its sound (the sharpened clip keeps it)
                        inputs.append({"release": draft_have[f"{draft}.mp4"], "file": f"{draft}.mp4"})
                else:
                    sc["seed"] += 97                # a remake: another take
                    if remake.get(b["id"]):
                        sc["scene"] += " " + remake[b["id"]].strip()
                    if sc.get("start_image") and sc["start_image"] not in rclips:
                        f = f"{sc['start_image']}_frame.png"
                        if f in draft_have:
                            frames[sc["start_image"]] = f; inputs.append({"release": draft_have[f], "file": f})
                        else:
                            sc.pop("start_image")
            scenes.append(sc)
            prev = b["id"]
        for s in (b.get("narration", []) if mode == "draft" else []):
            t = speakable(s)
            if t and t not in pieces:
                pieces.append(t)
    per = (lambda sc: 6 if sc.get("preview") == "384p" else 10) if mode == "draft" else \
          (lambda sc: 8 if sc.get("upscale_from") else 15)
    job = {"run_id": f"landmark-{sl}" + ("-final" if mode == "final" else ""),
           "purpose": f"Landmark case video ({mode}): {st['case']}", "scenes": scenes,
           "inputs": inputs, "frames": frames,
           "scene_time_limit_min": min(330, sum(per(sc) for sc in scenes) + 15)}
    if pieces:
        job["narration"] = {"ref_audio_file": "engine/cast/professor_voiceA.wav", "ref_audio": "professor_voiceA.wav",
                            "ref_text": prof["dialogue"], "speed": 1.0, "engines": ["qwen3"], "pieces": pieces}
    return job


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--case", required=True); ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--build-only", action="store_true", help="write the job file and stop (for checking)")
    a = ap.parse_args()
    lcfg = json.load(open(os.path.join(HERE, "settings.json"), encoding="utf-8"))
    out = os.environ.get("GITHUB_OUTPUT")

    def say(state):
        log(f"AI part: {state}")
        if out:
            open(out, "a").write(f"ai={state}\n")

    st = load_story(a.case)
    if a.no_ai:
        return say("off")
    approved, reuse = case_file(a.case, "approved.json"), case_file(a.case, "reuse.json")
    mode = "final" if approved else "draft"
    dest = os.path.join(ROOT, "out", "landmark", a.case, "engine")
    draft_rel = release_for(a.case)
    draft_have = {x["name"]: draft_rel["tag_name"] for x in draft_rel["assets"]} if draft_rel else {}
    if mode == "final" and not draft_rel:
        raise SystemExit("approved.json is there but no draft run was found: remove approved.json to make the draft first")
    job = build_job(st, lcfg, mode, reuse, draft_have, approved)
    log(f"mode: {mode}")
    name = f"landmark-{a.case}{'-final' if mode == 'final' else ''}.json"
    path = os.path.join(ROOT, "engine", "jobs", name)
    if a.build_only:
        json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return log(f"job written: {len(job['scenes'])} clips, {len(job.get('narration', {}).get('pieces', []))} sentences")
    rel = release_for(a.case, final=True) if mode == "final" else draft_rel
    if rel or (mode == "final" and not job["scenes"]):
        if draft_rel:
            download(draft_rel, dest)
        if mode == "final" and rel:
            download(rel, dest)
        fetch_reuse(reuse, dest)
        return say("ready")
    pending = os.path.join(ROOT, "engine", "state", "pending.json")
    if os.path.exists(pending) and json.load(open(pending)).get("run_id") == job["run_id"]:
        log("this case is already on Kaggle: '3b - Collect' will start L2 again when it is done")
        return say("sent")
    json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"job: {len(job['scenes'])} clips, {len(job.get('narration', {}).get('pieces', []))} voice sentences")
    now = datetime.datetime.now(datetime.timezone.utc)
    in_slot = datetime.time(5, 30) <= now.time() <= datetime.time(9, 30)     # 11:00 am - 3:00 pm India time
    waiting = os.path.join(ROOT, "engine", "state", f"waiting-landmark-{a.case}.json")
    if not in_slot:
        os.makedirs(os.path.dirname(waiting), exist_ok=True)
        json.dump({"job": name, "week": f"landmark:{a.case}", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                  open(waiting, "w"), indent=2)
    subprocess.run(["git", "add", "-A", path, os.path.dirname(waiting)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Manzi Engine job: landmark case {a.case}"], cwd=ROOT, check=False)
    subprocess.run(["git", "pull", "-q", "--rebase"], cwd=ROOT, check=False)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    if in_slot:
        subprocess.run(["gh", "workflow", "run", "engine.yml", "-f", f"job={name}", "-f", "wait_minutes=170",
                        "-f", f"then_make=landmark:{a.case}"], cwd=ROOT, check=True)
        return say("sent")
    say("waiting")


if __name__ == "__main__":
    main()
