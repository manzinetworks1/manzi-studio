"""Manzi Engine check stage: listens to every spoken clip and keeps the take that says the script best.

Runs in its own Python 3.11 environment (made with uv) after the video engine has exited, so the GPUs are free.
usage: python check_stage.py <job.json> <out_dir>

The job lists {"checks": [{"id": <clip id>, "line": <script line>, "lang": "hi",
                           "takes": "auto" (this run's <id>_<size>_t<n>.mp4) or [file, ...] (an audit), "base": null}]}
For every check:
  1. Whisper large-v3 writes down what each take says (Hindi)
  2. each take gets a score: how close the words are to the script (0-1), and whether the line ends cleanly
  3. the best take is copied to <base>.mp4 (+ .pt/.json latents) so the rest of the pipeline uses it;
     with base null (an audit of clips made earlier) nothing is copied, only the report is written
Writes check.json (every take, what was heard, the score, pass/fail) to the output folder.
"""
import ctypes
import difflib
import glob
import json
import os
import re
import shutil
import site
import subprocess
import sys
import time

for _pattern in ("nvidia/cublas/lib/libcublasLt.so.12", "nvidia/cublas/lib/libcublas.so.12", "nvidia/cudnn/lib/libcudnn*.so.9"):
    for _sp in site.getsitepackages():
        for _lib in sorted(glob.glob(os.path.join(_sp, _pattern))):
            try:
                ctypes.CDLL(_lib, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass

from faster_whisper import WhisperModel  # noqa: E402

job_path, OUT = sys.argv[1], sys.argv[2]
JOB = json.load(open(job_path))
PASS = float(JOB.get("check_pass", 0.6))
model = WhisperModel(JOB.get("check_model", "large-v3"), device="cuda", compute_type="float16")


def find(name):
    p = os.path.join(OUT, name)
    if os.path.exists(p):
        return p
    hits = glob.glob(f"/kaggle/input/**/{name}", recursive=True)
    return hits[0] if hits else None


def norm(text):
    """Only the Devanagari letters and digits, no spaces or punctuation: Whisper's spacing and the script's
    English words (Sunny, Mumbai) must not decide the score."""
    text = re.sub(r"[।॥.,!?…'\"“”‘’:;\-–—()]", " ", text)
    return "".join(re.findall(r"[ऀ-ॿ0-9]+", text))


def score(line, heard):
    a, b = norm(line), norm(heard)
    if not a:
        return 1.0
    m = difflib.SequenceMatcher(None, a, b)
    match = sum(bl.size for bl in m.get_matching_blocks())
    cover = match / len(a)                      # how much of the script was said
    extra = max(0, len(b) - match) / len(a)      # mumbling beyond the script
    tail = difflib.SequenceMatcher(None, a[-6:], b[-10:]).ratio() if len(b) >= 3 else 0.0  # the line's end was said
    return round(max(0.0, cover - 0.5 * extra) * (0.7 + 0.3 * tail), 3)


def wav(mp4):
    w = mp4 + ".16k.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-vn", "-ac", "1", "-ar", "16000", w], check=True)
    return w


report = []
t0 = time.time()
for ck in JOB.get("checks", []):
    rows = []
    names = ck.get("takes") or []
    if names == "auto":  # takes made in this run: <id>_<size>_t<n>.mp4
        names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(OUT, f"{ck['id']}_*_t[0-9].mp4")))
        ck["base"] = names[0].rsplit("_t", 1)[0] if names else None
    for name in names:
        path = find(name)
        if not path:
            rows.append({"file": name, "missing": True, "score": 0.0})
            continue
        try:
            segs, _ = model.transcribe(wav(path), language=ck.get("lang", "hi"), beam_size=5, vad_filter=False,
                                       condition_on_previous_text=False)
            heard = " ".join(s.text.strip() for s in segs).strip()
        except Exception as e:
            heard = f"(error: {e!r})"
        rows.append({"file": name, "heard": heard, "score": score(ck["line"], heard)})
    best = max(rows, key=lambda r: r["score"]) if rows else None
    rec = {"id": ck["id"], "line": ck["line"], "takes": rows, "best": best and best["file"],
           "score": best["score"] if best else 0.0, "pass": bool(best) and best["score"] >= PASS}
    if ck.get("base") and best and not best.get("missing"):
        stem = best["file"][:-4]
        for ext in (".mp4", ".pt", ".json"):
            src = find(stem + ext)
            if src:
                shutil.copy(src, os.path.join(OUT, ck["base"] + ext))
        for r in rows:  # the other takes are not needed any more (they would only fill the release)
            if r["file"] != best["file"]:
                for ext in (".mp4", ".pt", ".json"):
                    p = os.path.join(OUT, r["file"][:-4] + ext)
                    if os.path.exists(p):
                        os.remove(p)
    report.append(rec)
    print(f"{'✅' if rec['pass'] else '❌'} {ck['id']}: {rec['score']}  {ck['line']}  ->  "
          f"{best.get('heard') if best else '-'}", flush=True)
    with open(os.path.join(OUT, "check.json"), "w", encoding="utf-8") as f:
        json.dump({"pass_mark": PASS, "checks": report}, f, ensure_ascii=False, indent=2)
for w in glob.glob(os.path.join(OUT, "*.16k.wav")):
    os.remove(w)
print(f"✅ checked {len(report)} clip(s) in {time.time() - t0:.0f}s: "
      f"{sum(r['pass'] for r in report)} pass, {sum(not r['pass'] for r in report)} to remake", flush=True)
