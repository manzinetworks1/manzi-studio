
# ==== Manzi Engine: headless job runner (replaces AIQUEST's Gradio UI) ====
# Appended by engine/build_kernel.py to AIQUEST's engine code, cut just before its Gradio UI section, so every
# function above (make_preview, make_upscale, the tensor-parallel DiT, the LoRA runtime...) is used unchanged.
import json as _mz_json
import shutil as _mz_shutil
from PIL import Image as _MzImage

# The UI section normally sets this budget for upscale planning; without it every upscale would "not fit".
REFINE_FREE[0] = min(torch.cuda.mem_get_info(d)[0] for d in DEVICES) - REFINE_LORA_BYTES - 100 * 2**20

_MZ_JOB = _mz_json.load(open(os.environ["MANZI_JOB"]))
_MZ_OUT = os.environ.get("MANZI_OUT", "/kaggle/working/manzi_out")
os.makedirs(_MZ_OUT, exist_ok=True)
_MZ_RESULTS = {"run_id": _MZ_JOB.get("run_id"), "engine_load_s": round(time.time() - _t_load), "scenes": []}
_MZ_FRAMES = {}


def _mz_ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


_MZ_PREVIEW_AREAS = {"384p": 672 * 384, "480p": 832 * 480, "544p": 960 * 544}


