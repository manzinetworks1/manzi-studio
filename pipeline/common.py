"""Shared helpers for the Manzi Studio cloud job."""
import json, os, re, subprocess, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.json")


def config():
    with open(CONFIG, encoding="utf-8") as f: return json.load(f)


def secret(name, required=True):
    v = os.environ.get(name, "").strip()
    if required and not v: raise SystemExit(f"Missing secret {name}. Add it in GitHub: Settings -> Secrets and variables -> Actions.")
    return v


def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def http_json(url, body=None, headers=None, method=None, timeout=300, tries=4):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}; h.update(headers or {})
    for k in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=h, method=method or ("POST" if data else "GET"))
            with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and k < tries - 1: log(f"  busy ({e.code}), retrying…"); time.sleep(15 * (k + 1)); continue
            raise RuntimeError(f"HTTP {e.code} from {url.split('?')[0]}: {msg}")
        except urllib.error.URLError as e:
            if k < tries - 1: time.sleep(5 * (k + 1)); continue
            raise RuntimeError(f"Couldn't reach {url.split('?')[0]}: {e}")


def ffmpeg(): return "ffmpeg"


def slug(s, n=70):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:n].rstrip("-") or "video"


STOP = set("a an the of and or to in on for with by is are was were be what which how why discuss explain describe examine critically "
           "elucidate define write short note notes on its their his her under as at from this that main grounds do does give".split())


def keywords(question, n=6):
    words = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if w not in STOP]
    return words[:n]


def wav_write(path, x, sr):
    import wave, numpy as np
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(np.asarray(x, dtype=np.int16).tobytes())


def to_pcm(data_or_path, sr=24000):
    """Any audio (bytes or file) -> mono int16 numpy array at sr."""
    import numpy as np
    is_bytes = isinstance(data_or_path, (bytes, bytearray))
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", "-" if is_bytes else data_or_path, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                       input=data_or_path if is_bytes else None, capture_output=True)
    if r.returncode: raise RuntimeError("Couldn't read audio: " + r.stderr.decode()[-200:])
    return np.frombuffer(r.stdout, np.int16)
