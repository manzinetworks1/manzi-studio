"""Manzi Studio renderer: a video spec (+ optional voice) -> MP4, drawn by a headless browser. No screen needed.

python render.py spec.json out.mp4 [--voice voice.wav] [--thumb thumb.png] [--fps 30] [--no-music]
"""
import argparse, base64, json, os, subprocess, sys, tempfile, time, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def make_music(path, dur, sr=44100):
    """Soft, royalty-free background music made from scratch (chords + a light pluck)."""
    n = int(sr * dur); tt = np.arange(n) / sr; out = np.zeros(n)
    beat = 60 / 84; bar = beat * 4
    chords = [[261.63, 329.63, 392.00], [220.00, 261.63, 329.63], [174.61, 220.00, 261.63], [196.00, 246.94, 293.66]]
    for b in range(int(dur / bar) + 1):
        ch = chords[b % 4]; s = int(b * bar * sr); e = min(n, int((b + 1) * bar * sr) + int(0.3 * sr))
        if s >= n: break
        seg = tt[s:e] - tt[s]; env = np.minimum(1, seg / 0.6) * np.exp(-seg / 3.5)
        for f in ch: out[s:e] += 0.05 * env * (np.sin(2 * np.pi * f / 2 * seg) + 0.3 * np.sin(2 * np.pi * f * seg))
        for i in range(8):
            ps = s + int(i * beat / 2 * sr); pe = min(n, ps + int(0.5 * sr))
            if ps >= n: break
            sg = tt[ps:pe] - tt[ps]; f = ch[[0, 2, 1, 2, 0, 1, 2, 1][i]] * 2
            out[ps:pe] += 0.035 * np.exp(-sg * 7) * np.sin(2 * np.pi * f * sg)
    out *= np.minimum(1, tt / 1.5) * np.minimum(1, (dur - tt) / 2.5)
    out = out / (np.max(np.abs(out)) + 1e-9) * 0.45
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((out * 32767).astype(np.int16).tobytes())


BATCH_JS = """([t0, n, dt, q]) => {
  const out = []; let last = window.__lastKey;
  for (let i = 0; i < n; i++) {
    const k = R.frame(t0 + i * dt);
    if (k !== null && k === last) out.push(null);          // same picture as before
    else { out.push(R.jpeg(q)); last = k; }
  }
  window.__lastKey = last; return out;
}"""


def render(spec, out, voice=None, thumb=None, fps=30, music=True, quality=0.9, log=print):
    from playwright.sync_api import sync_playwright
    dur = float(spec["duration"]); total = int(round(dur * fps))
    with tempfile.TemporaryDirectory() as td, sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        pg = b.new_page(viewport={"width": 400, "height": 400})
        pg.goto("file://" + os.path.join(HERE, "page.html")); pg.evaluate("s => R.setup(s)", spec)
        cmd = [ffmpeg(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-"]
        mus = None
        if music: mus = os.path.join(td, "music.wav"); make_music(mus, dur + 1)
        if voice and mus:
            cmd += ["-i", voice, "-i", mus, "-filter_complex",
                    "[1:a]aresample=48000[v];[2:a]aresample=48000,volume=0.12[m];[v][m]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[a]",
                    "-map", "0:v", "-map", "[a]"]
        elif voice: cmd += ["-i", voice, "-map", "0:v", "-map", "1:a"]
        elif mus: cmd += ["-i", mus, "-filter_complex", "[1:a]volume=0.5[a]", "-map", "0:v", "-map", "[a]"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                "-t", f"{dur:.3f}", "-movflags", "+faststart", out]
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t_start = time.time(); last = None; drawn = 0; k = 0
        while k < total:
            n = min(60, total - k)
            frames = pg.evaluate(BATCH_JS, [k / fps, n, 1 / fps, quality])
            for f in frames:
                if f is not None: last = base64.b64decode(f); drawn += 1
                ff.stdin.write(last)
            k += n
            if k % (fps * 10) < 60: log(f"  {k}/{total} frames ({100 * k // total}%), {time.time() - t_start:.0f}s")
        ff.stdin.close(); ff.wait()
        if ff.returncode: raise RuntimeError("ffmpeg failed")
        if thumb:
            pg.evaluate("() => R.thumb()"); open(thumb, "wb").write(base64.b64decode(pg.evaluate("() => R.png()")))
        b.close()
    log(f"  done: {total} frames ({drawn} drawn, {total - drawn} reused) in {time.time() - t_start:.0f}s -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec"); ap.add_argument("out"); ap.add_argument("--voice"); ap.add_argument("--thumb")
    ap.add_argument("--fps", type=int, default=30); ap.add_argument("--no-music", action="store_true")
    a = ap.parse_args()
    render(json.load(open(a.spec, encoding="utf-8")), a.out, a.voice, a.thumb, a.fps, not a.no_music)
