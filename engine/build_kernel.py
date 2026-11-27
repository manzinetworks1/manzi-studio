"""Builds the Kaggle job script for one run of the Manzi Engine.

usage: python engine/build_kernel.py <job.json> <build_dir> [--gpu-dataset owner/slug]

Takes AIQUEST's notebook (frozen copy in engine/vendor/aiquest_h3.ipynb), lifts out its Step 1 cell and the engine
it writes in Step 2 (RUN_SCRIPT_CODE), cuts the engine just before its Gradio UI, appends our headless runner, and
packs everything plus the job into <build_dir>/manzi_engine.py with a kernel-metadata.json next to it.
"""
import base64
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(ROOT, "vendor", "aiquest_h3.ipynb")
UI_MARKER = "# ==== Gradio UI (AIQUEST Academy branding) ===="
KERNEL_ID = os.environ.get("MANZI_KERNEL_ID", "manojpobox/manzi-engine")


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def main():
    job_path, build_dir = sys.argv[1], sys.argv[2]
    datasets = []
    settings_file = os.path.join(ROOT, "settings.json")
    if os.path.exists(settings_file):
        ds = json.load(open(settings_file)).get("models_dataset")
        if ds:
            datasets.append(ds)
    if "--gpu-dataset" in sys.argv:
        datasets.append(sys.argv[sys.argv.index("--gpu-dataset") + 1])
    with open(job_path) as f:
        job = json.load(f)
    with open(VENDOR, encoding="utf-8") as f:
        nb = json.load(f)
    cells = ["".join(c["source"]) if isinstance(c["source"], list) else c["source"]
             for c in nb["cells"] if c.get("cell_type") == "code"]
    step1 = next((c for c in cells if "# Step 1:" in c and "WAN2GP_COMMIT" in c), None)
    step2 = next((c for c in cells if "RUN_SCRIPT_CODE = r'''" in c), None)
    if not step1 or not step2:
        raise SystemExit("❌ AIQUEST notebook layout changed: Step 1 / Step 2 cells not found")
    m = re.search(r"RUN_SCRIPT_CODE = r'''(.*?)\n'''", step2, re.S)
    if not m:
        raise SystemExit("❌ AIQUEST notebook layout changed: engine code (RUN_SCRIPT_CODE) not found")
    engine = m.group(1)
    if UI_MARKER not in engine:
        raise SystemExit("❌ AIQUEST notebook layout changed: Gradio UI marker not found")
    for needed in ("def make_preview(", "def make_upscale(", "REFINE_FREE = [0]", "_t_load = time.time()"):
        if needed not in engine:
            raise SystemExit(f"❌ AIQUEST engine changed: {needed!r} not found")
    engine = engine.split(UI_MARKER)[0]
    with open(os.path.join(ROOT, "runner_snippet.py"), encoding="utf-8") as f:
        engine += "\n" + f.read()
    with open(os.path.join(ROOT, "voice_stage.py"), encoding="utf-8") as f:
        voice = f.read()
    with open(os.path.join(ROOT, "check_stage.py"), encoding="utf-8") as f:
        check = f.read()
    with open(os.path.join(ROOT, "kernel_main.py"), encoding="utf-8") as f:
        script = f.read()
    cast = {}
    ref_file = (job.get("narration") or {}).get("ref_audio_file")
    if ref_file:
        with open(ref_file, "rb") as f:
            cast[job["narration"]["ref_audio"]] = base64.b64encode(f.read()).decode("ascii")
    for key, value in (("__CAST_B64__", b64(json.dumps(cast))), ("__JOB_B64__", b64(json.dumps(job))), ("__STEP1_B64__", b64(step1)),
                       ("__ENGINE_B64__", b64(engine)), ("__VOICE_B64__", b64(voice)),
                       ("__CHECK_B64__", b64(check))):
        script = script.replace(key, value)
    compile(script, "manzi_engine.py", "exec")  # syntax check of the whole package
    compile(engine, "run_manzi.py", "exec")
    os.makedirs(build_dir, exist_ok=True)
    with open(os.path.join(build_dir, "manzi_engine.py"), "w", encoding="utf-8") as f:
        f.write(script)
    meta = {
        "id": KERNEL_ID,
        "title": "Manzi Engine",
        "code_file": "manzi_engine.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_tpu": False,
        "enable_internet": True,
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": datasets,
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    with open(os.path.join(build_dir, "kernel-metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"✅ Built {build_dir}/manzi_engine.py ({len(script) // 1024} KB) for run {job.get('run_id')}: "
          f"{len(job.get('scenes', []))} scenes, narration: {bool(job.get('narration'))}")


if __name__ == "__main__":
    main()
