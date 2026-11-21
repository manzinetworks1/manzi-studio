"""Manzi Engine voice stage: narration in the Professor's cloned voice, with an automatic quality check.

Runs in its own Python 3.11 environment (made with uv) after the video engine has exited, so the GPUs are free.
usage: python voice_stage.py <job.json> <out_dir> <engine name: chatterbox | qwen3>

For every narration piece:
  1. clone the reference voice (the approved Professor take) and read the text
  2. Whisper (faster-whisper small.en) writes down what was said; it must match the script (>= 0.85)
     or the piece is made again with another seed (up to 3 tries; the best try is kept)
  3. the pace is matched to the reference take (words per second, ffmpeg atempo, kept within 0.85x-1.30x)
Then the pieces are joined with short pauses and loudness-normalised into narration_<engine>.wav.
"""
import difflib
import json
import os
import re
import subprocess
import sys
import time

import ctypes
import glob
import site

# faster-whisper (CTranslate2) dlopens libcublas.so.12 / cuDNN 9 by name: load the pip-installed NVIDIA copies first.
for _pattern in ("nvidia/cublas/lib/libcublasLt.so.12", "nvidia/cublas/lib/libcublas.so.12", "nvidia/cudnn/lib/libcudnn*.so.9"):
    for _sp in site.getsitepackages():
        for _lib in sorted(glob.glob(os.path.join(_sp, _pattern))):
            try:
                ctypes.CDLL(_lib, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass

import soundfile as sf
import torch

job_path, OUT, ENGINE = sys.argv[1], sys.argv[2], sys.argv[3]
JOB = json.load(open(job_path))
NAR = JOB["narration"]
REF = os.path.join(OUT, NAR["ref_audio"])
REF_TEXT = NAR["ref_text"]
SPEED = float(NAR.get("speed", 1.0))  # extra pace on top of the reference take's pace
PIECES = NAR["pieces"]
TAG = ENGINE
REPORT = {"engine": ENGINE, "pieces": []}


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


from faster_whisper import WhisperModel

whisper = WhisperModel("small.en", device="cuda", compute_type="float16")


# numbers are compared as numbers: the script says "nineteen seventy-three", Whisper writes "1973"
# (a copy of pipeline/numwords.py, because this file runs on its own on Kaggle)
UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
ORD = {w: i for i, w in enumerate("_ first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
                                  "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split())
       if w != "_"}
ORD.update({w: 10 * i for i, w in enumerate("_ _ twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth "
                                            "ninetieth".split()) if w != "_"})
SAME = {"vs": "versus", "v": "versus", "mr": "mister", "dr": "doctor"}


def _merge(tokens):
    out, i = [], 0
    while i < len(tokens):
        groups, j = [], i
        while j < len(tokens):
            w = tokens[j]
            if w in TENS:
                v = TENS[w]
                nxt = tokens[j + 1] if j + 1 < len(tokens) else ""
                if nxt in UNITS and 0 < UNITS[nxt] < 10:
                    v += UNITS[nxt]; j += 1
                elif nxt in ORD and ORD[nxt] < 10:
                    v += ORD[nxt]; j += 1
                groups.append(v)
            elif w in UNITS:
                groups.append(UNITS[w])
            elif w in ORD and not groups:
                groups.append(ORD[w]); j += 1
                break
            elif w in ("hundred", "thousand") and groups:
                groups[-1] *= 100 if w == "hundred" else 1000
                if j + 1 < len(tokens) and tokens[j + 1] == "and" and j + 2 < len(tokens) and \
                        (tokens[j + 2] in UNITS or tokens[j + 2] in TENS):
                    j += 1
            else:
                break
            j += 1
        if not groups:
            out.append(tokens[i]); i += 1
            continue
        if len(groups) == 1:
            out.append(str(groups[0]))
        elif len(groups) == 2 and groups[0] % 100 == 0 and groups[0] and groups[1] < groups[0]:
            out.append(str(groups[0] + groups[1]))          # three hundred sixty eight, two thousand seven
        elif len(groups) == 2 and 1 <= groups[0] <= 99 and groups[1] < 100:
            out.append(str(groups[0] * 100 + groups[1]))    # nineteen seventy three
        else:
            out += [str(g) for g in groups]
        i = j
    return out


def words(text):
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.lower())          # 31st -> 31
    t = re.sub(r"(\d),(\d{3})", r"\1\2", t)                          # 1,000 -> 1000
    toks = re.sub(r"[^a-z0-9' ]+", " ", t).split()
    toks = [SAME.get(w, w) for w in toks]
    return _merge(toks)


def listen(path):
    """(transcript, words per second of actual speech)."""
    segments, _ = whisper.transcribe(path, language="en", beam_size=1, word_timestamps=True)
    ws = [w for s in segments for w in (s.words or [])]
    text = " ".join(w.word.strip() for w in ws)
    span = (ws[-1].end - ws[0].start) if len(ws) > 1 else 0.0
    return text, (len(ws) / span if span > 0.5 else 0.0)


def match(a, b):
    return difflib.SequenceMatcher(None, words(a), words(b)).ratio()


ref_heard, ref_wps = listen(REF)
TARGET_WPS = (ref_wps or 3.0) * SPEED
REPORT.update(ref_heard=ref_heard, ref_wps=round(ref_wps, 2), target_wps=round(TARGET_WPS, 2))
print(f"🎙️ Reference heard as: {ref_heard!r} at {ref_wps:.2f} words/s → target {TARGET_WPS:.2f} words/s", flush=True)

# ---- the cloning model ----
t_load = time.time()
if ENGINE == "chatterbox":
    from chatterbox.tts import ChatterboxTTS

    model = ChatterboxTTS.from_pretrained(device="cuda")

    def speak(text, seed, path):
        torch.manual_seed(seed)
        wav = model.generate(text, audio_prompt_path=REF, exaggeration=0.5, cfg_weight=0.5)
        sf.write(path, wav.squeeze(0).cpu().numpy(), model.sr)
elif ENGINE == "qwen3":
    from qwen_tts import Qwen3TTSModel

    model = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base", device_map="cuda:0", dtype=torch.float16)

    def speak(text, seed, path):
        torch.manual_seed(seed)
        wavs, sr = model.generate_voice_clone(text=text, language="English", ref_audio=REF, ref_text=REF_TEXT)
        sf.write(path, wavs[0], sr)
else:
    raise SystemExit(f"unknown voice engine {ENGINE}")
REPORT["model_load_s"] = round(time.time() - t_load)

parts = []
t_all = time.time()
for i, text in enumerate(PIECES, 1):
    best = None
    for attempt in range(3):
        raw = os.path.join(OUT, f"nar_{TAG}_{i:02d}_try{attempt + 1}.wav")
        t0 = time.time()
        speak(text, 1000 + 17 * attempt + i, raw)
        heard, wps = listen(raw)
        score = match(text, heard)
        info = dict(file=raw, heard=heard, score=round(score, 3), wps=round(wps, 2), seconds=round(time.time() - t0, 1))
        if best is None or score > best["score"]:
            best = info
        if score >= 0.85:
            break
    for attempt_file in [f for f in os.listdir(OUT) if f.startswith(f"nar_{TAG}_{i:02d}_try")]:
        if os.path.join(OUT, attempt_file) != best["file"]:
            os.remove(os.path.join(OUT, attempt_file))
    tempo = min(1.30, max(0.85, TARGET_WPS / best["wps"])) if best["wps"] else 1.0
    final = os.path.join(OUT, f"nar_{TAG}_{i:02d}.wav")
    if abs(tempo - 1.0) > 0.03:
        ffmpeg("-i", best["file"], "-filter:a", f"atempo={tempo:.3f}", "-ar", "24000", "-ac", "1", final)
    else:
        ffmpeg("-i", best["file"], "-ar", "24000", "-ac", "1", final)
    os.remove(best["file"])
    best.update(file=os.path.basename(final), tempo=round(tempo, 3), passed=best["score"] >= 0.85, text=text)
    REPORT["pieces"].append(best)
    parts.append(final)
    print(f"{'✅' if best['passed'] else '⚠️'} piece {i}: match {best['score']:.2f}, {best['wps']} w/s, tempo x{tempo:.2f}",
          flush=True)

# ---- join with 0.3 s pauses, normalise loudness ----
gap = os.path.join(OUT, "_gap.wav")
ffmpeg("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.3", gap)
lst = os.path.join(OUT, "_list.txt")
with open(lst, "w") as f:
    for p in parts:
        f.write(f"file '{p}'\nfile '{gap}'\n")
joined = os.path.join(OUT, "_joined.wav")
ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined)
ffmpeg("-i", joined, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "24000", os.path.join(OUT, f"narration_{TAG}.wav"))
for p in (gap, lst, joined):
    os.remove(p)
REPORT["generate_s"] = round(time.time() - t_all)
REPORT["passed"] = sum(p["passed"] for p in REPORT["pieces"])
with open(os.path.join(OUT, f"voice_{TAG}.json"), "w") as f:
    json.dump(REPORT, f, indent=2)
print(f"✅ narration_{TAG}.wav: {REPORT['passed']}/{len(PIECES)} pieces passed the check in {REPORT['generate_s']}s",
      flush=True)
