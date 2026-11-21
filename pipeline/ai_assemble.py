"""Puts the Manzi Engine's results into the week's videos (used by make.py when out/<week>/engine/ exists).

- premade_voices(): the Professor's cloned voice for every sentence -> the voice cache (engine "manzi")
- assemble_long(): opening scene + Professor start + the notes video + Professor end -> one MP4
- scene_thumbnail(): a frame from the opening scene with the topic written on it
- CREDITS: required credit lines for the descriptions
"""
import json, os, subprocess
from common import log

CREDITS = ("🎬 AI scenes made with MiniMax H3 (MiniMax H3 Community License) · built with Wan2GP "
           "(https://github.com/deepbeepmeep/Wan2GP)")


def premade_voices(engine_dir):
    """{spoken text: wav bytes} from the voice stage's report (only pieces that passed the Whisper check). A piece is
    checked again here with numbers compared as numbers (Whisper writes "1973" where the script says "nineteen
    seventy-three"; older runs marked such sentences as failed although the Professor said them right)."""
    from numwords import match
    voices = {}
    for rep in sorted(f for f in os.listdir(engine_dir) if f.startswith("voice_") and f.endswith(".json")):
        data = json.load(open(os.path.join(engine_dir, rep), encoding="utf-8"))
        for p in data.get("pieces", []):
            path = os.path.join(engine_dir, p["file"])
            ok = p.get("passed") or (p.get("heard") and match(p.get("text", ""), p["heard"]) >= 0.85)
            if ok and os.path.exists(path):
                voices[p["text"]] = open(path, "rb").read()
    return voices


def duration(path):
    return round(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                      capture_output=True, text=True).stdout or 0), 2)


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip().split(",")
    return int(out[0]), int(out[1])


def clip(engine_dir, name):
    for suffix in ("720p", "544p", "384p"):
        p = os.path.join(engine_dir, f"{name}_{suffix}.mp4")
        if os.path.exists(p):
            return p
    return None


def assemble_long(notes_mp4, engine_dir, q, out_mp4, fps=30):
    """[opening scene] [Professor start] [notes video] [Professor end]; returns seconds added before the notes video
    (for the chapter times), or None when there is nothing to add."""
    before = [c for c in (clip(engine_dir, f"q{q}_hook"), clip(engine_dir, f"q{q}_prof_intro")) if c]
    after = [c for c in (clip(engine_dir, f"q{q}_prof_outro"),) if c]
    if not before and not after:
        return None
    w, h = _probe(notes_mp4)
    parts = before + [notes_mp4] + after
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p in parts:
        cmd += ["-i", p]
    chains = []
    for i in range(len(parts)):
        chains.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                      f"setsar=1,fps={fps},format=yuv420p[v{i}];"
                      f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(parts)))
    graph = ";".join(chains) + f";{joined}concat=n={len(parts)}:v=1:a=1[v][a]"
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4]
    subprocess.run(cmd, check=True)
    added = sum(duration(p) for p in before)
    log(f"  long video: + opening scene and Professor ({added:.1f}s before, {len(after)} clip after)")
    return added


def scene_thumbnail(engine_dir, q, title, out_png, font):
    """1280x720: the opening scene at 2.5 s, darkened at the bottom, with the topic in big letters."""
    src = clip(engine_dir, f"q{q}_hook")
    if not src:
        return None
    words, lines, cur = title.upper().split(), [], ""
    for w in words:
        if len(cur) + len(w) > 18 and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    lines = lines[:3]
    txt = os.path.splitext(out_png)[0] + ".txt"
    open(txt, "w", encoding="utf-8").write("\n".join(lines))
    vf = (f"scale=1280:720,drawbox=y=ih*0.52:w=iw:h=ih*0.48:color=black@0.62:t=fill,"
          f"drawtext=fontfile='{font}':textfile='{txt}':fontcolor=white:fontsize=78:line_spacing=10:"
          f"x=48:y=h-th-48:borderw=4:bordercolor=black@0.8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "2.5", "-i", src, "-frames:v", "1", "-vf", vf, out_png],
                   check=True)
    os.remove(txt)
    return out_png