def _mz_speech_tail(mp4, drop_db=18.0):
    """(seconds after the last loud speech sound, clip length). Level-based: speech is found as 50 ms frames within
    `drop_db` of the loudest frame, so room tone / ambience doesn't count (ffmpeg silencedetect did not work here:
    it reports a closing silence_end at the end of the file)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", mp4, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if len(a) < 1600:
        return 0.0, 0.0
    frames = a[: len(a) // 800 * 800].reshape(-1, 800)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    loud = np.where(db > db.max() - drop_db)[0]
    length = len(a) / 16000
    return round(length - (int(loud[-1]) + 1) * 0.05, 2), round(length, 2)


def _mz_save():
    with open(os.path.join(_MZ_OUT, "engine_results.json"), "w") as f:
        _mz_json.dump(_MZ_RESULTS, f, indent=2)


def _mz_run_job():
    """The job runs in a worker thread, like AIQUEST's Gradio handlers: Wan2GP leaves a default-device mode active on
    the main thread, which would put the VAE's CPU canvas on the GPU (cuda:1 vs cpu error in the decode check)."""
    print(f"\n🎬 Manzi Engine: {len(_MZ_JOB.get('scenes', []))} scene(s) to make")
    sys.stdout.flush()
    for _sc in _MZ_JOB.get("scenes", []):
        _sid, _t0 = _sc["id"], time.time()
        _rec = {"id": _sid, "kind": _sc.get("kind", "scene")}
        try:
            _start = None
            if _sc.get("start_image"):
                _start = _MzImage.open(_MZ_FRAMES[_sc["start_image"]]).convert("RGB")
            _lora, _ls = NO_LORA, 1.0
            if _sc.get("lora"):  # e.g. "Natural Face" -> AIQUEST's catalog entry (strength from the catalog unless given)
                _lora = next((k for k in LORA_CATALOG if _sc["lora"].lower() in k.lower()), NO_LORA)
                if _lora != NO_LORA:
                    _ls = float(_sc.get("lora_strength", LORA_CATALOG[_lora]["scale"]))
            _rec["lora"] = None if _lora == NO_LORA else f"{_lora} @ {_ls}"
            # ---- preview, remade (new seed) when the spoken line runs into the clip's last moments ----
            _area = _MZ_PREVIEW_AREAS.get(_sc.get("preview", "384p"), 672 * 384)
            _min_tail = float(_sc.get("min_end_silence", 0.4)) if _sc.get("dialogue") else 0.0
            _seed0 = int(_sc.get("seed", -1))
            _best, _takes = None, []
            for _try in range(1 + (int(_sc.get("retries", 0)) if _min_tail else 0)):
                _seed = _seed0 + _try if _seed0 >= 0 else -1
                globals()["PREVIEW_AREA"] = _area  # AIQUEST's preview_size() reads this module-level setting
                try:
                    _path, _status, _name = make_preview(
                        _sc.get("scene", ""), _sc.get("dialogue", ""), _sc.get("language", "English"),
                        _sc.get("sound", ""), _sc.get("music", ""), _start, None, _sc.get("aspect", "16:9 Landscape"),
                        _sc.get("duration", "5 s"), _seed, _lora, _ls, NO_LORA, 1.0, "", None, 0.0, True, "euler",
                        float(_sc.get("shift", 12.0)), 0)
                finally:
                    globals()["PREVIEW_AREA"] = 672 * 384
                if not _path:
                    raise RuntimeError(_status)
                _tail, _len = _mz_speech_tail(_path) if _min_tail else (None, None)
                _takes.append({"seed_status": _status.splitlines()[0], "end_silence_s": _tail, "clip_s": _len})
                print(f"   🗣️ take {_try + 1}: silence after the last word {_tail}s (need {_min_tail}s)")
                sys.stdout.flush()
                if _best is None or (_tail or 0) > (_best[3] or 0):
                    _best = (_path, _status, _name, _tail)
                if not _min_tail or (_tail or 0) >= _min_tail:
                    break
            _path, _status, _name, _tail = _best
            _rec["takes"] = _takes
            _rec["end_silence_s"] = _tail
            _rec["timing_ok"] = (not _min_tail) or (_tail or 0) >= _min_tail
            _rec["preview_status"] = _status
            _dst = os.path.join(_MZ_OUT, f"{_sid}_{_sc.get('preview', '384p')}.mp4")
            _mz_shutil.copy(_path, _dst)
            _rec["preview"] = os.path.basename(_dst)
            _rec["preview_s"] = round(time.time() - _t0)
            if _sc.get("save_frame"):
                _fp = os.path.join(_MZ_OUT, f"{_sid}_frame.png")
                _mz_ffmpeg("-ss", str(_sc.get("frame_time", 0.0)), "-i", _dst, "-frames:v", "1", _fp)
                _MZ_FRAMES[_sid] = _fp
                _rec["frame"] = os.path.basename(_fp)
            if _sc.get("save_audio"):
                _wp = os.path.join(_MZ_OUT, f"{_sid}_voice.wav")
                _mz_ffmpeg("-i", _dst, "-vn", "-ac", "1", "-ar", "24000", _wp)
                _rec["audio"] = os.path.basename(_wp)
            if _sc.get("output") in OUTPUTS:
                _t1 = time.time()
                _preset = next((k for k in REFINE_PRESETS if _sc.get("preset", "Fast").lower() in k.lower()), DEFAULT_PRESET)
                _rec["preset"] = _preset
                _up, _ustatus = make_upscale(_name, _sc["output"], _preset, -1, True)
                _rec["upscale_status"] = _ustatus
                if _up:
                    _d2 = os.path.join(_MZ_OUT, f"{_sid}_{_sc['output'].split()[0]}.mp4")
                    _mz_shutil.copy(_up, _d2)
                    _rec["final"] = os.path.basename(_d2)
                _rec["upscale_s"] = round(time.time() - _t1)
            _rec["ok"] = True
        except Exception as _e:
            traceback.print_exc()
            _rec["ok"], _rec["error"] = False, str(_e)
        _rec["total_s"] = round(time.time() - _t0)
        _MZ_RESULTS["scenes"].append(_rec)
        _mz_save()
        print(f"{'✅' if _rec['ok'] else '❌'} {_sid}: {_rec['total_s']}s")
        sys.stdout.flush()



_mz_thread = threading.Thread(target=_mz_run_job, name="manzi-job")
_mz_thread.start()
_mz_thread.join()
print("✅ Manzi Engine: all scenes done")
sys.stdout.flush()
os._exit(0)  # the engine has daemon threads and pinned memory: leave at once so the GPUs are free for the voice stage
