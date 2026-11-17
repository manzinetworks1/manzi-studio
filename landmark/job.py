"""L2, first step: the AI part of a landmark case video (Manzi Engine on Kaggle).

python landmark/job.py --case <slug> [--no-ai]

- Engine results already published (Release "engine-landmark-<slug>-..."): downloads them to
  out/landmark/<slug>/engine/ and prints ai=ready.
- Otherwise builds the job (every story scene, the Professor's start/end clips, every narration sentence in his
  cloned voice), sends it to "3 - Manzi Engine" in the 11 am-3 pm IST slot or leaves it waiting for "3c", and prints
  ai=sent or ai=waiting. When Kaggle is done, "3b - Collect" publishes the results and starts L2 again by itself.
Writes "ai=<off|ready|sent|waiting>" to $GITHUB_OUTPUT when run in GitHub Actions.
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


def release_for(sl):
    rels = json.loads(gh("releases?per_page=100"))
    rels = [r for r in rels if r["tag_name"].startswith(f"engine-landmark-{sl}-")]
    return sorted(rels, key=lambda r: r["created_at"])[-1] if rels else None


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
                 "No text, no captions, no logos, no watermarks.")
    return " ".join(parts)


def build_job(st, lcfg):
    sl = st["slug"]
    prof = json.load(open(CAST, encoding="utf-8"))
    beats = st["beats"]
    scene_ids = [b["id"] for b in beats if b["type"] == "scene"]
    next_continues = {scene_ids[i - 1] for i, sid in enumerate(scene_ids)
                      if i and next(b for b in beats if b["id"] == sid).get("cont")}
    scenes, pieces, prev = [], [], None
    for b in beats:
        if b["type"] == "professor":
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
            if b["id"] in next_continues:
                sc.update(save_frame=True, frame_time="end")
            scenes.append(sc)
            prev = b["id"]
        for s in b.get("narration", []):
            t = speakable(s)
            if t and t not in pieces:
                pieces.append(t)
    job = {"run_id": f"landmark-{sl}", "purpose": f"Landmark case video: {st['case']}", "scenes": scenes,
           "scene_time_limit_min": min(330, 13 * len(scenes) + 15)}
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
    job = build_job(st, lcfg)
    name = f"landmark-{a.case}.json"
    path = os.path.join(ROOT, "engine", "jobs", name)
    if a.build_only:
        json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return log(f"job written: {len(job['scenes'])} clips, {len(job.get('narration', {}).get('pieces', []))} sentences")
    rel = release_for(a.case)
    if rel:
        download(rel, os.path.join(ROOT, "out", "landmark", a.case, "engine"))
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
