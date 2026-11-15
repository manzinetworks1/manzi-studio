"""Manzi Engine — Kaggle job script (built by engine/build_kernel.py; do not edit the built copy).

Runs headless on Kaggle GPU T4 x2, started by the GitHub workflow "3 - Manzi Engine":
  1. AIQUEST's Step 1, unchanged: pinned Wan2GP + H3 weights (MiniMax H3 pruned INT8, PDMD 4-step LoRA,
     NVIDIA Open-H3-Regenerate-2K)
  2. AIQUEST's engine (tensor-parallel H3 on both T4s) with our headless job runner in place of its web page:
     every scene of the job -> 384p preview with sound (+ 720p regenerate when asked)
  3. the voice stage: narration read in the Professor's cloned voice, checked by Whisper
Results go to /kaggle/working/manzi_out (the kernel's Output), which GitHub downloads when the run is complete.

Credits: AIQUEST Academy's "MiniMax H3 + Open-H3 Regenerate 2K" notebook (Apache 2.0), Wan2GP by DeepBeepMeep,
MiniMax H3 (MiniMax H3 Community License: credit "MiniMax H3"), NVIDIA Open-H3-Regenerate-2K, PDMD.
"""
import base64
import json
import os
import subprocess
import sys
import time

T_START = time.time()
JOB = json.loads(base64.b64decode("__JOB_B64__").decode())
STEP1 = base64.b64decode("__STEP1_B64__").decode()
ENGINE = base64.b64decode("__ENGINE_B64__").decode()
VOICE_STAGE = base64.b64decode("__VOICE_B64__").decode()
CAST = json.loads(base64.b64decode("__CAST_B64__").decode())  # {file name: base64} e.g. the Professor's voice

OUT = "/kaggle/working/manzi_out"
WORK = "/kaggle/tmp/manzi"
os.makedirs(OUT, exist_ok=True)
os.makedirs(WORK, exist_ok=True)
os.chdir(WORK)  # Wan2GP and the engine live here, not in /kaggle/working (which is saved as the kernel output)
SUMMARY = {"run_id": JOB.get("run_id"), "stages": {}, "errors": [],
           "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T_START))}
for _name, _data in CAST.items():
    with open(os.path.join(OUT, _name), "wb") as _f:
        _f.write(base64.b64decode(_data))


def save_summary():
    SUMMARY["total_s"] = round(time.time() - T_START)
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(SUMMARY, f, indent=2)


def stage(name):
    print(f"\n{'#' * 70}\n# {name}\n{'#' * 70}", flush=True)
    return time.time()


def done(name, t0, ok=True, note=""):
    SUMMARY["stages"][name] = {"ok": ok, "seconds": round(time.time() - t0), "note": note}
    save_summary()


# ---- 0. Hardware check: the engine splits H3 across two T4s ----
t = stage("0. Hardware")
gpus = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                      capture_output=True, text=True).stdout.strip().splitlines()
print("\n".join(gpus) or "no GPU", flush=True)
SUMMARY["gpus"] = gpus
if len(gpus) < 2:
    SUMMARY["errors"].append("Needs Kaggle GPU T4 x2; this run got: " + (", ".join(gpus) or "no GPU"))
    done("hardware", t, False)
    sys.exit(1)
done("hardware", t)

# ---- 1. AIQUEST Step 1: pinned code, dependencies, weights (models from an attached dataset are reused) ----
if JOB.get("scenes") or JOB.get("save_models"):
    t = stage("1. Setup: pinned Wan2GP + H3 weights")
    try:
        exec(compile(STEP1, "aiquest_step1.py", "exec"), {"__name__": "aiquest_step1"})
        done("setup", t)
    except BaseException as e:  # SystemExit included: Step 1 exits on missing GPUs / disk
        SUMMARY["errors"].append(f"setup: {e!r}")
        done("setup", t, False)
        sys.exit(1)

# ---- 1a. Weights from the attached dataset: copy them to the local disk ----
# AIQUEST's Step 1 links files from /kaggle/input. That disk is network-backed and very slow at the random reads the
# engine does while splitting the DiT across the GPUs (it took ~10 min per block instead of ~1.5 s), so each linked
# file is copied once to /kaggle/tmp (a sequential read: a few minutes for 43 GB).
if JOB.get("scenes"):
    t = stage("1a. Copy the saved models to the local disk")
    import shutil
    copied = 0
    for root in ("/kaggle/tmp/h3_models", "/kaggle/tmp/h3_regen", "/kaggle/tmp/h3_loras"):
        for dirpath, _, files in os.walk(root):
            for name in files:
                path = os.path.join(dirpath, name)
                if os.path.islink(path) and os.path.realpath(path).startswith("/kaggle/input"):
                    src = os.path.realpath(path)
                    os.remove(path)
                    with open(src, "rb") as fi, open(path + ".part", "wb") as fo:
                        shutil.copyfileobj(fi, fo, 64 * 1024 * 1024)
                    os.replace(path + ".part", path)
                    copied += os.path.getsize(path)
    print(f"✅ {copied / 1e9:.1f} GB copied in {time.time() - t:.0f}s", flush=True)
    done("copy_models", t, note=f"{copied / 1e9:.1f} GB")

