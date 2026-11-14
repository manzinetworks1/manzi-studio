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
        print("Still queued or running; try again later.")
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
    assets = [f for f in files if f.endswith((".mp4", ".wav", ".png", ".json", ".log", ".txt"))]
    sh("gh", "release", "create", tag, "--title", f"Manzi Engine: {run_id}", "--notes-file", "release_notes.md",
       "--prerelease", *assets)
    print(f"✅ Published {len(assets)} files on release {tag}")
    try:  # "results ready" email through the existing Manzi Studio mailer
        sys.path.insert(0, "pipeline")
        import common
        import mail
        url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}" \
              f"/releases/tag/{tag}"
        body = "".join(f"<p>{line}</p>" for line in notes if line and not line.startswith("#"))
        mail.send(common.config(), f"[Manzi Engine] Run {run_id} is ready",
                  f"<p><a href='{url}'><b>Open the results</b></a> (videos, voices and the report).</p>{body}")
    except Exception as e:
        print(f"⚠️ Email not sent: {e}")

    os.remove(PENDING)
    sh("git", "config", "user.name", "manzi-studio-bot")
    sh("git", "config", "user.email", "actions@users.noreply.github.com")
    sh("git", "pull", "-q", "--rebase")
    sh("git", "add", "-A", "engine/state", check=False)
    sh("git", "commit", "-m", f"Manzi Engine: run {run_id} collected ({tag})", check=False)
    sh("git", "push", check=False)


if __name__ == "__main__":
    sys.exit(main())
