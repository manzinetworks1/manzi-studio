"""Collects a finished Manzi Engine run from Kaggle and publishes it as a GitHub Release.

Used by "3 - Manzi Engine" (right after the run) and "3b - Collect engine results" (schedule / button).
Does nothing unless engine/state/pending.json exists and the Kaggle run has finished.
Needs: KAGGLE_USERNAME, KAGGLE_KEY, GH_TOKEN in the environment; the kaggle and gh tools.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import time

PENDING = "engine/state/pending.json"
KERNEL = os.environ.get("KERNEL") or f"{os.environ['KAGGLE_USERNAME']}/manzi-engine"


def sh(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)


def main():
    if not os.path.exists(PENDING):
        print("No Manzi Engine run is waiting.")
        return
    pending = json.load(open(PENDING))
    status = sh("kaggle", "kernels", "status", KERNEL, check=False).stdout.lower()
    print(f"Kaggle status: {status.strip()}")
    if "complete" not in status and "error" not in status and "cancel" not in status:
        import calendar
        waited_h = (time.time() - calendar.timegm(time.strptime(pending["pushed_at"], "%Y-%m-%dT%H:%M:%SZ"))) / 3600
        week = pending.get("then_make")
        if week and ":" not in week and "queued" in status and waited_h > 4:
            # Kaggle is too busy: make the week's videos without the AI part so nothing is late
            print(f"Queued for {waited_h:.1f} h: making week {week} without the AI part")
            sh("gh", "workflow", "run", "make.yml", "-f", f"week={week}", "-f", "no_ai=true", check=False)
            notify(f"[Manzi Engine] Kaggle was busy: week {week} made without AI scenes",
                   f"<p>Kaggle kept the job in its queue for {waited_h:.1f} hours, so this week's videos are being made "
                   f"without the AI scenes and with the usual voice. You'll get the normal <b>videos ready</b> email.</p>")
            os.remove(PENDING)
            save_state(f"Manzi Engine: run {pending['run_id']} skipped (Kaggle queue)")
        else:
            print(f"Still {('queued' if 'queued' in status else 'running')} after {waited_h:.1f} h; try again later.")
        return

    out = "engine_out"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    sh("kaggle", "kernels", "output", KERNEL, "-p", out, check=False)
    files = [f for f in glob.glob(f"{out}/**/*", recursive=True) if os.path.isfile(f)]
    summary = {}
    for f in files:
        if os.path.basename(f) == "summary.json":
            summary = json.load(open(f))
    run_id = summary.get("run_id") or pending["run_id"]
    if run_id != pending["run_id"]:
        print(f"Kaggle's latest output is for run {run_id}, not {pending['run_id']}: waiting.")
        return

    notes = [f"# Manzi Engine run `{run_id}`", ""]
    if "complete" not in status:
        notes.append(f"⚠️ Kaggle reports: {status.strip()}")
    notes.append(f"Total time on Kaggle: {round(summary.get('total_s', 0) / 60, 1)} min")
    if summary.get("started_at"):
        import calendar
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        wait_min = (calendar.timegm(time.strptime(summary["started_at"], fmt)) - calendar.timegm(time.strptime(pending["pushed_at"], fmt))) / 60
        notes.append(f"Waited in Kaggle's queue: {wait_min:.0f} min (sent {pending['pushed_at']} UTC)")
        with open("engine/state/queue_log.csv", "a") as f:  # learn which hours are quiet
            f.write(f"{pending['pushed_at']},{summary['started_at']},{wait_min:.0f},{run_id}\n")
    for name, st in summary.get("stages", {}).items():
        notes.append(f"- {'✅' if st['ok'] else '❌'} {name}: {round(st['seconds'] / 60, 1)} min {st.get('note', '')}")
    for err in summary.get("errors", []):
        notes.append(f"- ❌ {err}")
    for f in files:
        base = os.path.basename(f)
        if base == "engine_results.json":
            notes += ["", "## Scenes"]
            for s in json.load(open(f))["scenes"]:
                if s.get("ok"):
                    notes.append(f"- ✅ {s['id']}: preview {s.get('preview_s')}s"
                                 + (f", upscale {s['upscale_s']}s" if 'upscale_s' in s else ""))
                else:
                    notes.append(f"- ❌ {s['id']}: {s.get('error', '')[:200]}")
        if base == "check.json":
            c = json.load(open(f))
            notes += ["", f"## Listen check (Whisper, pass mark {c.get('pass_mark')})"]
            for r in c.get("checks", []):
                notes.append(f"- {'✅' if r['pass'] else '❌'} {r['id']}: {r['score']} · heard: "
                             f"{next((t.get('heard', '') for t in r['takes'] if t['file'] == r['best']), '')[:120]}")
        if base.startswith("voice_") and base.endswith(".json"):
            v = json.load(open(f))
            notes += ["", f"## Narration — {v['engine']}",
                      f"{v.get('passed')}/{len(v.get('pieces', []))} pieces passed the Whisper check · "
                      f"reference pace {v.get('ref_wps')} words/s · generated in {v.get('generate_s')}s"]
            for p in v.get("pieces", []):
                notes.append(f"- {'✅' if p['passed'] else '⚠️'} {p['file']}: match {p['score']}, tempo ×{p['tempo']}")
    notes += ["", "Scenes made with MiniMax H3 (MiniMax H3 Community License) via Wan2GP and AIQUEST Academy's "
                  "Kaggle engine (Apache 2.0)."]
    with open("release_notes.md", "w") as f:
        f.write("\n".join(notes))

    tag = f"engine-{run_id}-{time.strftime('%Y%m%d-%H%M', time.gmtime())}"
    assets = [f for f in files if f.endswith((".mp4", ".wav", ".png", ".json", ".log", ".txt", ".pt"))]  # .pt: draft latents
    sh("gh", "release", "create", tag, "--title", f"Manzi Engine: {run_id}", "--notes-file", "release_notes.md",
       "--prerelease", *assets)
    print(f"✅ Published {len(assets)} files on release {tag}")
    url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}" \
          f"/releases/tag/{tag}"
    week = pending.get("then_make")
    if week and week.startswith("landmark:"):  # a landmark case: make its video now (it downloads this release)
        case = week.split(":", 1)[1]
        r = sh("gh", "workflow", "run", "landmark_make.yml", "-f", f"case={case}", check=False)
        print("started 'L2 - Make landmark video'" if r.returncode == 0 else f"⚠️ could not start 'L2': {r.stderr}")
    elif week and week.startswith("masala:"):  # a Masala Short: put it together now (it downloads this release)
        slug, _, mode = week.split(":", 1)[1].partition(":")
        args = ["-f", f"story={slug}"] + (["-f", f"mode={mode}"] if mode else [])
        r = sh("gh", "workflow", "run", "masala_make.yml", *args, check=False)
        print("started 'M - Make masala short'" if r.returncode == 0 else f"⚠️ could not start 'M': {r.stderr}")
    elif week:  # the weekly flow: make the videos now (make.py downloads this release)
        r = sh("gh", "workflow", "run", "make.yml", "-f", f"week={week}", check=False)
        print("started '2 - Make videos'" if r.returncode == 0 else f"⚠️ could not start '2 - Make videos': {r.stderr}")
    else:
        body = "".join(f"<p>{line}</p>" for line in notes if line and not line.startswith("#"))
        notify(f"[Manzi Engine] Run {run_id} is ready",
               f"<p><a href='{url}'><b>Open the results</b></a> (videos, voices and the report).</p>{body}")
    os.remove(PENDING)
    save_state(f"Manzi Engine: run {run_id} collected ({tag})")


def notify(subject, html):
    try:  # through the existing Manzi Studio mailer
        sys.path.insert(0, "pipeline")
        import common
        import mail
        mail.send(common.config(), subject, html)
    except Exception as e:
        print(f"⚠️ Email not sent: {e}")


def save_state(message):
    sh("git", "config", "user.name", "manzi-studio-bot")
    sh("git", "config", "user.email", "actions@users.noreply.github.com")
    sh("git", "add", "-A", "engine/state", check=False)
    sh("git", "commit", "-q", "-m", message, check=False)
    sh("git", "pull", "-q", "--rebase", check=False)
    pushed = sh("git", "push", "-q", check=False)
    print("state saved" if pushed.returncode == 0 else f"⚠️ could not save state: {pushed.stderr}")


if __name__ == "__main__":
    sys.exit(main())
