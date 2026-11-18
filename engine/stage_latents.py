"""Puts files from earlier engine runs (approved drafts' latents, last pictures of scenes) on Kaggle for a new run.

python engine/stage_latents.py engine/jobs/<job>.json

The job may list {"inputs": [{"release": "<GitHub release tag>", "file": "<asset name>"}, ...]}. Those assets are
downloaded from the repo's Releases and published as a new version of the private Kaggle dataset
<KAGGLE_USERNAME>/manzi-latents (created on first use); the run then attaches it and finds the files under
/kaggle/input. Prints "dataset=<owner/slug>" to $GITHUB_OUTPUT (nothing when the job lists no inputs).
"""
import json, os, subprocess, sys, tempfile, time

job = json.load(open(sys.argv[1]))
items = job.get("inputs") or []
out = os.environ.get("GITHUB_OUTPUT")
if not items:
    print("no files from earlier runs needed")
    sys.exit(0)
repo = os.environ.get("GITHUB_REPOSITORY", "manzinetworks1/manzi-studio")
user = os.environ["KAGGLE_USERNAME"]
ds = f"{user}/manzi-latents"
d = tempfile.mkdtemp()


def sh(*a, check=True):
    r = subprocess.run(a, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"❌ {' '.join(a[:4])}: {r.stderr or r.stdout}")
    return r


ids = {}
for it in items:
    if it["release"] not in ids:
        rel = json.loads(sh("gh", "api", f"repos/{repo}/releases/tags/{it['release']}").stdout)
        ids[it["release"]] = {a["name"]: a["id"] for a in rel["assets"]}
    aid = ids[it["release"]].get(it["file"])
    if not aid:
        raise SystemExit(f"❌ {it['file']} is not in release {it['release']}")
    with open(os.path.join(d, it["file"]), "wb") as f:
        f.write(subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                                f"repos/{repo}/releases/assets/{aid}"], capture_output=True, check=True).stdout)
print(f"downloaded {len(items)} file(s): {', '.join(sorted(os.listdir(d)))}")
json.dump({"title": "Manzi latents", "id": ds, "licenses": [{"name": "CC0-1.0"}]},
          open(os.path.join(d, "dataset-metadata.json"), "w"))
exists = sh("kaggle", "datasets", "status", ds, check=False)
if exists.returncode == 0 and "ready" in exists.stdout.lower() + exists.stderr.lower():
    r = sh("kaggle", "datasets", "version", "-p", d, "-m", f"run {job.get('run_id')}", "--dir-mode", "skip", check=False)
else:
    r = sh("kaggle", "datasets", "create", "-p", d, "--dir-mode", "skip", check=False)
print((r.stdout + r.stderr).strip()[-600:])
if r.returncode:
    raise SystemExit("❌ Kaggle did not accept the files")
for _ in range(60):  # Kaggle needs a little while before a new version can be attached
    time.sleep(15)
    st = sh("kaggle", "datasets", "status", ds, check=False)
    s = (st.stdout + st.stderr).lower()
    print("dataset status:", s.strip())
    if "ready" in s:
        break
else:
    raise SystemExit("❌ the Kaggle dataset did not become ready in 15 min")
time.sleep(30)  # the status says ready a moment before the new version is the one attached
if out:
    open(out, "a").write(f"dataset={ds}\n")
