"""Voice for a video spec: one clip per beat with the SAME voice settings, joined with short pauses.
Every beat then knows exactly when it starts and ends (t0/t1), so the slides follow the voice perfectly.

Engines: "edge" (Microsoft Indian voices, free) and "sarvam" (Sarvam AI Bulbul, paid, Indian voices).
"""
import asyncio, base64, os, re
import numpy as np
from common import http_json, secret, to_pcm, wav_write, log

SR = 24000
GAP = {"cover": 0.9, "q": 0.6, "number": 0.5, "bust": 0.4, "timer": 0.0}


def speakable(s):
    """Small fixes so section numbers and abbreviations are read properly."""
    s = re.sub(r"\*\*", "", s)
    s = re.sub(r"\bv\.\s", " versus ", s); s = re.sub(r"\bvs\.?\s", " versus ", s)
    s = re.sub(r"\b(\d+)\((\d+)\)", r"\1, sub-section \2", s)
    s = re.sub(r"\bS\.\s?(\d)", r"Section \1", s); s = re.sub(r"\bArt\.\s?(\d)", r"Article \1", s)
    s = s.replace("&", " and ")
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ Microsoft (edge-tts)
async def _edge_one(text, voice, rate):
    import edge_tts
    try: com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError: com = edge_tts.Communicate(text, voice, rate=rate)
    audio, words = bytearray(), []
    async for ch in com.stream():
        if ch["type"] == "audio": audio += ch["data"]
        elif ch["type"] == "WordBoundary": words.append((ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))
    return bytes(audio), words


def edge_clip(text, voice, rate):
    for k in range(4):
        try: return asyncio.run(_edge_one(text, voice, rate))
        except Exception as e:
            if k == 3: raise RuntimeError(f"Microsoft voice failed: {e}")
            log(f"  Microsoft voice hiccup, retrying… ({e})"); import time; time.sleep(3 + 4 * k)


# ------------------------------------------------------------------ Sarvam AI (Bulbul)
SARVAM_URL = os.environ.get("SARVAM_URL", "https://api.sarvam.ai/text-to-speech")


def sarvam_clip(text, lang, model, speaker, pace):
    body = {"text": text[:2400], "language_code": "hi-IN" if lang == "hindi" else "en-IN", "model": model, "speaker": speaker,
            "pace": pace, "speech_sample_rate": 24000}
    r = http_json(SARVAM_URL, body, {"api-subscription-key": secret("SARVAM_API_KEY")})
    return base64.b64decode(r["audios"][0]), []


# ------------------------------------------------------------------ whole spec
def trim(x, keep=0.06):
    if len(x) == 0: return x
    hop = int(SR * 0.01); n = len(x) // hop
    if n < 3: return x
    db = 20 * np.log10(np.sqrt((x[:n * hop].astype(np.float64).reshape(n, hop) ** 2).mean(1)) + 1.0)
    loud = np.where(db > max(np.percentile(db, 95) - 40, 18.0))[0]
    if len(loud) == 0: return x
    return x[max(0, loud[0] * hop - int(keep * SR)): min(len(x), (loud[-1] + 1) * hop + int(keep * SR))]


def voice_spec(spec, cfg, out_wav, cache=None):
    """Adds t0/t1 (and word times) to every beat, writes the joined voice to out_wav, sets spec['duration']."""
    v = cfg["voice"]; eng = v.get("engine", "edge"); lang = spec.get("lang", "english")
    pieces, t = [np.zeros(int(0.35 * SR), np.int16)], 0.35
    for b in spec["beats"]:
        if b["k"] == "timer":             # quiz countdown: silence
            d = b.get("fixed", 3.0); b["t0"], b["t1"] = round(t, 3), round(t + d, 3); pieces.append(np.zeros(int(d * SR), np.int16)); t += d; continue
        text = speakable(b.get("say", ""))
        if not text: b["t0"] = b["t1"] = round(t, 3); continue
        key = (eng, text)
        if cache is not None and key in cache: data, words = cache[key]
        elif eng == "sarvam": data, words = sarvam_clip(text, lang, v.get("sarvam_model", "bulbul:v3"), v.get("sarvam_speaker", "shubh"), float(v.get("sarvam_pace", 1.0)))
        else: data, words = edge_clip(text, v.get("edge_voice_hindi" if lang == "hindi" else "edge_voice", "en-IN-PrabhatNeural"), v.get("edge_rate", "+8%"))
        if cache is not None: cache[key] = (data, words)
        raw = to_pcm(data, SR); x = trim(raw)
        # where trimming cut the start: shift word times by the same amount
        lead = (np.argmax(np.abs(raw) > 300) / SR) if len(raw) else 0
        lead = max(0.0, lead - 0.06)
        b["t0"] = round(t, 3); b["t1"] = round(t + len(x) / SR, 3)
        if words: b["words"] = [{"w": w, "t0": round(t + max(0, a - lead), 3), "t1": round(t + max(0, e - lead), 3)} for w, a, e in words]
        pieces.append(x); t += len(x) / SR
        g = GAP.get(b["k"], 0.45); pieces.append(np.zeros(int(g * SR), np.int16)); t += g
    pieces.append(np.zeros(int(0.6 * SR), np.int16)); t += 0.6
    wav_write(out_wav, np.concatenate(pieces), SR)
    spec["duration"] = round(t, 3)
    return spec