# ---- 1b. One-time: save the downloaded weights as a private Kaggle dataset (later runs attach it) ----
if JOB.get("save_models"):
    t = stage("1b. Save models to a private Kaggle dataset")
    try:
        from kaggle_secrets import UserSecretsClient
        token = UserSecretsClient().get_secret("KAGGLE_API_TOKEN")  # a Kaggle secret on this notebook, never in code
        env = dict(os.environ, KAGGLE_API_TOKEN=token)
        ds_dir = "/kaggle/tmp/models_dataset"
        os.makedirs(ds_dir, exist_ok=True)
        for root in ("/kaggle/tmp/h3_models", "/kaggle/tmp/h3_regen"):
            for dirpath, _, files in os.walk(root):
                for name in files:
                    src = os.path.join(dirpath, name)
                    dst = os.path.join(ds_dir, name)
                    if not os.path.exists(dst) and not name.endswith((".part", ".lock")) and ".cache" not in src:
                        os.link(src, dst) if os.stat(src).st_dev == os.stat(ds_dir).st_dev else os.symlink(src, dst)
        slug = JOB["save_models"]
        with open(os.path.join(ds_dir, "dataset-metadata.json"), "w") as f:
            json.dump({"title": "Manzi H3 Models", "id": slug, "licenses": [{"name": "other"}]}, f)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "kaggle>=1.7.4", "six"], check=True)
        files = sorted(os.listdir(ds_dir))
        print(f"Uploading {len(files)} files to private dataset {slug}: {files}", flush=True)
        r = subprocess.run(["kaggle", "datasets", "create", "-p", ds_dir, "--dir-mode", "skip"], env=env,
                           capture_output=True, text=True)
        print(r.stdout[-3000:], r.stderr[-3000:], flush=True)
        ok = r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower()
        done("save_models", t, ok, note=slug)
    except Exception as e:
        SUMMARY["errors"].append(f"save models: {e!r}")
        done("save_models", t, False)

# ---- 2. Video engine: every scene of the job ----
job_file = os.path.join(WORK, "job.json")
with open(job_file, "w") as f:
    json.dump(JOB, f)
if JOB.get("scenes"):
    t = stage("2. Scenes (MiniMax H3 engine)")
    with open("run_manzi.py", "w", encoding="utf-8") as f:
        f.write(ENGINE)
    env = dict(os.environ, MANZI_JOB=job_file, MANZI_OUT=OUT, PYTHONWARNINGS="ignore", TQDM_DISABLE="1",
               PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    limit = int(JOB.get("scene_time_limit_min", 150)) * 60  # a stuck run must not eat the week's GPU hours
    try:
        rc = subprocess.call([sys.executable, "-u", "run_manzi.py"], env=env, timeout=limit)
    except subprocess.TimeoutExpired:
        rc = "timeout"
        SUMMARY["errors"].append(f"scene engine stopped after {limit // 60} min (time limit)")
    if rc not in (0, "timeout"):
        SUMMARY["errors"].append(f"scene engine exit code {rc}")
    done("scenes", t, rc == 0)

# ---- 3. Voice stage: narration in the cloned Professor voice, Whisper-checked ----
if JOB.get("narration"):
    t = stage("3. Voice: environment (Python 3.11 via uv)")
    env_dir = "/kaggle/tmp/voice_env"
    ok = True
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=True)
        subprocess.run(["uv", "venv", "-q", "-p", "3.11", env_dir], check=True)
        done("voice_env", t)
    except Exception as e:
        ok = False
        SUMMARY["errors"].append(f"voice env: {e!r}")
        done("voice_env", t, False)
    with open(os.path.join(WORK, "voice_stage.py"), "w", encoding="utf-8") as f:
        f.write(VOICE_STAGE)
    common = ["faster-whisper", "soundfile", "setuptools<80", "nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"]
    packages = {"chatterbox": ["chatterbox-tts", *common],  # setuptools: Perth watermarker needs pkg_resources
                "qwen3": ["qwen-tts", *common]}
    for engine in JOB["narration"].get("engines", ["chatterbox"]):
        if not ok:
            break
        t = stage(f"3. Voice: {engine}")
        py = os.path.join(env_dir + "_" + engine, "bin", "python")
        try:
            subprocess.run(["uv", "venv", "-q", "-p", "3.11", env_dir + "_" + engine], check=True)
            subprocess.run(["uv", "pip", "install", "-q", "--python", py, *packages[engine]], check=True,
                           timeout=1200)
            rc = subprocess.call([py, "-u", os.path.join(WORK, "voice_stage.py"), job_file, OUT, engine],
                                 timeout=2400)
            if rc != 0:
                SUMMARY["errors"].append(f"voice {engine}: exit code {rc}")
            done(f"voice_{engine}", t, rc == 0)
        except Exception as e:
            SUMMARY["errors"].append(f"voice {engine}: {e!r}")
            done(f"voice_{engine}", t, False)

save_summary()
print(f"\n✅ Manzi Engine run {JOB.get('run_id')} finished in {round((time.time() - T_START) / 60, 1)} min",
      flush=True)
