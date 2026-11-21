"""The week's AI part (Manzi Engine on Kaggle), used by "2 - Make videos" before rendering.

python pipeline/engine_week.py --week 2026-11-15 [--no-ai]

- If AI is switched off (config "ai.enabled"), --no-ai is given, or the week has no English topic: prints ai=off.
- If the engine's results for this week are already published (Release "engine-week-<week>-..."): downloads them to
  out/<week>/engine/ and prints ai=ready.
- Otherwise: builds the job (opening scene + Professor start/end clips per topic, and every sentence of the week's
  videos in the Professor's voice), starts "3 - Manzi Engine" with it and prints ai=sent. When Kaggle is done, the
  collector publishes the results and starts "2 - Make videos" again by itself.
Writes "ai=<off|ready|sent>" to $GITHUB_OUTPUT when run in GitHub Actions.
"""
import argparse, datetime, glob, json, os, subprocess, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, config, log
from specs import planned_specs, plain
from voice import speakable

CAST = os.path.join(ROOT, "engine", "cast", "professor.json")
REPO = os.environ.get("GITHUB_REPOSITORY", "manzinetworks1/manzi-studio")
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def gh(path, accept="application/vnd.github+json"):
    req = urllib.request.Request(f"{API}/repos/{REPO}/{path}", headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                                                          "Accept": accept})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def release_for(week):
    rels = json.loads(gh("releases?per_page=50"))
    rels = [r for r in rels if r["tag_name"].startswith(f"engine-week-{week}-")]
    return sorted(rels, key=lambda r: r["created_at"])[-1] if rels else None


def download(rel, dest):
    os.makedirs(dest, exist_ok=True)
    for a in rel["assets"]:
        path = os.path.join(dest, a["name"])
        if not os.path.exists(path):
            open(path, "wb").write(gh(f"releases/assets/{a['id']}", "application/octet-stream"))
    log(f"engine results: {len(rel['assets'])} files in {os.path.relpath(dest, ROOT)}")


def hook_scene(h):
    """The opening scene, written with the rules from the lip-sync tests (close-up, shot from behind the listener,
    one short line, everyone Indian)."""
    return (f"Cinematic close-up inside {h['place']}, in daylight, filmed from just behind {h['listener']}: at the far left "
            f"edge of the frame, out of focus, the back of {h['listener']}'s head and shoulder. In sharp focus, the speaker: "
            f"{h['speaker']}, clearly Indian with brown skin, framed from the chest up so the face fills about half of the frame "
            f"height, looks at {h['listener']} (towards the camera) and speaks clearly, with crisp, well-articulated mouth "
            f"movements and no long pauses. Softly blurred background with other Indian people. Static camera, natural light.")


def build_job(week, packs, cfg):
    cast = json.load(open(CAST, encoding="utf-8"))
    ai_cfg = cfg.get("ai", {})
    scenes, pieces = [], []
    for pack in packs:
        q = pack["qnum"]; ai = pack.get("ai") or {}
        if ai.get("hook") and ai_cfg.get("hook", True):
            h = ai["hook"]
            scenes.append({"id": f"q{q}_hook", "kind": "scene", "scene": hook_scene(h), "dialogue": h["line"],
                           "sound": h.get("sound", "") + ", the speaker's clear Indian-accented voice.", "duration": "5 s",
                           "output": "720p", "preset": "Fast"})
        if ai_cfg.get("professor", True):
            for part, default in (("intro", f"Hello students! Today: {plain(pack['topic'])}. Let's begin."),
                                  ("outro", "Comment NOTES for the free PDF. See you next time!")):
                scenes.append({"id": f"q{q}_prof_{part}", "kind": "professor", "seed": cast["seed"], "scene": cast["scene"],
                               "dialogue": ai.get(f"professor_{part}") or default, "sound": cast["sound"],
                               # 384p like the approved takes: the same seed at another size would give another face
                               "preview": "384p", "duration": "5 s", "output": "720p", "preset": "Fast"})
        if ai_cfg.get("voice", True):
            for spec in planned_specs(pack, cfg, cfg["channel"]):
                for b in spec["beats"]:
                    t = speakable(b.get("say", ""))
                    if t and t not in pieces:
                        pieces.append(t)
    job = {"run_id": f"week-{week}", "purpose": f"AI scenes and Professor voice for week {week}", "scenes": scenes}
    if pieces:
        job["narration"] = {"ref_audio_file": "engine/cast/professor_voiceA.wav", "ref_audio": "professor_voiceA.wav",
                            "ref_text": cast["dialogue"], "speed": float(ai_cfg.get("voice_speed", 1.0)),
                            "engines": [ai_cfg.get("voice_engine", "qwen3")], "pieces": pieces}
    return job


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--week", required=True); ap.add_argument("--no-ai", action="store_true")
    a = ap.parse_args(); cfg = config(); week = a.week
    out = os.environ.get("GITHUB_OUTPUT")

    def say(state):
        log(f"AI part: {state}")
        if out:
            open(out, "a").write(f"ai={state}\n")

    packs = [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(os.path.join(ROOT, "weeks", week, "q*.json")))]
    packs = [p for p in packs if p.get("language", "english") != "hindi"]  # the Professor speaks English
    if a.no_ai or not cfg.get("ai", {}).get("enabled") or not packs:
        return say("off")
    rel = release_for(week)
    if rel:
        download(rel, os.path.join(ROOT, "out", week, "engine"))
        return say("ready")
    job = build_job(week, packs, cfg)
    path = os.path.join(ROOT, "engine", "jobs", f"week-{week}.json")
    json.dump(job, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"job: {len(job['scenes'])} scenes, {len(job.get('narration', {}).get('pieces', []))} voice sentences")
    # Kaggle's free GPUs are least busy in the Indian late morning (night in the USA): the job waits for that slot
    now = datetime.datetime.now(datetime.timezone.utc)
    start_utc = datetime.time(5, 30)                     # 11:00 am India time
    in_slot = start_utc <= now.time() <= datetime.time(9, 30)
    waiting = os.path.join(ROOT, "engine", "state", "waiting.json")
    if not in_slot:
        os.makedirs(os.path.dirname(waiting), exist_ok=True)
        json.dump({"job": f"week-{week}.json", "week": week, "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                  open(waiting, "w"), indent=2)
    subprocess.run(["git", "add", "-A", path, os.path.dirname(waiting)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Manzi Engine job for week {week}"], cwd=ROOT, check=False)
    subprocess.run(["git", "pull", "-q", "--rebase"], cwd=ROOT, check=False)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    if in_slot:
        subprocess.run(["gh", "workflow", "run", "engine.yml", "-f", f"job=week-{week}.json", "-f", "wait_minutes=0",
                        "-f", f"then_make={week}"], cwd=ROOT, check=True)
        return say("sent")
    say("waiting")


if __name__ == "__main__":
    main()
